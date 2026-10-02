import base64
import gzip
from fastapi import APIRouter, Response
from fastapi.responses import FileResponse, RedirectResponse
from starlette.exceptions import HTTPException

from helpers.assets import (
    ASSETS,
    bundle,
    bundle_path,
    catalog_br,
    catalog_hash,
    catalog_raw,
    local_assets_enabled,
    notation,
    notation_path,
    official_notation_url,
    official_url,
)

router = APIRouter(tags=["Assets"], include_in_schema=False)

# Transparent 1x1 placeholders for missing static images so BestHTTP/Unity
# doesn't exhaust download worker concurrency slots or crash.
_TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
)
_TRANSPARENT_ASTC_GZ = gzip.compress(
    bytes.fromhex("13ABA15C060601060000060000010000FCFDFFFFFFFFFFFF0000000000000000")
)


def _octet(result) -> Response:
    body, content_md5 = result
    return Response(
        content=body,
        media_type="application/octet-stream",
        headers={"Content-MD5": content_md5},
    )


# Loose static-assets (Banners, Comics, loose textures) under /production/static-assets/{path}
@router.get(
    "/production/static-assets/{filepath:path}", name="Assets_StaticAssets"
)
async def asset_static(filepath: str) -> Response:
    path = (ASSETS / "static-assets" / filepath).resolve()
    root = (ASSETS / "static-assets").resolve()
    if root in path.parents and path.is_file():
        media_type = "image/png" if filepath.endswith(".png") else "application/octet-stream"
        return FileResponse(path, media_type=media_type)

    # Missing static image fallback:
    if filepath.endswith(".astc.gz"):
        return Response(content=_TRANSPARENT_ASTC_GZ, media_type="application/octet-stream")
    if filepath.endswith(".png") or filepath.endswith(".jpg"):
        return Response(content=_TRANSPARENT_PNG, media_type="image/png")

    raise HTTPException(status_code=404, detail="Static asset not found")


# Notation charts + music_config, served under /production/Notations/{music}/{file}.enc.
# This 3-segment path must be matched here -- otherwise redirect_slashes rewrites it and the
# client tries to AES-decrypt a redirect body (crash in SymmetricTransform). We hand back the
# raw encrypted bytes (local if downloaded, else a redirect to the real CDN).
@router.get("/production/Notations/{music_id}/{filename}", name="Assets_Notation")
async def asset_notation(music_id: str, filename: str) -> Response:
    if local_assets_enabled():
        local = notation_path(music_id, filename)
        if local is not None:
            return FileResponse(local, media_type="application/octet-stream")
    return RedirectResponse(official_notation_url(music_id, filename), status_code=302)


# Everything the client fetches from assets-e (redirected here). kind is
# 2d-assets|3d-assets|cri-assets, platform Android|iOS.
#   catalog_<ver>.json.br  -> brotli of the local catalog json
#   catalog_<ver>.hash     -> spookyhash-128 of the local catalog json
#   <group>/<name>.bundle  -> local file when local_assets is on, else a redirect to
#                             the official CDN (the mitm turns that 3xx into a passthrough)
@router.get(
    "/production/{kind}/{platform}/{version}/{filepath:path}", name="Assets_Production"
)
async def asset_production(
    kind: str, platform: str, version: str, filepath: str
) -> Response:
    if filepath.endswith(".json.br"):
        result = catalog_br(kind, platform)
    elif filepath.endswith(".hash"):
        result = catalog_hash(kind, platform)
    elif filepath.endswith(".json"):
        result = catalog_raw(kind, platform)
    else:
        if local_assets_enabled():
            local = bundle_path(kind, platform, filepath)
            if local is not None:
                return FileResponse(local, media_type="application/octet-stream")
            # When local assets is enabled, never redirect to the dead official CDN (causes timeout / HE03-001-0)
            raise HTTPException(
                status_code=404, detail=f"Local bundle not found: {kind}/{platform}/{filepath}"
            )
        return RedirectResponse(
            official_url(kind, platform, version, filepath), status_code=302
        )
    if result is None:
        raise HTTPException(status_code=404)
    return _octet(result)
