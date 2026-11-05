#!/usr/bin/env python3
"""Point a kept copy with a missing file at its duplicate's working file.

rekordbox allows one collection entry per file, so the duplicate has to go first.
Only clear-cut pairs from a dedupe manifest are merged: the kept copy's file is
missing, there is exactly one working duplicate, sizes match, and that duplicate
has no cues and sits in no real playlist. Other cases are listed for review.

Mirrors rekordbox's own removal, except play history and Claude Backups snapshot
rows move to the kept copy, and the duplicate's analysis files stay on disk.
Dry run unless --apply.

--identical takes the pairs written by find_identical.py: two entries for one
byte-identical file, both present on disk. The kept entry keeps its own path and
analysis. It takes over the duplicate's playlist slots, history and plays, and any
metadata it lacks. The duplicate's audio file stays on disk.

Usage:
    python3 merge_duplicates.py manifest.json
    python3 merge_duplicates.py manifest.json --limit 3 --apply
    python3 merge_duplicates.py manifest.json --apply
    python3 merge_duplicates.py --pairs fixes.json
    python3 merge_duplicates.py --identical pairs.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from apply_core import (backup_database, load_file_state, rekordbox_running,
                        renumber_after_removals, tombstone_remove)
from rb_common import get_db, normalize

FILL_FIELDS = ("AlbumID", "GenreID", "ReleaseYear", "LabelID", "RemixerID", "KeyID",
               "ColorID", "Rating", "Commnt")
GENERIC_ARTISTS = {"", "various", "various artists", "va", "v a", "unknown", "unknown artist"}


def plan_merges(manifest: dict, paths: dict, sizes: dict, cues: dict, memberships: dict,
                exists=os.path.exists) -> tuple[list, list]:
    """Return (merges, review). A manifest group is only considered when its kept
    copy is still in the library and its file is missing."""
    merges, review = [], []
    for grp in manifest.get("groups", []):
        if grp.get("decision") != "collapse":
            continue
        kept = str(grp["winner_content_id"])
        if kept not in paths or exists(paths[kept]):
            continue
        working = [str(m["content_id"]) for m in grp["members"]
                   if str(m["content_id"]) != kept and str(m["content_id"]) in paths
                   and exists(paths[str(m["content_id"])])]
        item = {"kept": kept, "kept_path": paths[kept], "duplicates": working}
        if not working:
            review.append({**item, "reason": "no working duplicate"})
        elif len(working) > 1:
            review.append({**item, "reason": "several working duplicates"})
        elif sizes.get(kept) != sizes.get(working[0]):
            review.append({**item, "reason": "file sizes differ"})
        elif cues.get(working[0]):
            review.append({**item, "reason": "duplicate has cues"})
        elif any(not snapshot for _, snapshot in memberships.get(working[0], [])):
            review.append({**item, "reason": "duplicate is in a playlist"})
        else:
            merges.append({"kept": kept, "duplicate": working[0],
                           "old_path": paths[kept], "new_path": paths[working[0]]})
    return merges, review


def plan_pairs(pairs: list, paths: dict, sizes: dict, cues: dict, memberships: dict,
               exists=os.path.exists, disk_size=os.path.getsize) -> tuple[list, list]:
    """Check a hand-picked list. Each item names `kept` plus either `duplicate` (the
    entry that owns the file) or `new_path` (an unclaimed file). Unlike plan_merges,
    the duplicate may hold playlist slots: they move to the kept entry, unless both
    are in the same playlist."""
    owned = {p: cid for cid, p in paths.items()}
    merges, review = [], []
    for pair in pairs:
        kept, dup = str(pair["kept"]), pair.get("duplicate")
        dup = str(dup) if dup else None
        new_path = paths.get(dup, "") if dup else pair.get("new_path", "")
        item = {"kept": kept, "duplicate": dup, "old_path": paths.get(kept, ""),
                "new_path": new_path}
        real = {label for label, snapshot in memberships.get(dup, []) if not snapshot}
        kept_real = {label for label, snapshot in memberships.get(kept, []) if not snapshot}
        if kept not in paths or (dup and dup not in paths):
            reason = "entry is no longer in the library"
        elif exists(paths[kept]):
            reason = "kept entry already has a file"
        elif not exists(new_path):
            reason = "target file is not on disk"
        elif dup and sizes.get(kept) != sizes.get(dup):
            reason = "file sizes differ"
        elif not dup and new_path in owned:
            reason = "another entry already uses the file"
        elif not dup and sizes.get(kept) != disk_size(new_path):
            reason = "file sizes differ"
        elif dup and cues.get(dup):
            reason = "duplicate has cues"
        elif real & kept_real:
            reason = "both entries are in the same playlist"
        else:
            merges.append({**item, "moved_playlists": sorted(real)})
            continue
        review.append({**item, "reason": reason})
    return merges, review


def plan_identical(pairs: list, paths: dict, cues: dict, exists=os.path.exists,
                   disk_size=os.path.getsize) -> tuple[list, list]:
    """Check pairs from find_identical.py against the library as it is now."""
    merges, review = [], []
    for pair in pairs:
        kept, dup = str(pair["kept"]), str(pair["duplicate"])
        item = {"kept": kept, "duplicate": dup, "old_path": paths.get(dup, ""),
                "new_path": paths.get(kept, ""), "identical": True}
        if kept not in paths or dup not in paths:
            reason = "entry is no longer in the library"
        elif not exists(paths[kept]) or not exists(paths[dup]):
            reason = "a file is missing"
        elif disk_size(paths[kept]) != disk_size(paths[dup]):
            reason = "file sizes differ"
        elif cues.get(dup):
            reason = "duplicate has cues"
        else:
            merges.append(item)
            continue
        review.append({**item, "reason": reason})
    return merges, review


def metadata_fills(kept: dict, dup: dict) -> dict:
    """Fields to copy from the duplicate: anything blank on the kept entry, plus the
    artist when the kept entry only has a generic one like Various Artists."""
    fills = {f: dup[f] for f in FILL_FIELDS
             if kept.get(f) in (None, "", 0, "0") and dup.get(f) not in (None, "", 0, "0")}
    if (normalize(kept["artist"]) in GENERIC_ARTISTS
            and normalize(dup["artist"]) not in GENERIC_ARTISTS):
        fills["ArtistID"] = dup["ArtistID"]
    return fills


def entry_facts(row) -> dict:
    return {**{f: getattr(row, f) for f in (*FILL_FIELDS, "ArtistID")},
            "artist": row.ArtistName or ""}


def absorb_entry(db, tables, kept, dup, now: datetime) -> None:
    """Hand the duplicate's plays, playlist slots and history to the kept entry, then
    remove it. Where both are in a playlist, the kept entry's slot stays."""
    kept_id, dup_id = str(kept.ID), str(dup.ID)
    kept.DJPlayCount = int(kept.DJPlayCount or 0) + int(dup.DJPlayCount or 0)

    songs = tables.DjmdSongPlaylist
    live = songs.rb_local_deleted == 0
    shared = {str(r.PlaylistID) for r in
              db.query(songs).filter(songs.ContentID == kept_id, live)}
    for row in db.query(songs).filter(songs.ContentID == dup_id, live).all():
        pid = str(row.PlaylistID)
        if pid in shared:
            track_no = tombstone_remove(db, tables, row.ID, now)
            db.flush()
            renumber_after_removals(db, tables, pid, [track_no], now)
        else:
            row.ContentID = kept_id
            row.updated_at = now
    for row in db.query(tables.DjmdSongHistory).filter(tables.DjmdSongHistory.ContentID == dup_id):
        row.ContentID = kept_id
        row.updated_at = now
    for table in (tables.ContentFile, tables.DjmdMixerParam):
        for row in db.query(table).filter(table.ContentID == dup_id).all():
            db.delete(row)
    db.delete(dup)
    db.flush()


