"""Serve the local Addressables catalogs. Everything derives from the decompressed
``assets/<kind>/<platform>/catalog.json`` that ``download_all_assets`` writes:

- ``.json.br`` -> brotli of that json (the client decompresses it by extension)
- ``.hash``    -> SpookyHash-128 of that json, little-endian, lowercase hex

Both carry a ``Content-MD5`` (base64 of md5) matching the official server. Results
are memoized since compression/hashing the 10-50 MB catalogs is not free.
"""

import base64
import hashlib
from pathlib import Path
from typing import Dict, Optional, Tuple

import brotli
import spookyhash

from helpers.config import config

ASSETS = Path(__file__).resolve().parent.parent / "_data" / "assets"
# where bundle requests are redirected when local_assets is off (hardcoded on purpose)
OFFICIAL_ASSET_URL = "https://assets-e.wds-stellarium.com/production"

_br_cache: Dict[str, Tuple[bytes, str]] = {}
_hash_cache: Dict[str, Tuple[bytes, str]] = {}


def _catalog(kind: str, platform: str) -> Optional[bytes]:
    path = ASSETS / kind / platform.lower() / "catalog.json"
    return path.read_bytes() if path.is_file() else None


def _content_md5(body: bytes) -> str:
    return base64.b64encode(hashlib.md5(body).digest()).decode()


def catalog_br(kind: str, platform: str) -> Optional[Tuple[bytes, str]]:
    key = f"{kind}/{platform.lower()}"
    if key not in _br_cache:
        raw = _catalog(kind, platform)
        if raw is None:
            return None
        body = brotli.compress(raw, quality=5)
        _br_cache[key] = (body, _content_md5(body))
    return _br_cache[key]


def catalog_hash(kind: str, platform: str) -> Optional[Tuple[bytes, str]]:
    key = f"{kind}/{platform.lower()}"
    if key not in _hash_cache:
        raw = _catalog(kind, platform)
        if raw is None:
            return None
        body = spookyhash.hash128(raw).to_bytes(16, "little").hex().encode()
        _hash_cache[key] = (body, _content_md5(body))
    return _hash_cache[key]


def local_assets_enabled() -> bool:
    return bool(config["local_assets"])


_KINDS = ("2d-assets", "3d-assets", "cri-assets")


def bundle(kind: str, platform: str, rel_path: str) -> Optional[Tuple[bytes, str]]:
    """A local asset bundle and its Content-MD5, or None if not downloaded anywhere. Not
    memoized -- there are tens of thousands of bundles.

    A bundle filename identifies the same content regardless of which kind-host serves it, and
    asset groups are kind-exclusive, so a given <group>/<file> path lives under at most one kind.
    The client probes 2d->3d->cri for a bundle and uses the first hit, so a bundle that lives only
    under one kind (e.g. cri-only adventure se/voice/acb) must be served for a request to ANY kind
    -- otherwise the offline server 302s the probe to the official CDN. Try the requested kind
    first, then the others in probe order."""
    plat = platform.lower()

    def _try(k: str) -> Optional[Tuple[bytes, str]]:
        path = (ASSETS / k / plat / rel_path).resolve()
        root = (ASSETS / k / plat).resolve()
        if root not in path.parents or not path.is_file():  # stay inside the asset dir
            return None
        body = path.read_bytes()
        return body, _content_md5(body)

    hit = _try(kind)
    if hit is not None:
        return hit
    for k in _KINDS:
        if k != kind and (hit := _try(k)) is not None:
            return hit
    return None


def official_url(kind: str, platform: str, version: str, rel_path: str) -> str:
    return f"{OFFICIAL_ASSET_URL}/{kind}/{platform}/{version}/{rel_path}"


def static_content(rel_path: str) -> Optional[Tuple[bytes, str]]:
    """A local static-content file (event/gacha banner textures, under static-assets/Resources)
    and its Content-MD5, or None if not downloaded. Served raw -- the client reads the png /
    astc.gz as-is. Not memoized (thousands of banners)."""
    path = (ASSETS / "static-assets" / rel_path).resolve()
    root = (ASSETS / "static-assets").resolve()
    if root not in path.parents or not path.is_file():  # stay inside the dir
        return None
    body = path.read_bytes()
    return body, _content_md5(body)


def official_static_url(rel_path: str) -> str:
    return f"{OFFICIAL_ASSET_URL}/static-assets/{rel_path}"


def notation(music_id: str, filename: str) -> Optional[Tuple[bytes, str]]:
    """A local encrypted notation/music_config .enc and its Content-MD5, or None if absent.

    Served verbatim (still AES/brotli-encrypted) -- the client decrypts it, so we must
    never hand it a redirect body or a decoded file."""
    path = (ASSETS / "Notations" / music_id / filename).resolve()
    root = (ASSETS / "Notations").resolve()
    if root not in path.parents or not path.is_file():
        return None
    body = path.read_bytes()
    return body, _content_md5(body)


def official_notation_url(music_id: str, filename: str) -> str:
    return f"{OFFICIAL_ASSET_URL}/Notations/{music_id}/{filename}"
