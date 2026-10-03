"""Cloudflare R2 multi-account storage router & asset resolver.

Supports distributing asset files across multiple free Cloudflare R2 accounts
(each providing 10 GB storage free tier).

Modes supported:
1. "redirect" (HTTP 302 Found) - redirects client directly to R2 public URL / custom domain.
2. "proxy" (HTTP 200 Streaming) - downloads stream from R2 and proxies it to client.

Zero external dependencies required (uses standard library urllib & fastapi).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from typing import Iterator, Optional
import urllib.error
import urllib.request

from fastapi import Response
from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.exceptions import HTTPException

from helpers.config import config

logger = logging.getLogger("sod.r2")

_executor = ThreadPoolExecutor(max_workers=16)


def _get_r2_settings() -> dict:
    sec = config.get("r2_storage") or {}
    if not isinstance(sec, dict):
        return {}
    return sec


def r2_enabled() -> bool:
    """Return True if R2 multi-account storage routing is enabled in config."""
    return bool(_get_r2_settings().get("enabled", False))


def get_r2_mode() -> str:
    """Return routing mode: 'redirect' (default) or 'proxy'."""
    mode = str(_get_r2_settings().get("mode", "redirect")).lower()
    return "proxy" if mode == "proxy" else "redirect"


def resolve_r2_target_url(category: str, subpath: str) -> Optional[str]:
    """Find matching R2 account base URL for a given asset category and path.

    Categories can be:
    - "cri-assets" (or alias "cri")
    - "2d-assets" (or alias "2d")
    - "3d-assets" (or alias "3d")
    - "static-assets" (or alias "static")
    - "notations"

    Prefix rules inside routes are also supported, e.g.:
    routes:
      cri: "https://r2-cri.example.com"
      2d: "https://r2-2d.example.com"
      3d_characters: "https://r2-3d-a.example.com"  # matched by prefix if configured
      3d: "https://r2-3d-b.example.com"             # fallback 3d bucket
    """
    settings = _get_r2_settings()
    routes = settings.get("routes", {})
    if not isinstance(routes, dict):
        return None

    clean_category = category.lower().replace("-assets", "").replace("_assets", "")
    subpath_clean = subpath.lstrip("/").replace("\\", "/")

    # 1. Exact match on category + prefix if specified with colon or slash
    # e.g., "3d:characters": "https://..."
    for key, base_url in routes.items():
        key_lower = str(key).lower()
        if ":" in key_lower:
            cat_prefix, match_prefix = key_lower.split(":", 1)
            cat_prefix = cat_prefix.replace("-assets", "")
            if cat_prefix in (clean_category, category.lower()) and subpath_clean.lower().startswith(match_prefix.lower()):
                return f"{str(base_url).rstrip('/')}/{subpath_clean}"

    # 2. Match standard category or its aliases
    alias_map = {
        "cri-assets": ["cri", "cri-assets", "cri_assets"],
        "2d-assets": ["2d", "2d-assets", "2d_assets"],
        "3d-assets": ["3d", "3d-assets", "3d_assets"],
        "static-assets": ["static", "static-assets", "static_assets"],
        "notations": ["notations", "notation"],
    }
    candidates = alias_map.get(category.lower(), [category.lower(), clean_category])
    for cand in candidates:
        if cand in routes:
            return f"{str(routes[cand]).rstrip('/')}/{subpath_clean}"

    # 3. Default fallback route if provided
    if "default" in routes:
        return f"{str(routes['default']).rstrip('/')}/{category}/{subpath_clean}"

    return None


def _sync_stream_r2(url: str, chunk_size: int = 65536) -> tuple[int, dict, Iterator[bytes]]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Sirius-R2-Router/1.0"},
    )
    resp = urllib.request.urlopen(req, timeout=15)
    headers = {
        "Content-Type": resp.headers.get("Content-Type", "application/octet-stream"),
        "Content-Length": resp.headers.get("Content-Length", ""),
        "ETag": resp.headers.get("ETag", ""),
    }
    # Clean empty header values
    headers = {k: v for k, v in headers.items() if v}

    def _iterator() -> Iterator[bytes]:
        try:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            resp.close()

    return resp.status, headers, _iterator()


async def serve_r2_asset(category: str, subpath: str) -> Optional[Response]:
    """Resolve asset from Cloudflare R2 if configured and enabled.

    Returns:
    - RedirectResponse (mode="redirect")
    - StreamingResponse (mode="proxy")
    - None (if R2 not enabled or category not mapped -> fall back to local disk)
    """
    if not r2_enabled():
        return None

    target_url = resolve_r2_target_url(category, subpath)
    if not target_url:
        return None

    mode = get_r2_mode()
    if mode == "redirect":
        return RedirectResponse(target_url, status_code=302)

    # Proxy mode: stream directly through SOD
    loop = asyncio.get_running_loop()
    try:
        status, headers, iterator = await loop.run_in_executor(
            _executor, lambda: _sync_stream_r2(target_url)
        )
        return StreamingResponse(
            iterator,
            status_code=status,
            media_type=headers.get("Content-Type", "application/octet-stream"),
            headers=headers,
        )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Let caller handle or fallback to local / dummy transparent
            logger.info("R2 object not found (404): %s", target_url)
            return None
        logger.warning("R2 upstream error %s for %s", e.code, target_url)
        raise HTTPException(status_code=502, detail=f"R2 upstream returned {e.code}")
    except Exception as exc:
        logger.warning("Failed to proxy from R2 (%s): %s", target_url, exc)
        return None
