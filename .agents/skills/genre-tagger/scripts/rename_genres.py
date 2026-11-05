#!/usr/bin/env python3
"""Rename genre labels across the library from an explicit map. Dry run unless --apply.

The map is a JSON object of {"old label": "new label"}; an empty new label clears
the genre. Matching is exact, so `techno` and `Techno` are separate keys. With
--apply this refuses while rekordbox is running and saves a full backup first.

Usage:
    python3 rename_genres.py renames.json
    python3 rename_genres.py renames.json --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from apply_core import backup_database, rekordbox_running
from rb_common import get_db


def plan_renames(current: dict, renames: dict) -> list:
    """`current` maps content_id to its genre label. Returns the tracks that change."""
    return [{"content_id": cid, "old": old, "new": renames[old]}
            for cid, old in current.items() if old in renames and renames[old] != old]


def main() -> int:
    ap = argparse.ArgumentParser(description="Rename genre labels across the library.")
    ap.add_argument("renames", help="JSON map of old label to new label.")
    ap.add_argument("--apply", action="store_true", help="Write. Without it, dry run only.")
    args = ap.parse_args()

    renames = json.loads(Path(args.renames).read_text(encoding="utf-8"))
    if args.apply and rekordbox_running():
        raise SystemExit("rekordbox appears to be RUNNING. Close it completely first.")

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    db = get_db()
    from pyrekordbox.db6 import tables

    rows = {str(c.ID): c for c in db.get_content()}
    current = {cid: (c.GenreName or "").strip() for cid, c in rows.items()}
    changes = plan_renames(current, renames)

    print(f"{len(changes)} track(s) change, across "
          f"{len({c['old'] for c in changes})} label(s).")
    for (old, new), n in Counter((c["old"], c["new"]) for c in changes).most_common():
        print(f"  {n:5}  {old!r} -> {new or '(blank)'}")
    if not args.apply:
        print("DRY RUN. Re-run with --apply to write.")
        return 0
    if not changes:
        return 0

    db_path, backup = backup_database(db)
    now = datetime.now()
    try:
        ids = {}
        for name in sorted({c["new"] for c in changes if c["new"]}):
            # Exact-case lookup: the point is to land on this spelling.
            found = db.query(tables.DjmdGenre).filter(tables.DjmdGenre.Name == name).first()
            ids[name] = (found or db.add_genre(name=name)).ID
        for c in changes:
            row = rows[c["content_id"]]
            row.GenreID = ids[c["new"]] if c["new"] else None
            row.updated_at = now
        db.commit()
    except Exception as e:
        db.rollback()
        raise SystemExit(f"Write failed and was rolled back. Backup: {backup}\nError: {e}")

    stored = {str(cid): gid for cid, gid in
              db.query(tables.DjmdContent.ID, tables.DjmdContent.GenreID)}
    mismatches = [c for c in changes
                  if stored.get(c["content_id"]) != (ids[c["new"]] if c["new"] else None)]
    log_path = db_path.parent / f"genre-rename-log-{now.strftime('%Y-%m-%d_%H%M%S')}.json"
    log_path.write_text(json.dumps({
        "applied_at": now.isoformat(), "db_file_backup": str(backup),
        "changes": changes, "mismatches": mismatches,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Updated {len(changes)} track(s). Backup: {backup}\nLog: {log_path}")
    if mismatches:
        print(f"WARNING: {len(mismatches)} track(s) did not verify. Restore from the "
              "backup if needed.")
        return 1
    print("Verified: every genre is reflected in the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
