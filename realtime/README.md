# Realtime channel (StreamingHub)

Server of Dreams speaks two protocols. The REST API in `routes/` is the one the client
uses for everything outside a live: login, characters, shops, gacha. This package is the
**other** one — the realtime channel the game opens when it enters a multi-live, a circle
chat, or collects friend invitations.

They are genuinely different: different port, different protocol, different auth path.
The API is HTTP/1.1 JSON-ish MessagePack over FastAPI; this is **HTTP/2 + gRPC carrying
MagicOnion StreamingHub frames** on a long-lived bidirectional stream.

## Why it is not an ASGI route

A StreamingHub call is one stream that lives for the whole session:

* the response headers must be sent **before** any request body, because the client sends
  `end_stream=false` with an empty body and then waits;
* a request body may never arrive at all — `Connect` is a stream, not a request/response
  pair;
* messages flow both ways for as long as the stream lives.

Uvicorn buffers the request body, which reproduces exactly the hang that made this channel
impossible to proxy through mitmproxy. So the transport is written directly on `h2`
(`transport.py`), and it works.

## Layout

| Module | Responsibility |
| --- | --- |
| `framing.py` | gRPC frames; MagicOnion message shapes; LZ4 compression both ways |
| `methods.py` | FNV1A32 method ids, per hub |
| `dtos.py` | wire DTOs in MessagePack-CSharp array form |
| `state.py` | connections, **seats**, rooms, broadcast fan-out |
| `hub.py` | the handlers — the actual game logic |
| `transport.py` | HTTP/2 + TLS server on `h2` |
| `dispatcher.py` | binds a frame to a handler, authenticates, owns the service |

## Running it

```bash
.venv/bin/python realtime_main.py          # standalone, the usual way
```

Or in the same process as the API, by setting `realtime.auto_start: true` in `config.yml`.
Both are supported; standalone is easier to test and restart.

`config.yml`:

```yaml
realtime:
  host: 0.0.0.0
  port: 8443
  certfile: /root/wds-frida/hub-mitm.crt
  keyfile:  /root/wds-frida/hub-mitm.key
  auto_start: false
```

TLS needs **both** files; with neither the channel serves cleartext, which is only useful
for a local test. The certificate must be one the client trusts — the patched APK ships a
CA that signs only for the realtime hostname, so a self-signed cert is rejected unless the
device trusts it.

Point the client at this listener through `multi_real_time_server_url` in `/api/Environment`
(`multi_real_time_server_url` in `config.yml`).

## The protocol, as observed

Everything here is reconstructed from a **captured live session**, so shapes are
evidence-backed rather than inferred. The facts that cost the most to establish:

**Method ids are a hash, not a position.** `id = FNV1A32(methodName)` reinterpreted as a
signed int32. The name hashed is the bare declaration — no interface prefix, the `Async`
suffix kept. Verified against every id that appeared in the capture. A method id does
**not** identify a hub on its own: `JoinAsync` and `OnJoin` hash the same in two different
interfaces, so an id must always be paired with the hub it arrived on.

**Framing.** `flag(1) + length(4, big-endian) + payload`, where the payload is a MessagePack
array. `[MessageId, MethodId, args]` is a request from the client and a response from the
server — the same shape, disambiguated by direction. `[MethodId, args]` is a broadcast
(receiver callback) with **no message id**, which is exactly what makes it distinguishable.
`[-1, 0, nil]` (`0x93 0xff 0x00 0x0c`) is a marker the server sends first: the client
ignores it, a proxy needs it to flush instead of buffering.

**Every request gets a response**, including void methods, which answer `nil`. Missing that
leaves the client's `UniTask` pending forever.

**The client requires at least one frame after the headers.** `ConnectAsync` throws
"failed to negotiate with the server" if `MoveNext` completes without data, so the marker
frame is load-bearing, not cosmetic.

**Compression is on the argument, not the frame.** A large argument list arrives as
`[ExtType(98), block]` *in place of* the arguments, and a large reply as `[ExtType(99)]`.
Decoding order matters: decompress **before** flattening ext types, or the payload becomes
unrecognisable.

**Seats outlive connections.** The capture shows a client reconnecting and issuing
room-scoped calls *without joining again*, and still holding its place. So membership is a
`RoomMember` (a seat) and not a socket. A seat's state is snapshotted on disconnect so the
roster others see does not change just because a socket was replaced. Only `IMultiLiveHub`
owns seats — a circle or common-hub connection for the same account must not take one over.

**Hall type and size.** `13` = Gingaza (public), `21` = team challenge, `11`/`12`/`14`/`15`
are the other halls. Four members maximum. A public join replies with a **nil** hall id
(public rooms are addressed server-side); a private one returns its id.

## DTO layouts

MessagePack-CSharp writes `[MessagePackObject]` types as **arrays indexed by `[Key(n)]`**,
not maps. Field order is load-bearing: one field wrong shifts every following value and the
client misreads silently. Lengths, each confirmed against the capture:

* `MultiLiveCharacter` — **11**
* `MultiLiveUser` — **14**
* `CircleChat` — **11**
* `CircleActivityLog` — **8**
* `MultiLiveInvitation` — **13**
* `MultiLiveCreatePrivateHallResult` — 5, `MultiLiveJoinResult` — 6,
  `MultiLiveFetchUsersResult` — 3

## Tests

```bash
.venv/bin/python -m realtime.test_realtime   # 51 checks over a real HTTP/2 connection
.venv/bin/python -m realtime.test_tls        # TLS + real tokens from sod's own auth
.venv/bin/python -m realtime.test_replay     # replays the captured session
```

`test_realtime` drives a whole two-player session end to end: create a private hall, a
guest joins by key code, ready/decide, music and difficulty, game start, in-game sync, exit,
final results, continue play, leave, invitations, seat ownership across reconnects.

`test_replay` runs every captured request against our handlers and compares the reply
**layout** with what the real server sent. It classifies each difference:

* **structural** — a real bug; fails the run. Validated by mutation: a wrong array length, a
  misplaced nil, or a drifted nested layout is always caught.
* **state-only** — same layout, different contents. Expected: the replay runs every
  captured stream as one account while the real session had several players.
* **no-history** — we returned empty where the capture had entries (chat history, pending
  invitations). A fresh server has none.

## What is verified, and what is not

Verified against the live listener with real tokens:

* TLS + ALPN `h2` negotiate; a token minted by `make_session_jwt` is accepted and maps to
  the right user id; a forged token is refused;
* create hall → guest joins by key code → host receives `OnJoin` → `FetchUsersAsync` returns
  both members → `DecideMemberAsync` fans `OnReadyGroup` and `OnGoGame` out to the guest.

Verified by replay: 408 of 449 captured calls match the real server's reply layout exactly,
with 0 structural mismatches across all 28 methods the capture exercised.

**Not verified:**

* no real game client has connected to this listener yet — the device has not been pointed
  at it;
* chat history and the circle activity log are **in memory only** and start empty; the
  capture's non-empty pages are real server data we do not reproduce;
* `GetActivityLogsAsync` returns empty because nothing records activity yet;
* friend invitations are keyed by user id parsed from the client's friend-id strings; the
  real server's friend graph is not modelled, so an invitation only reaches a friend whose
  id happens to be a known account;
* player rank, trophies and icon frames in an invitation are placeholders (`0`), because the
  account data that would fill them is not read yet.
