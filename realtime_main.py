"""Run the realtime StreamingHub channel as its own process.

Kept separate from the REST API (``main.py``) because it is a different protocol on
a different port. Running it standalone is also the quickest way to test a client
against it: point the game's ``multi_real_time_server_url`` at this listener.

    .venv/bin/python realtime_main.py

TLS is served when ``realtime.certfile``/``keyfile`` are set in config.yml. The
certificate must be one the client trusts -- the patched APK ships a CA that only
signs for the realtime hostname, so a self-signed cert will be rejected unless the
device trusts it.
"""

import asyncio
import logging
import signal

from helpers.auth import decode_jwt
from helpers.config import config
from realtime.dispatcher import build_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)


async def main() -> None:
    service = build_service(config, decode_jwt)
    await service.start()

    section = dict(config["realtime"]) if config.get("realtime") else {}
    print(
        f"realtime channel on {section.get('host', '0.0.0.0')}:{section.get('port', 8443)} "
        f"(tls={'yes' if section.get('certfile') else 'no'})"
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    await service.stop()
    print("realtime channel stopped")


if __name__ == "__main__":
    asyncio.run(main())