def merge_pair(db, tables, kept_id: str, dup_id: str | None, now: datetime,
               new_path: str = "") -> None:
    kept = db.get_content(ID=kept_id)
    if not dup_id:
        kept.FolderPath = new_path
        kept.FileNameL = os.path.basename(new_path)
        kept.updated_at = now
        return
    dup = db.get_content(ID=dup_id)
    new_path, new_name = dup.FolderPath, dup.FileNameL
    absorb_entry(db, tables, kept, dup, now)
    kept.FolderPath = new_path
    kept.FileNameL = new_name
    kept.updated_at = now


def merge_identical(db, tables, kept_id: str, dup_id: str, now: datetime) -> None:
    kept, dup = db.get_content(ID=kept_id), db.get_content(ID=dup_id)
    for field, value in metadata_fills(entry_facts(kept), entry_facts(dup)).items():
        setattr(kept, field, value)
    absorb_entry(db, tables, kept, dup, now)
    kept.updated_at = now


def identical_differences(db, merges: list) -> Counter:
    """Count pairs whose entries disagree on something that won't carry over."""
    rows = {str(c.ID): c for c in db.get_content()}
    found = Counter()
    for m in merges:
        kept, dup = rows[m["kept"]], rows[m["duplicate"]]
        fills = metadata_fills(entry_facts(kept), entry_facts(dup))
        found["metadata filled in from the duplicate"] += bool(fills)
        found["artist replaced (kept entry was generic)"] += "ArtistID" in fills
        found["genre filled in"] += "GenreID" in fills
        for label, a, b in (("artist", kept.ArtistName, dup.ArtistName),
                            ("title", kept.Title, dup.Title),
                            ("genre", kept.GenreName, dup.GenreName)):
            if normalize(a) and normalize(b) and normalize(a) != normalize(b):
                if not (label == "artist" and "ArtistID" in fills):
                    found[f"{label} differs, kept entry's stays"] += 1
        if abs(int(kept.BPM or 0) - int(dup.BPM or 0)) > 50:
            found["BPM differs, kept entry's stays"] += 1
    return found


