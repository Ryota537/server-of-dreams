"""Download the published master-data archive and unpack it into per-table JSON.

    python -m scripts.download_masterdata                  # from the GitHub release
    python -m scripts.download_masterdata --file some.zip  # unpack a local archive

Fetches the published release zip -- a bundle of per-table ``<Table>.json`` files that are
already unpacked and keyed by field name -- and writes each entry into ``_data/masterdata/``.
The ``/master-data`` route repacks them.
"""

import argparse
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT = Path(__file__).resolve().parent.parent / "_data" / "masterdata"


def _fix_character_stats(out_dir: Path) -> int:
    """Correct swapped actor base stats before saving.

    The published archive labels the master-data Status Key(0)/Key(2) fields backwards, so
    ``CharacterMaster.min_level_status`` arrives with vocal and concentration swapped. The
    real order is vocal=0, expression=1, concentration=2 (see ``models/keys.py`` Status);
    here we swap the stored values to match. Returns the number of rows corrected.
    """
    path = out_dir / "CharacterMaster.json"
    if not path.is_file():
        return 0
    rows = json.loads(path.read_text(encoding="utf-8"))
    fixed = 0
    for row in rows:
        status = row.get("min_level_status")
        if isinstance(status, dict) and "vocal" in status and "concentration" in status:
            status["vocal"], status["concentration"] = (
                status["concentration"],
                status["vocal"],
            )
            fixed += 1
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return fixed


MASTERDATA_URL = (
    "https://github.com/Ryota537/asset-of-dreams/releases/download/"
    "1.96.0-7/2026-09-29_mastermemory_1790650219_1790650219.db.zip"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=None, help="unpack a local archive instead")
    args = parser.parse_args()

    if args.file:
        data = Path(args.file).read_bytes()
        print(f"read {args.file} ({len(data)} bytes)")
    else:
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
    fixed = _fix_character_stats(OUT)
    print(f"unpacked {count} tables -> {OUT} (corrected {fixed} actor stat rows)")


main()
