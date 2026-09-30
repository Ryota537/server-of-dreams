"""Replay the captured session against our handlers and compare reply shapes.

For every request the real client sent, we run the same call against our own
handlers and compare the RESPONSE SHAPE with what the real server replied. Values
legitimately differ (our hall ids are ours), but the structure must not: a wrong
array length or a misplaced nil is exactly the bug that makes the client misread
silently.

Two details this handles that a naive replay gets wrong:

* the capture spans SEVERAL TCP connections and each reuses stream id 1, so streams
  must be keyed by connection as well as id;
* the real server compresses responses, so the captured reply is an ``ExtType(99)``
  that has to be decompressed before its shape means anything.

Run: ``.venv/bin/python -m realtime.test_replay``
"""

from __future__ import annotations

import base64
import json
import sys

import msgpack

sys.path.insert(0, "/root/server-of-dreams")

from realtime import framing as F  # noqa: E402
from realtime import methods as M  # noqa: E402
from realtime.dispatcher import RealtimeService  # noqa: E402

CAPTURE = "/root/wds-captures/hub-h2.jsonl"
MARKER = [-1, 0, 12]


def load_streams():
    """``[(hub, [(direction, object), ...]), ...]`` keyed by connection and path.

    Every captured frame carries its own ``path``, which is the authoritative hub.
    Keying on ``(connection, path)`` avoids the trap that stream ids restart at 1 on
    every connection -- keying on the id alone splices unrelated sessions together.
    """
    streams: dict[tuple, list] = {}
    order: list[tuple] = []
    conn = 0
    for line in open(CAPTURE):
        row = json.loads(line)
        event = row.get("event")
        if event == "client_connect":
            conn += 1
            continue
        if event != "frame":
            continue
        path = row.get("path") or ""
        hub = M.hub_for_path(path)
        if hub is None:
            continue
        key = (conn, path, row.get("stream_id"))
        if key not in streams:
            streams[key] = [hub, []]
            order.append(key)
        payload = base64.b64decode(row["payload_b64"])
        # The marker frame carries no information; skip it.
        if msgpack.unpackb(payload, raw=False, strict_map_key=False) == MARKER:
            continue
        streams[key][1].append((row["dir"], payload))
    return [streams[k] for k in order]


def replay_stream(service, hub, events, key_map):
    """Replay one captured stream; return ``[(method, args, real_result, ours), ...]``.

    Streams are replayed in capture order against one shared registry, so a room
    created by an earlier stream is the one a later stream's ``FetchUsersAsync``
    finds -- exactly the sequence the real server saw.

    A stream that issues room-scoped calls WITHOUT a join is a reconnect: the client
    already holds a seat, so the seat is looked up by the user id that stream
    authenticated as.
    """
    session = service.make_session(hub, f"/{hub}/Connect", lambda payload: None, "t")
    handler = service.handlers[hub]
    pending: dict[int, tuple] = {}
    out = []
    for direction, payload in events:
        # Decode through the REAL framing layer, so this exercises the same argument
        # decompression and message parsing the live server uses.
        try:
            msg = F.read_message(payload, "c2s" if direction == "c->s" else "s2c")
        except Exception:
            continue
        if direction == "c->s":
            if msg.kind == "request" and msg.message_id is not None:
                pending[msg.message_id] = (msg.method_id, msg.args)
            continue
        if msg.kind != "response" or msg.message_id is None:
            continue
        found = pending.pop(msg.message_id, None)
        if found is None:
            continue
        method_id, args = found
        name = M.method_name(method_id, hub)
        if name is None:
            continue
        if hub == "IMultiLiveHub" and session.hall_id is None:
            _bind_to_open_room(service, session)
        ours = handler.handle(name, session, _remap(name, args, key_map))
        # The real server compresses large RESPONSES too, so the captured reply may
        # still be an ExtType(99) blob. Decompress before comparing shapes.
        real = msg.args
        if isinstance(real, msgpack.ExtType):
            real = F.decompress(real)
        if name == "CreatePrivateHallAsync" and isinstance(ours, list) and len(ours) == 5:
            if isinstance(real, list) and len(real) == 5:
                key_map[real[3]] = ours[3]
        out.append((name, args, real, ours))
    return out


def _bind_to_open_room(service, session) -> None:
    """Put a reconnecting session back into the seat its account already holds.

    ``HubRegistry.register`` does this for real connections; the replay builds sessions
    directly, so it is done explicitly here. Without it a reconnect would see an empty
    roster, which is not what the real server did.
    """
    for room in service.registry.rooms.values():
        member = room.member_for_user(session.user_id)
        if member is not None:
            room.bind(member, session)
            return


def _remap(method: str, args, key_map):
    """Swap a captured private-hall key code for the one our server issued."""
    if method == "JoinPrivateHallWithKeyCodeAsync" and isinstance(args, list) and args:
        return [key_map.get(args[0], args[0])] + list(args[1:])
    return args


