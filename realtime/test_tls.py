"""TLS + real-token test: the closest thing to how the game connects.

Starts the realtime service over TLS with the same certificate the relay uses, then
speaks to it as the game does -- h2 over TLS, ALPN h2, a Bearer token minted by sod's
own ``make_session_jwt``. Proves three things a cleartext test cannot:

* TLS + ALPN negotiate;
* a real sod token is accepted and maps to the right user id;
* a token signed with the wrong secret is refused.

Run: ``.venv/bin/python -m realtime.test_tls``
"""

from __future__ import annotations

import asyncio
import ssl
import sys

import h2.config
import h2.connection
import h2.events
import msgpack

sys.path.insert(0, "/root/server-of-dreams")

from helpers.auth import decode_jwt, make_session_jwt  # noqa: E402
from realtime import framing as F  # noqa: E402
from realtime import methods as M  # noqa: E402
from realtime.dispatcher import RealtimeService  # noqa: E402

CERT = "/root/wds-frida/hub-mitm.crt"
KEY = "/root/wds-frida/hub-mitm.key"
CA = "/root/.mitmproxy/mitmproxy-ca-cert.pem"

PASS = 0
FAIL = 0


def check(label: str, condition: bool, extra: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label} {extra}")


async def call_over_tls(port: int, hub: str, token: str, method: str, args, *, host: str = "lb-realtime.wds-stellarium.com"):
    """One request/response round trip on a fresh TLS connection."""
    ctx = ssl.create_default_context(cafile=CA)
    ctx.set_alpn_protocols(["h2"])
    reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=ctx, server_hostname=host)
    conn = h2.connection.H2Connection(
        config=h2.config.H2Configuration(client_side=True, header_encoding="latin1")
    )
    conn.initiate_connection()
    writer.write(conn.data_to_send())
    await writer.drain()

    conn.send_headers(
        1,
        [
            (":method", "POST"),
            (":scheme", "https"),
            (":authority", host),
            (":path", f"/{hub}/Connect"),
            ("content-type", "application/grpc"),
            ("te", "trailers"),
            ("authorization", f"Bearer {token}"),
        ],
    )
    conn.send_data(1, F.wrap_grpc_frame(msgpack.packb([0, 0, None])))
    writer.write(conn.data_to_send())
    await writer.drain()

    received = []
    grpc = b""
    deadline = asyncio.get_event_loop().time() + 1.5
    sent = False
    while asyncio.get_event_loop().time() < deadline:
        try:
            data = await asyncio.wait_for(reader.read(65536), timeout=0.3)
        except asyncio.TimeoutError:
            if not sent:
                conn.send_data(1, F.wrap_grpc_frame(msgpack.packb([1, M.method_id(method, hub), args])))
                writer.write(conn.data_to_send())
                await writer.drain()
                sent = True
            continue
        if not data:
            break
        for ev in conn.receive_data(data):
            if isinstance(ev, h2.events.DataReceived):
                conn.acknowledge_received_data(ev.flow_controlled_length, ev.stream_id)
                grpc += bytes(ev.data)
        writer.write(conn.data_to_send())
        await writer.drain()
        while len(grpc) >= 5 and len(grpc) >= 5 + int.from_bytes(grpc[1:5], "big"):
            length = int.from_bytes(grpc[1:5], "big")
            payload = grpc[5 : 5 + length]
            grpc = grpc[5 + length :]
            obj = msgpack.unpackb(payload, raw=False, strict_map_key=False)
            received.append(obj)
            if isinstance(obj, list) and len(obj) == 3 and obj[0] == 1:
                writer.close()
                return obj
        if not sent:
            conn.send_data(1, F.wrap_grpc_frame(msgpack.packb([1, M.method_id(method, hub), args])))
            writer.write(conn.data_to_send())
            await writer.drain()
            sent = True
    writer.close()
    return received


async def main() -> int:
    service = RealtimeService(
        host="127.0.0.1",
        port=0,
        certfile=CERT,
        keyfile=KEY,
        decode_token=decode_jwt,
    )
    await service.start()
    port = service.server._server.sockets[0].getsockname()[1]
    print(f"TLS realtime server on 127.0.0.1:{port}\n")

    print("a token minted by sod's own auth")
    token = make_session_jwt(10, "Android")
    check("token decodes back to user 10", decode_jwt(token) == 10)
    reply = await call_over_tls(port, "IMultiLiveHub", token, "CreatePrivateHallAsync",
                                [13, 13, "良太", 110, None])
    check("got a response over TLS", isinstance(reply, list) and len(reply) == 3, f"got {reply!r}")
    if isinstance(reply, list) and len(reply) == 3:
        result = reply[2]
        check("create result is 5 elements", isinstance(result, list) and len(result) == 5, f"got {result!r}")
        check("hall created", result and result[0] is True)
        check("session was registered with the token's user id",
              any(s.user_id == 10 for s in service.registry.sessions))

    print("\na token signed with the wrong secret")
    import jwt as pyjwt

    forged = pyjwt.encode(
        {"uid": "10", "nbf": 0, "exp": 9999999999, "iat": 0,
         "iss": "server-of-dreams", "aud": "github.com/UnknownSekai/server-of-dreams"},
        "wrong-secret",
        algorithm="HS256",
    )
    check("forged token does not decode", decode_jwt(forged) is None)
    out = await call_over_tls(port, "IMultiLiveHub", forged, "FetchUsersAsync", None)
    flat = str(out)
    check("forged token gets no roster", "can_open" not in flat and "fetch" not in flat.lower(),
          f"got {flat[:120]}")

    print("\na real session token over the circle hub")
    circle = await call_over_tls(port, "ICircleHub", token, "TrySendChatAsync",
                                 ["halo", None, "良太", 150050, True, None, 190003])
    check("circle hub answered over TLS", isinstance(circle, list) and len(circle) == 3, f"got {circle!r}")
    check("chat accepted", circle and circle[2] == [0], f"got {circle[2] if circle else None!r}")

    await service.stop()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