def playlist_contents(db, tables, renamed: dict) -> dict:
    """Tracks in each playlist as playlist_id -> set of ids, read through `renamed`."""
    songs = tables.DjmdSongPlaylist
    contents: dict[str, set] = {}
    for pid, cid in db.query(songs.PlaylistID, songs.ContentID).filter(songs.rb_local_deleted == 0):
        contents.setdefault(str(pid), set()).add(renamed.get(str(cid), str(cid)))
    return contents


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge kept copies onto working duplicates.")
    ap.add_argument("manifest", nargs="?", help="An applied playlist-dedupe manifest.")
    ap.add_argument("--pairs", help="JSON list of hand-picked fixes, instead of a manifest.")
    ap.add_argument("--identical", help="JSON pairs from find_identical.py.")
    ap.add_argument("--limit", type=int, help="Only merge this many pairs, as a trial.")
    ap.add_argument("--report", default="merge_review.json",
                    help="Where to write the pairs left for review.")
    ap.add_argument("--apply", action="store_true", help="Write. Without it, dry run only.")
    args = ap.parse_args()
    if sum(map(bool, (args.manifest, args.pairs, args.identical))) != 1:
        ap.error("Pass one of: a manifest, --pairs or --identical.")

    if args.apply and rekordbox_running():
        raise SystemExit("rekordbox appears to be RUNNING. Close it completely first.")
    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)

    source = json.loads(Path(args.manifest or args.pairs or args.identical).read_text(encoding="utf-8"))
    db = get_db()
    from pyrekordbox.db6 import tables

    paths, memberships = load_file_state(db, tables)
    sizes = {str(c.ID): c.FileSize for c in db.get_content()}
    cues = Counter(str(q.ContentID) for q in
                   db.query(tables.DjmdCue).filter(tables.DjmdCue.rb_local_deleted == 0))
    if args.identical:
        cues.update(str(q.ContentID) for q in db.query(tables.ContentCue))
        merges, review = plan_identical(source, paths, cues)
    else:
        plan = plan_pairs if args.pairs else plan_merges
        merges, review = plan(source, paths, sizes, cues, memberships)
    Path(args.report).write_text(json.dumps(review, indent=2, ensure_ascii=False),
                                 encoding="utf-8")

    print(f"{len(merges)} pair(s) can be merged, {len(review)} left for review "
          f"({args.report}).")
    for reason, n in Counter(r["reason"] for r in review).most_common():
        print(f"  {n:4}  {reason}")
    merges = merges[:args.limit] if args.limit else merges
    if args.identical:
        slots = sum(len(memberships.get(m["duplicate"], [])) for m in merges)
        print(f"  Playlist slots on the duplicates: {slots}")
        for label, n in identical_differences(db, merges).most_common():
            print(f"  {n:4}  {label}")
    for m in [] if args.identical else merges:
        moved = f", playlists moving over: {len(m['moved_playlists'])}" if m.get("moved_playlists") else ""
        print(f"  {os.path.basename(m['new_path'])}  (cues on kept: {cues.get(m['kept'], 0)}{moved})")
    if not args.apply:
        print(f"DRY RUN. Re-run with --apply to merge {len(merges)} pair(s).")
        return 0
    if not merges:
        return 0

    renamed = {m["duplicate"]: m["kept"] for m in merges}
    expected = playlist_contents(db, tables, renamed)
    db_path, backup = backup_database(db)
    now = datetime.now()
    try:
        for m in merges:
            if m.get("identical"):
                merge_identical(db, tables, m["kept"], m["duplicate"], now)
            else:
                merge_pair(db, tables, m["kept"], m["duplicate"], now, m["new_path"])
        db.commit()
    except Exception as e:
        db.rollback()
        raise SystemExit(f"Write failed and was rolled back. Backup: {backup}\nError: {e}")

    stored = {str(c): p for c, p in db.query(tables.DjmdContent.ID, tables.DjmdContent.FolderPath)}
    problems = [m for m in merges
                if stored.get(m["kept"]) != m["new_path"] or m["duplicate"] in stored]
    if playlist_contents(db, tables, {}) != expected:
        problems.append({"kept": "", "duplicate": "", "reason": "a playlist's tracks changed"})
    log_path = db_path.parent / f"merge-log-{now.strftime('%Y-%m-%d_%H%M%S')}.json"
    log_path.write_text(json.dumps({
        "applied_at": now.isoformat(), "db_file_backup": str(backup),
        "merges": merges, "problems": problems,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Merged {len(merges)} pair(s). Backup: {backup}\nLog: {log_path}")
    if problems:
        print(f"WARNING: {len(problems)} pair(s) did not verify. Restore from the backup "
              "if needed.")
        return 1
    print("Verified: every kept copy has its new path and every duplicate is gone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
