#!/usr/bin/env python3
"""Write accepted metadata to rekordbox. Dry run unless --apply is passed.

Sets artist and title, plus album and year only where they are blank. A track that
gained an artist since the scan is skipped, unless its entry has `replace_artist`,
which only needs the artist to be unchanged since the scan. Audio files' own tags are
not changed.
With --apply this refuses while rekordbox is running and saves a full backup first.

Usage:
    python3 apply_metadata.py metadata.json
    python3 apply_metadata.py metadata.json --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from apply_core import backup_database, rekordbox_running
from rb_common import get_db


def plan_writes(entries: list, artists: dict) -> tuple[list, list]:
    """`artists` maps content_id to its current artist, for tracks still in the
    library. Returns (writes, skipped)."""
    writes, skipped = [], []
    for e in entries:
        if e["status"] != "accepted":
            continue
        cid = e["content_id"]
        if cid not in artists:
            skipped.append((e, "no longer in the library"))
        elif e.get("replace_artist"):
            if artists[cid] == e["current"]["artist"].strip():
                writes.append(e)
            else:
                skipped.append((e, f"artist changed since the scan: {artists[cid]}"))
        elif artists[cid]:
            skipped.append((e, f"already has an artist: {artists[cid]}"))
        else:
            writes.append(e)
    return writes, skipped


def named(db, table, name: str, create):
    return db.query(table).filter(table.Name == name).first() or create()


def main() -> int:
    ap = argparse.ArgumentParser(description="Write accepted metadata to rekordbox.")
    ap.add_argument("manifest")
    ap.add_argument("--apply", action="store_true", help="Write. Without it, dry run only.")
    args = ap.parse_args()

    entries = json.loads(Path(args.manifest).read_text(encoding="utf-8"))["entries"]
    if args.apply and rekordbox_running():
        raise SystemExit("rekordbox appears to be RUNNING. Close it completely first.")

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    db = get_db()
    from pyrekordbox.db6 import tables

    rows = {str(c.ID): c for c in db.get_content()}
    writes, skipped = plan_writes(
        entries, {cid: (c.ArtistName or "").strip() for cid, c in rows.items()})
    print(f"{len(writes)} track(s) to update, {len(skipped)} skipped.")
    for e in writes:
        p = e["proposed"]
        print(f"  {e['current']['title'][:45]!r} -> {p['artist']} - {p['title']}"
              f" | {p['album']} {p['year'] or ''}")
    for e, reason in skipped:
        print(f"  SKIP {e['current']['title'][:45]!r}: {reason}")
    if not args.apply:
        print("DRY RUN. Re-run with --apply to write.")
        return 0
    if not writes:
        return 0

    db_path, backup = backup_database(db)
    now = datetime.now()
    log = []
    try:
        for e in writes:
            p, row = e["proposed"], rows[e["content_id"]]
            log.append({"content_id": e["content_id"], "old_title": row.Title,
                        "old_artist_id": row.ArtistID, "old_album_id": row.AlbumID,
                        "old_year": row.ReleaseYear, "new": p})
            artist_id = row.ArtistID
            if not e.get("replace_artist") or p["artist"] != e["current"]["artist"]:
                artist_id = named(db, tables.DjmdArtist, p["artist"],
                                  lambda: db.add_artist(name=p["artist"])).ID
                row.ArtistID = artist_id
            row.Title = p["title"]
            if p["album"] and (not row.AlbumID or e.get("replace_album")):
                album = named(db, tables.DjmdAlbum, p["album"],
                              lambda: db.add_album(name=p["album"], artist=artist_id))
                row.AlbumID = album.ID
            if p["year"] and not row.ReleaseYear:
                row.ReleaseYear = int(p["year"])
            row.updated_at = now
        db.commit()
    except Exception as err:
        db.rollback()
        raise SystemExit(f"Write failed and was rolled back. Backup: {backup}\nError: {err}")

    stored = {str(cid): (aid, title) for cid, aid, title in
              db.query(tables.DjmdContent.ID, tables.DjmdContent.ArtistID, tables.DjmdContent.Title)}
    mismatches = [e["content_id"] for e in writes
                  if not stored[e["content_id"]][0]
                  or stored[e["content_id"]][1] != e["proposed"]["title"]]
    log_path = db_path.parent / f"metadata-log-{now.strftime('%Y-%m-%d_%H%M%S')}.json"
    log_path.write_text(json.dumps({
        "applied_at": now.isoformat(), "db_file_backup": str(backup),
        "writes": log, "mismatches": mismatches,
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(f"Updated {len(writes)} track(s). Backup: {backup}\nLog: {log_path}")
    if mismatches:
        print(f"WARNING: {len(mismatches)} track(s) did not verify. Restore from the "
              "backup if needed.")
        return 1
    print("Verified: every change is reflected in the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
