#!/usr/bin/env python3
"""Find byte-identical audio files on a drive and compare the folders they sit in.

Read-only. Candidates share a size and are confirmed with a full hash. Each set is
matched to the rekordbox entry that uses it, and each pair of folders gets a diff:
files in both, and files only on one side. Same-folder sets are listed by folder.

Usage:
    python3 scan_drive.py /Volumes/<YourDrive>/Music --out drive_duplicates.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from apply_core import load_file_state, path_key
from rb_common import get_db

AUDIO = {".mp3", ".wav", ".aiff", ".aif", ".flac", ".m4a", ".aac", ".ogg", ".alac"}


def audio_files(root: str) -> list:
    found = []
    for folder, subfolders, names in os.walk(root):
        subfolders[:] = [s for s in subfolders if not s.startswith(".")]
        for name in names:
            if not name.startswith("._") and os.path.splitext(name)[1].lower() in AUDIO:
                path = os.path.join(folder, name)
                found.append((path, os.path.getsize(path)))
    return found


def file_hash(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def identical_sets(files: list) -> list:
    by_size = defaultdict(list)
    for path, size in files:
        by_size[size].append(path)
    sets = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_hash = defaultdict(list)
        for path in paths:
            try:
                by_hash[file_hash(path)].append(path)
            except OSError as err:
                print(f"Could not read {path}: {err}")
        sets += [{"hash": h, "size": size, "paths": sorted(ps)}
                 for h, ps in by_hash.items() if len(ps) > 1]
    return sets


def compare_folders(sets: list, listing: dict) -> list:
    """One record per folder pair. `listing` maps a folder to its audio file paths.
    A set of three copies appears in each pair it touches."""
    shared = defaultdict(list)
    for n, s in enumerate(sets):
        by_folder = defaultdict(list)
        for path in s["paths"]:
            by_folder[os.path.dirname(path)].append(path)
        for folder, paths in by_folder.items():
            if len(paths) > 1:
                shared[folder, folder].append(n)
        for a, b in combinations(sorted(by_folder), 2):
            shared[a, b].append(n)

    pairs = []
    for (a, b), members in shared.items():
        matched = {p for n in members for p in sets[n]["paths"]}
        pairs.append({"left": a, "right": b, "sets": members,
                      "only_left": sorted(set(listing[a]) - matched),
                      "only_right": [] if a == b else sorted(set(listing[b]) - matched)})
    pairs.sort(key=lambda p: (p["left"] == p["right"], -len(p["sets"]), p["left"]))
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description="Find identical audio files on a drive.")
    ap.add_argument("root")
    ap.add_argument("--out", default="drive_duplicates.json")
    args = ap.parse_args()

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    db = get_db()
    from pyrekordbox.db6 import tables

    paths, memberships = load_file_state(db, tables)
    cues = Counter(str(q.ContentID) for q in
                   db.query(tables.DjmdCue).filter(tables.DjmdCue.rb_local_deleted == 0))
    cues.update(str(q.ContentID) for q in db.query(tables.ContentCue))
    entry_of = {path_key(p): cid for cid, p in paths.items() if p}

    files = audio_files(args.root)
    listing = defaultdict(list)
    for path, _ in files:
        listing[os.path.dirname(path)].append(path)
    sets = identical_sets(files)
    for s in sets:
        s["entries"] = {}
        for path in s["paths"]:
            cid = entry_of.get(path_key(path))
            if cid:
                s["entries"][path] = {"id": cid, "cues": cues[cid],
                                      "slots": len(memberships.get(cid, []))}
    pairs = compare_folders(sets, listing)

    Path(args.out).write_text(json.dumps({
        "root": args.root, "audio_files": len(files), "sets": sets, "pairs": pairs,
    }, ensure_ascii=False), encoding="utf-8")
    extra = sum(s["size"] * (len(s["paths"]) - 1) for s in sets)
    print(f"{len(files)} audio files. {len(sets)} identical set(s), "
          f"{extra / 1e9:.2f} GB in extra copies. {len(pairs)} folder pair(s).")
    print(f"Entries per set: {Counter(len(s['entries']) for s in sets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
