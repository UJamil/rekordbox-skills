#!/usr/bin/env python3
"""Write accepted genres to rekordbox. Dry run unless --apply is passed.

Only `accepted` entries are written. A track whose genre changed since the scan is
skipped, so a manual edit is never overwritten. With --apply this refuses while
rekordbox is running and saves a full database backup first.

Usage:
    python3 apply_genres.py genres.json            # dry run
    python3 apply_genres.py genres.json --apply    # write for real
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


def plan_writes(entries: list, current: dict, existing: dict) -> tuple[list, list, set]:
    """Return (writes, skipped, new genre names). `current` maps content_id to its
    genre now; `existing` maps casefolded genre name to its stored spelling, so
    'techno' reuses 'Techno' rather than creating a near-duplicate."""
    writes, skipped, new = [], [], set()
    for e in entries:
        if e["status"] != "accepted":
            continue
        cid = e["content_id"]
        if cid not in current:
            skipped.append((e, "track is no longer in the library"))
        elif current[cid] != e["current_genre"]:
            skipped.append((e, f"genre changed since the scan (now '{current[cid]}')"))
        else:
            name = existing.get(e["proposed"].casefold(), e["proposed"])
            if name == current[cid]:
                skipped.append((e, "already set"))
                continue
            if e["proposed"].casefold() not in existing:
                new.add(name)
            writes.append({"content_id": cid, "genre": name, "previous": current[cid]})
    return writes, skipped, new


def main() -> int:
    ap = argparse.ArgumentParser(description="Write accepted genres to rekordbox.")
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
    current = {cid: (c.GenreName or "").strip() for cid, c in rows.items()}
    # When spellings collide, the capitalized one wins, so `Techno` beats `techno`.
    names = sorted((g.Name for g in db.query(tables.DjmdGenre) if g.Name),
                   key=lambda n: sum(ch.isupper() for ch in n))
    existing = {name.casefold(): name for name in names}
    writes, skipped, new = plan_writes(entries, current, existing)

    print(f"{len(writes)} track(s) to update, {len(new)} new genre(s), "
          f"{len(skipped)} skipped.")
    for genre, n in Counter(w["genre"] for w in writes).most_common():
        print(f"  {n:5}  {genre}{'  (new)' if genre in new else ''}")
    for e, reason in skipped:
        print(f"  SKIP  {e['artist']} - {e['title']}: {reason}")
    pending = sum(e["status"] == "pending" for e in entries)
    if pending:
        print(f"{pending} track(s) are still pending review and will not be written.")
    if not args.apply:
        print("DRY RUN. Re-run with --apply to write.")
        return 0
    if not writes:
        return 0

    _db_path, backup = backup_database(db)
    try:
        ids = {}
        for name in sorted({w["genre"] for w in writes}):
            found = db.get_genre(Name=name).one_or_none()
            ids[name] = (found or db.add_genre(name=name)).ID
        for w in writes:
            rows[w["content_id"]].GenreID = ids[w["genre"]]
        db.commit()
    except Exception as e:
        db.rollback()
        raise SystemExit(f"Write failed and was rolled back. Backup: {backup}\nError: {e}")

    # Query the column directly: GenreName on a loaded row can stay stale.
    stored = {str(cid): str(gid) for cid, gid in
              db.query(tables.DjmdContent.ID, tables.DjmdContent.GenreID)}
    mismatches = [w for w in writes if stored.get(w["content_id"]) != str(ids[w["genre"]])]
    log_path = Path(args.manifest).with_name("genres_applied_log.json")
    log_path.write_text(json.dumps({
        "applied_at": datetime.now().isoformat(), "db_file_backup": str(backup),
        "writes": writes, "mismatches": mismatches,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Updated {len(writes)} track(s). Backup: {backup}\nAudit log: {log_path}")
    if mismatches:
        print(f"WARNING: {len(mismatches)} track(s) did not verify. Restore from the "
              "backup if needed.")
        return 1
    print("Verified: every genre is reflected in the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
