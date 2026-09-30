"""Download the published master-data archive and unpack it into per-table JSON.

    python -m scripts.download_masterdata                  # from the GitHub release
    python -m scripts.download_masterdata --file some.zip  # unpack a local archive

Fetches the asset-of-dreams release zip -- a bundle of per-table ``<Table>.json``
files that are already unpacked and keyed by field name -- and writes each entry
into ``_data/masterdata/``. The ``/master-data`` route repacks them.

The live official-server path is retained (commented out) but dead: the production
endpoint now returns 410 GONE (end of service).
"""

import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Only needed by the dead live-server path below.
# from helpers.mastermemory import unpack
# from helpers.msgpack import from_array
# from models.master_data import TABLES
# from scripts._sirius import MaintenanceError, master_data_manifest
# from models import MasterDataManifest

OUT = Path(__file__).resolve().parent.parent / "_data" / "masterdata"

MASTERDATA_URL = (
    "https://github.com/Ryota537/asset-of-dreams/releases/download/"
    "1.96.0-7/2026-09-29_mastermemory_1790650219_1790650219.db.zip"
)


# def _download_url(manifest: MasterDataManifest) -> str:
#     uri, sas = manifest.uri or "", manifest.sas_token or ""
#     if uri and sas:
#         sep = "&" if "?" in uri else "?"
#         return f"{uri}{sep}{sas.lstrip('?')}"
#     return uri


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=None, help="unpack a local archive instead")
    args = parser.parse_args()

    if args.file:
        data = Path(args.file).read_bytes()
        print(f"read {args.file} ({len(data)} bytes)")
    else:
        # Live production master-data is dead -- the endpoint now returns 410 GONE
        # (end of service). Kept for reference; we fetch the pre-unpacked archive
        # from the asset-of-dreams GitHub release instead.
        #
        #     try:
        #         manifest: MasterDataManifest = master_data_manifest()
        #     except MaintenanceError:
        #         print("Server is in maintenance")
        #         return
        #     url = (
        #         "https://assets-e.wds-stellarium.com/master-data/production/"
        #         + _download_url(manifest)
        #     )
        #     print(
        #         f"master-data version {manifest.version} "
        #         f"(publish {manifest.publish_timestamp})"
        #     )
        print(f"downloading {MASTERDATA_URL}")
        req = urllib.request.Request(
            MASTERDATA_URL, headers={"User-Agent": "server-of-dreams"}
        )
        data = urllib.request.urlopen(req, timeout=120).read()
        print(f"downloaded {len(data)} bytes")

    OUT.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".json"):
                continue
            (OUT / Path(info.filename).name).write_bytes(zf.read(info))
            count += 1
    # The archive's JSON is already keyed by field name, so unlike the live blob
    # it needs no unpack/from_array pass -- we just drop the files into place.
    print(f"unpacked {count} tables -> {OUT}")


main()
