#!/usr/bin/env python3
"""Write accepted artwork to rekordbox. Dry run unless --apply is passed.

Each new image is resized into rekordbox's artwork folder at 600, 240 and 80 pixels.
Tracks that gained art since the scan are skipped. Audio files are not changed.
With --apply this refuses while rekordbox is running and saves a full backup first.

Usage:
    python3 apply_artwork.py art.json
    python3 apply_artwork.py art.json --apply --limit 3
    python3 apply_artwork.py art.json --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from apply_core import backup_database, rekordbox_running
from rb_common import get_db

SIZES = (("artwork.jpg", 600), ("artwork_m.jpg", 240), ("artwork_s.jpg", 80))


def new_image_path() -> str:
    """rekordbox's layout: the first three characters of a UUID, then the rest."""
    name = str(uuid.uuid4())
    return f"/PIONEER/Artwork/{name[:3]}/{name[3:]}/artwork.jpg"


def write_images(source: str, share: Path, image_path: str) -> Path:
    folder = share / image_path.lstrip("/").rsplit("/", 1)[0]
    folder.mkdir(parents=True)
    for name, size in SIZES:
        done = subprocess.run(["sips", "-s", "format", "jpeg", "-Z", str(size), source, "--out", str(folder / name)],
                              capture_output=True, text=True)
        if done.returncode or not (folder / name).exists():
            raise RuntimeError(f"Could not resize {source}: {done.stderr.strip()}")
    return folder


def plan(groups: list, rows: dict, limit: int | None) -> tuple:
    """Accepted groups and their tracks that still have no art. Returns (writes, skipped)."""
    writes, skipped = [], 0
    for g in groups:
        if g["status"] != "accepted":
            continue
        ids = []
        for t in g["tracks"]:
            row = rows.get(t["content_id"])
            if row is None or (row.ImagePath or "").strip():
                skipped += 1
            else:
                ids.append(t["content_id"])
        if ids:
            writes.append((g, ids))
    return (writes[:limit] if limit else writes), skipped


def main(db=None) -> int:
    ap = argparse.ArgumentParser(description="Write accepted artwork to rekordbox.")
    ap.add_argument("manifest")
    ap.add_argument("--apply", action="store_true", help="Write. Without it, dry run only.")
    ap.add_argument("--limit", type=int, help="Only write this many groups, as a trial.")
    args = ap.parse_args()

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    manifest = Path(args.manifest)
    groups = json.loads(manifest.read_text(encoding="utf-8"))["groups"]
    db = db or get_db()
    rows = {str(c.ID): c for c in db.get_content()}
    writes, skipped = plan(groups, rows, args.limit)
    print(f"{len(writes)} group(s), {sum(len(i) for _, i in writes)} track(s). Skipped {skipped} that now have art or are gone.")
    for g, ids in writes[:12]:
        print(f"  {g['album'] or g['tracks'][0]['title']}: {len(ids)} track(s) from {g['source']}")
    if not args.apply:
        print("DRY RUN. Re-run with --apply to write.")
        return 0
    if rekordbox_running():
        raise SystemExit("rekordbox appears to be RUNNING. Close it completely first.")
    _, backup = backup_database(db)

    share = Path(db.share_directory)
    now = datetime.now()
    log, made = [], []
    try:
        for g, ids in writes:
            image_path = g["image_path"]
            if not image_path:
                image_path = new_image_path()
                made.append(write_images(g["image"], share, image_path))
            for cid in ids:
                rows[cid].ImagePath = image_path
                rows[cid].updated_at = now
                log.append({"content_id": cid, "image_path": image_path, "source": g["source"], "group": g["id"]})
        db.commit()
    except Exception as err:
        db.rollback()
        for folder in made:
            shutil.rmtree(folder, ignore_errors=True)
        raise SystemExit(f"Write failed and was rolled back. Backup: {backup}\nError: {err}")

    stored = {str(c.ID): c.ImagePath for c in db.get_content()}
    bad = [e["content_id"] for e in log if stored.get(e["content_id"]) != e["image_path"]
           or not (share / e["image_path"].lstrip("/")).exists()]
    stamp = now.strftime("%Y-%m-%d_%H%M%S")
    log_path = manifest.with_name(f"artwork-log-{stamp}.json")
    log_path.write_text(json.dumps({"backup": str(backup), "changes": log}, indent=2), encoding="utf-8")
    print(f"Updated {len(log)} track(s). Log: {log_path}")
    if bad:
        print(f"WARNING: {len(bad)} change(s) didn't verify. Restore from {backup} if needed.")
        return 1
    print("Verified: every image exists and every track points at it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
