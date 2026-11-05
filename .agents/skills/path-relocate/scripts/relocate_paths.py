#!/usr/bin/env python3
"""Repoint rekordbox tracks after a drive or folder rename. Dry run unless --apply.

Swaps a path prefix in DjmdContent.FolderPath, only for tracks whose old file is
gone and whose new file exists. ANLZ analysis files are deliberately left alone:
pyrekordbox can't read every .EXT or .3EX file, and rewriting them risks beatgrids,
waveforms and cues. With --apply this refuses while rekordbox is running and saves
a full database backup first.

Usage:
    python3 relocate_paths.py --from /Volumes/Old/ --to /Volumes/New/
    python3 relocate_paths.py --from /Volumes/Old/ --to /Volumes/New/ --limit 5 --apply
    python3 relocate_paths.py --from /Volumes/Old/ --to /Volumes/New/ --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from apply_core import backup_database, path_key, rekordbox_running
from rb_common import get_db


def plan_relocation(paths: dict, old_prefix: str, new_prefix: str, exists=os.path.exists):
    """Sort tracks under old_prefix into (moves, unresolved). `paths` maps
    content_id to its current FolderPath."""
    taken = {path_key(p) for p in paths.values() if p}
    moves, unresolved = [], []
    for cid, path in paths.items():
        if not (path or "").startswith(old_prefix):
            continue
        new = new_prefix + path[len(old_prefix):]
        if exists(path):
            reason = "file still exists at the old path"
        elif not exists(new):
            reason = "no file at the new path"
        elif path_key(new) in taken:
            reason = "another track already uses the new path"
        else:
            moves.append({"content_id": cid, "old": path, "new": new})
            continue
        unresolved.append({"content_id": cid, "path": path, "reason": reason})
    return moves, unresolved


def main() -> int:
    ap = argparse.ArgumentParser(description="Repoint tracks after a drive rename.")
    ap.add_argument("--from", dest="old", required=True, help="Old path prefix.")
    ap.add_argument("--to", dest="new", required=True, help="New path prefix.")
    ap.add_argument("--limit", type=int, help="Only move this many tracks, as a trial.")
    ap.add_argument("--report", default="relocate_unresolved.json",
                    help="Where to write the tracks that could not be matched.")
    ap.add_argument("--apply", action="store_true", help="Write. Without it, dry run only.")
    args = ap.parse_args()

    if args.apply and rekordbox_running():
        raise SystemExit("rekordbox appears to be RUNNING. Close it completely first.")

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    db = get_db()
    from pyrekordbox.db6 import tables

    paths = {str(c.ID): c.FolderPath or "" for c in db.get_content()}
    moves, unresolved = plan_relocation(paths, args.old, args.new)
    Path(args.report).write_text(
        json.dumps(unresolved, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(moves)} track(s) can be repointed, {len(unresolved)} unresolved "
          f"(listed in {args.report}).")
    moves = moves[:args.limit] if args.limit else moves
    for m in moves[:5]:
        print(f"  {m['old']}\n    -> {m['new']}")
    if not args.apply:
        print(f"DRY RUN. Re-run with --apply to repoint {len(moves)} track(s).")
        return 0
    if not moves:
        return 0

    db_path, backup = backup_database(db)
    now = datetime.now()
    try:
        for m in moves:
            row = db.get_content(ID=m["content_id"])
            row.FolderPath = m["new"]
            row.updated_at = now
        db.commit()
    except Exception as e:
        db.rollback()
        raise SystemExit(f"Write failed and was rolled back. Backup: {backup}\nError: {e}")

    # Query the column directly: attributes on a loaded row can stay stale.
    stored = {str(cid): p for cid, p in db.query(tables.DjmdContent.ID, tables.DjmdContent.FolderPath)}
    mismatches = [m for m in moves if stored.get(m["content_id"]) != m["new"]]
    stamp = now.strftime("%Y-%m-%d_%H%M%S")
    log_path = db_path.parent / f"relocate-log-{stamp}.json"
    log_path.write_text(json.dumps({
        "applied_at": now.isoformat(), "db_file_backup": str(backup),
        "moves": moves, "mismatches": mismatches,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Repointed {len(moves)} track(s). Backup: {backup}\nLog: {log_path}")
    if mismatches:
        print(f"WARNING: {len(mismatches)} track(s) did not verify. Restore from the "
              "backup if needed.")
        return 1
    print("Verified: every path is reflected in the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
