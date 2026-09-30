"""Realtime StreamingHub support for Server of Dreams.

Layers, bottom up:

``framing``    gRPC frames and the MagicOnion MessagePack message shapes
``methods``    FNV1A32 method ids and the hub method tables
``dtos``       wire DTOs in MessagePack-CSharp array form
``state``      sessions and rooms
``hub``        the per-hub handlers (the game logic)
``transport``  the HTTP/2 + TLS server
``dispatcher`` binds a decoded frame to a handler and writes the reply

The protocol here is reconstructed from a captured live session, so shapes are
evidence-backed rather than inferred. ``realtime/README.md`` records what was observed,
what is verified, and what is still unverified.
"""

from realtime.dispatcher import RealtimeService

__all__ = ["RealtimeService"]
