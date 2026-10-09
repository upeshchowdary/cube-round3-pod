"""Download the real product photos this repo uses. They are not stored in git: data/photos.json lists each one.

  python scripts/fetch_photos.py           # download the photos that are missing (or differ), check every one
  python scripts/fetch_photos.py --check   # only report what is missing; download nothing

Each entry names the Wikimedia Commons file, where it goes in the repo, and how it was saved (width, JPEG quality) and
its sha256. The Gemini answers recorded for the real-photo units (agents/returns/cassettes/) replay only on the exact
same bytes, so every photo is checked against its sha256 after download; a mismatch is reported, never hidden.
Sources, authors and licences: data/input/RETURNS_PHOTOS.md and live_demo_sets/CREDITS.md.

`python scripts/dev.py setup`, `make setup` and the Docker build run this; without network the project still runs, the
real-photo units and demo sets just are not available.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "photos.json"
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "CUBE-Pod05-PhotoFetch/1.0 (https://github.com/upeshchowdary/cube-round3-pod)"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(client, entry: dict, dest: Path) -> None:
    """Same steps the photos were first saved with: Commons thumbnail at `width`, RGB, fit in width x width, JPEG."""
    from PIL import Image

    q = client.get(API, params={"action": "query", "titles": f"File:{entry['commons_file']}", "prop": "imageinfo",
                                "iiprop": "url", "iiurlwidth": entry["width"], "format": "json"})
    q.raise_for_status()
    page = next(iter(q.json()["query"]["pages"].values()))
    url = page["imageinfo"][0]["thumburl"]
    for attempt in range(5):
        r = client.get(url)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        break
    im = Image.open(io.BytesIO(r.content)).convert("RGB")
    im.thumbnail((entry["width"], entry["width"]))
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "JPEG", quality=entry["quality"], optimize=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only; download nothing")
    ap.add_argument("--root", type=Path, default=ROOT, help="where to put the photos (default: the repo)")
    args = ap.parse_args(argv)
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["photos"]
    todo = [e for e in entries if not (args.root / e["path"]).is_file() or sha256(args.root / e["path"]) != e["sha256"]]
    print(f"{len(entries) - len(todo)} of {len(entries)} photos present and verified")
    if args.check or not todo:
        return 1 if (args.check and todo) else 0
    import httpx

    bad = []
    with httpx.Client(headers=UA, timeout=60, follow_redirects=True) as client:
        for e in todo:
            dest = args.root / e["path"]
            try:
                fetch(client, e, dest)
            except Exception as exc:  # no network, Commons down: report and carry on
                bad.append(f"{e['path']}: download failed ({type(exc).__name__}: {exc})")
                continue
            if sha256(dest) != e["sha256"]:
                bad.append(f"{e['path']}: downloaded, but not the recorded bytes (the recorded Gemini answer for it will not replay)")
            time.sleep(0.3)
    print(f"downloaded {len(todo) - len(bad)} photo(s)")
    for b in bad:
        print("  WARNING", b)
    return 0  # never fail a setup or a build over photos: the units that need them report it themselves


if __name__ == "__main__":
    sys.exit(main())
