#!/usr/bin/env python3
"""List library entries that point at byte-identical files. Read-only.

Candidates share a file size and are confirmed with a full hash. In each group the
entry with cues stays, then the most played and most used, because cues and analysis
can't move between entries. Everything else moves over in merge_duplicates.py
--identical.

Usage:
    python3 find_identical.py --out pairs.json --csv identical.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from apply_core import load_file_state
from merge_duplicates import GENERIC_ARTISTS
from rb_common import get_db, normalize


def keep_rank(entry: dict) -> tuple:
    """Higher is better. The trailing id keeps the choice the same on every run."""
    return (entry["cues"], entry["plays"], entry["slots"],
            normalize(entry["artist"]) not in GENERIC_ARTISTS,
            len(os.path.basename(entry["path"])), -int(entry["id"]))


def pairs_from_groups(groups: list) -> list:
    pairs = []
    for entries in groups:
        ranked = sorted(entries, key=keep_rank, reverse=True)
        pairs += [{"kept": ranked[0]["id"], "duplicate": e["id"]} for e in ranked[1:]]
    return pairs


def file_hash(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def identical_groups(entries: list) -> list:
    by_size = defaultdict(list)
    for e in entries:
        by_size[e["size"]].append(e)
    groups = []
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        by_hash = defaultdict(list)
        for e in same_size:
            try:
                by_hash[file_hash(e["path"])].append(e)
            except OSError as err:
                print(f"Could not read {e['path']}: {err}")
        groups += [g for g in by_hash.values() if len(g) > 1]
    return groups


def main() -> int:
    ap = argparse.ArgumentParser(description="Find entries for byte-identical files.")
    ap.add_argument("--out", default="identical_pairs.json")
    ap.add_argument("--csv", help="Also write a table for review.")
    args = ap.parse_args()

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    db = get_db()
    from pyrekordbox.db6 import tables

    _, memberships = load_file_state(db, tables)
    cues = Counter(str(q.ContentID) for q in
                   db.query(tables.DjmdCue).filter(tables.DjmdCue.rb_local_deleted == 0))
    cues.update(str(q.ContentID) for q in db.query(tables.ContentCue))
    entries = []
    for c in db.get_content():
        path = c.FolderPath or ""
        if os.path.exists(path):
            entries.append({"id": str(c.ID), "artist": c.ArtistName or "", "title": c.Title or "",
                            "path": path, "size": os.path.getsize(path), "cues": cues[str(c.ID)],
                            "plays": int(c.DJPlayCount or 0),
                            "slots": len(memberships.get(str(c.ID), []))})

    groups = identical_groups(entries)
    pairs = pairs_from_groups(groups)
    Path(args.out).write_text(json.dumps(pairs, indent=2), encoding="utf-8")
    same = sum(len({os.path.dirname(e["path"]) for e in g}) == 1 for g in groups)
    print(f"{len(groups)} group(s), {len(pairs)} entries to merge. "
          f"{same} group(s) share a folder. Pairs: {args.out}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Group", "Action", "Artist", "Title", "Cues", "Playlist slots",
                        "Plays", "Path", "Content ID"])
            for n, g in enumerate(groups, 1):
                for i, e in enumerate(sorted(g, key=keep_rank, reverse=True)):
                    w.writerow([n, "Remove entry" if i else "Keep", e["artist"], e["title"],
                                e["cues"], e["slots"], e["plays"], e["path"], e["id"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
