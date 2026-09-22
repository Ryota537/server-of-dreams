"""Download every notation chart + music_config for the game into ``_data/assets/``.

    python -m scripts.download_notations --dry-run   # check availability first
    python -m scripts.download_notations             # actually download

The CDN layout is ``<asset_url>/Notations/<dir>/<file>`` where:

- ``<dir>`` is ``LiveMaster.music_master_id`` for normal charts, or
  ``AnotherNotationMaster.notation_path`` for alternate charts. Note that a chart's
  directory is NOT ``LiveMaster.id`` (that id is never used in a URL).
- ``<file>`` is ``<difficulty>.enc`` for a chart (the difficulty value, not a fixed
  ``1.enc``) and ``music_config.enc`` for the shared per-directory config.

Files are AES/brotli-encrypted; the client decrypts them, so they are stored verbatim.
Existing files are skipped, so re-running resumes. This mirrors ``_data/assets/<kind>/``
by writing to ``_data/assets/Notations/<dir>/<file>``.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "_data" / "assets"
MASTERDATA = Path(__file__).resolve().parent.parent / "_data" / "masterdata"
ASSET_URL = "https://assets-e.wds-stellarium.com/production"
OUT = ASSETS / "Notations"
_UA = "server-of-dreams"


def expected_files() -> list:
    """Distinct ``<dir>/<file>`` notation paths implied by the master data."""
    dirs = {}  # dir -> set of chart filenames

    live = json.loads((MASTERDATA / "LiveMaster.json").read_text(encoding="utf-8"))
    for row in live:
        d = str(row["music_master_id"])
        dirs.setdefault(d, set()).add(f"{row['difficulty']}.enc")

    another = json.loads(
        (MASTERDATA / "AnotherNotationMaster.json").read_text(encoding="utf-8")
    )
    for row in another:
        d = str(row["notation_path"])
        dirs.setdefault(d, set()).add(f"{row['difficulty']}.enc")

    out = []
    for d, names in dirs.items():
        for name in sorted(names):
            out.append(f"{d}/{name}")
        out.append(f"{d}/music_config.enc")
    return sorted(out)


def _head(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "server-of-dreams"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


def _looks_like_challenge(head: bytes) -> bool:
    """True when the CDN returned an anti-bot challenge page instead of the asset.

    assets-e sits behind a WAF that, under concurrency, answers 200 with an obfuscated
    ``<script>`` HTML page (content-type text/html) instead of the encrypted binary.
    Writing that to disk silently corrupts the asset, so it is detected and retried.
    """
    h = head[:64].lstrip().lower()
    return h.startswith(b"<script") or h.startswith(b"<html") or h.startswith(b"<!doctype")


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _download(url: str, dest: Path, attempts: int = 6) -> str:
    if dest.exists() and not _looks_like_challenge(dest.read_bytes()[:64]):
        return "skip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            body = _fetch(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            body = b""
        if body and not _looks_like_challenge(body):
            tmp = dest.with_name(dest.name + ".part")
            with open(tmp, "wb") as f:
                f.write(body)
            tmp.replace(dest)  # atomic: a killed download never leaves a "complete" file
            return "ok"
        if attempt == attempts:
            raise RuntimeError("WAF challenge persisted")
        time.sleep(delay)
        delay = min(delay * 2, 20.0)
    return "err"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="HEAD every file, download none")
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="parallel downloads (keep low: assets-e throttles into a WAF challenge)",
    )
    parser.add_argument("--limit", type=int, default=0, help="max files (debugging)")
    args = parser.parse_args()

    rels = expected_files()
    if args.limit:
        rels = rels[: args.limit]
    print(f"{len(rels)} notation files expected -> {OUT}")

    if args.dry_run:
        missing = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(_head, f"{ASSET_URL}/Notations/{rel}"): rel for rel in rels
            }
            for fut in as_completed(futures):
                if fut.result() != 200:
                    missing.append((futures[fut], fut.result()))
        print(f"available: {len(rels) - len(missing)}/{len(rels)} | missing: {len(missing)}")
        for rel, code in sorted(missing)[:40]:
            print(f"  ! {rel} ({code})")
        return

    ok = skip = err = done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_download, f"{ASSET_URL}/Notations/{rel}", OUT / rel): rel
            for rel in rels
        }
        for fut in as_completed(futures):
            done += 1
            try:
                res = fut.result()
                ok += res == "ok"
                skip += res == "skip"
            except urllib.error.HTTPError as e:
                err += 1
                print(f"  ! {futures[fut]} ({e.code})")
            except Exception as e:  # noqa: BLE001
                err += 1
                print(f"  ! {futures[fut]} ({type(e).__name__})")
            if done % 200 == 0 or done == len(rels):
                print(f"  {done}/{len(rels)} ok={ok} skip={skip} err={err}")


main()