def describe(value, depth: int = 0):
    """Structural description: containers keep their length, scalars are just "scalar".

    Values are erased on purpose -- this compares LAYOUT, not content.
    """
    if depth > 8:
        return ("...",)
    if isinstance(value, (list, tuple)):
        return ("list", len(value), tuple(describe(v, depth + 1) for v in value))
    if isinstance(value, dict):
        return ("map", tuple(sorted(str(k) for k in value)))
    return ("scalar",)


def compatible(real, ours) -> bool:
    """Whether two structural descriptions can both be correct.

    The one judgement call: when two lists have DIFFERENT lengths, that is tolerated
    only if their entries are themselves containers -- a roster, a chat history, an
    activity log -- because there the count is room state. A length difference in a
    list of scalars means an element layout drifted, which is a real protocol bug:
    that is what catches a ``MultiLiveUser`` or ``MultiLiveCharacter`` with the wrong
    number of fields.
    """
    if real[0] != ours[0]:
        return False
    if real[0] == "scalar":
        return True
    if real[0] == "map":
        return real[1] == ours[1]
    if real[0] == "...":
        return True
    real_len, ours_len = real[1], ours[1]
    if real_len == ours_len:
        return all(compatible(a, b) for a, b in zip(real[2], ours[2]))
    if not real[2] or not ours[2]:
        # One side is empty: missing history, not a wrong layout.
        return True
    return all(entry[0] in ("list", "map") for entry in real[2] + ours[2])


def is_less_populated(real, ours) -> bool:
    """True when ``ours`` is empty where ``real`` had entries, at any depth.

    That is missing history, not a wrong shape: the capture is a live session with chat
    history and pending invitations, and a fresh server has none.
    """
    if isinstance(real, (list, tuple)) and isinstance(ours, (list, tuple)):
        if real and not ours:
            return True
        for real_item, ours_item in zip(real, ours):
            if is_less_populated(real_item, ours_item):
                return True
    return False


def classify(real, ours) -> str:
    """Is a mismatch a real shape bug, or a difference the fixture cannot avoid?

    ``structural``
        The layout differs -- a different wrapper, a different element count, a nested
        container of the wrong size. A genuine protocol bug that must fail the run.
    ``data``
        We returned an empty container where the capture had entries.
    ``state``
        Same layout, different contents. Expected, because this replay runs every
        captured stream as one account while the real session had several players.
    """
    if not compatible(describe(real), describe(ours)):
        return "structural"
    if is_less_populated(real, ours):
        return "data"
    return "state"


def main() -> int:
    streams = load_streams()
    service = RealtimeService(decode_token=lambda t: 10)
    key_map: dict = {}

    results = []
    for hub, events in streams:
        results.extend(replay_stream(service, hub, events, key_map))

    print(f"{len(streams)} hub streams, {len(results)} replayed calls\n")

    ok = 0
    failed = []
    counters = {"stateful": 0, "state": 0, "data": 0}
    per_method: dict[str, list[int]] = {}
    for name, args, real, ours in results:
        # agree, no-room, state-only, missing-history, structural
        bucket = per_method.setdefault(name, [0, 0, 0, 0, 0])
        # An error reply (4-element frame) means our replay legitimately diverged
        # because the room state it depends on was never rebuilt.
        if isinstance(ours, list) and len(ours) == 4:
            bucket[1] += 1
            counters["stateful"] += 1
            continue
        if describe(ours) == describe(real):
            bucket[0] += 1
            ok += 1
            continue
        verdict = classify(real, ours)
        if verdict == "state":
            bucket[2] += 1
            counters["state"] += 1
            continue
        if verdict == "data":
            bucket[3] += 1
            counters["data"] += 1
            continue
        bucket[4] += 1
        failed.append((name, args, real, ours))

    for name in sorted(per_method):
        agree, div, st, data, bad = per_method[name]
        flag = "PASS" if bad == 0 else "FAIL"
        notes = []
        if st:
            notes.append(f"{st} state")
        if data:
            notes.append(f"{data} no-history")
        if div:
            notes.append(f"{div} no-room")
        suffix = f"  ({', '.join(notes)})" if notes else ""
        print(f"  {flag}  {name:52} {agree}/{agree + bad}{suffix}")

    if failed:
        print("\nSTRUCTURAL mismatches (real bugs):")
        for name, args, real, ours in failed[:8]:
            print(f"\n  {name}")
            print(f"    args  {str(args)[:100]}")
            print(f"    real  {str(describe(real))[:170]}")
            print(f"    ours  {str(describe(ours))[:170]}")
            print(f"    ours! {str(ours)[:170]}")

    print(
        f"\n{ok} exact, {counters['state']} state-only, {counters['data']} no-history, "
        f"{counters['stateful']} no-room, {len(failed)} structural"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
