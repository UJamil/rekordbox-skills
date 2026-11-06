#!/usr/bin/env python3
"""Find duplicate tracks and spelling problems in the library. Read-only.

Reports three things: tracks that look like the same recording, artist, album and genre
names spelled more than one way, and titles with junk in them, like underscores,
all capitals, YouTube ids or leftover track numbers.

Usage:
    python3 find_name_issues.py --out issues.json --csv issues.csv
    python3 find_name_issues.py --out issues.json --skip leaving.json
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from rb_common import get_db, lengths_very_close, normalize, similarity, split_title

NEAR = 0.9  # two names this close are probably one name
MIN_NEAR_LENGTH = 6  # short names like "Sub" and "Sun" are different people
JUNK = (("YouTube id", re.compile(r"\[[A-Za-z0-9_-]{11}\]")),
        ("underscores", re.compile(r"\w_\w")),
        ("track number", re.compile(r"^(\d{1,3}|[A-Da-d]\d)\s*[-.]\s+\S")),
        ("copy number", re.compile(r"(_\d| \(\d\))$")),
        ("file extension", re.compile(r"\.(mp3|flac|wav|aiff?|m4a)$", re.I)),
        ("website", re.compile(r"https?:|www\.|\.(com|net|org)\b", re.I)),
        ("stray bracket", re.compile(r"\( | \)|\[ | \]")))


def spelling_key(name: str) -> str:
    """One key for names that differ only in case, punctuation, spaces, `&`/`and` or `The`."""
    text = re.sub(r"\s*(&|\+)\s*", " and ", name.casefold())
    text = re.sub(r"^the\s+|,\s*the$", "", text.strip())
    return re.sub(r"[^\w]", "", text)


def spelling_groups(counts: Counter) -> list:
    """Groups of names that are probably one name, most used first."""
    groups = defaultdict(set)
    for name in counts:
        groups[spelling_key(name)].add(name)
    keys = sorted(k for k in groups if k)
    by_start = defaultdict(list)
    for k in keys:
        by_start[k[:2]].append(k)
    merged = {k: k for k in keys}

    def root(k):
        while merged[k] != k:
            k = merged[k]
        return k
    for bucket in by_start.values():
        for i, a in enumerate(bucket):
            for b in bucket[i + 1:]:
                if min(len(a), len(b)) >= MIN_NEAR_LENGTH and similarity(a, b) >= NEAR \
                        and re.sub(r"\D", "", a) == re.sub(r"\D", "", b):
                    merged[root(b)] = root(a)
    out = defaultdict(set)
    for k in keys:
        out[root(k)] |= groups[k]
    return [sorted(v, key=lambda n: (-counts[n], n)) for v in out.values() if len(v) > 1]


def title_problems(title: str) -> list:
    found = [label for label, pattern in JUNK if pattern.search(title or "")]
    letters = re.sub(r"[^A-Za-z]", "", title or "")
    if len(letters) > 5 and letters.isupper():
        found.append("all capitals")
    elif len(letters) > 5 and letters.islower():
        found.append("all lowercase")
    return found


def duplicate_groups(tracks: list) -> list:
    """Same artist, base title and version tags, within a couple of seconds."""
    grouped = defaultdict(list)
    for t in tracks:
        base, markers = split_title(t["title"])
        if base and t["artist"]:
            grouped[(spelling_key(t["artist"]), normalize(base), markers)].append(t)
    groups = []
    for members in grouped.values():
        left = list(members)
        while left:
            first = left.pop(0)
            same = [first] + [t for t in left if lengths_very_close(first["length"], t["length"])]
            left = [t for t in left if t not in same]
            if len(same) > 1:
                groups.append(same)
    return groups


def main() -> int:
    ap = argparse.ArgumentParser(description="Find duplicates and spelling problems.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv", help="Also write a table for review.")
    ap.add_argument("--skip", help="JSON list of content ids to leave out.")
    args = ap.parse_args()

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    skip = set(json.loads(Path(args.skip).read_text())) if args.skip else set()
    db = get_db()
    tracks = [{"content_id": str(c.ID), "artist": (c.ArtistName or "").strip(), "title": c.Title or "",
               "album": (c.AlbumName or "").strip(), "genre": (c.GenreName or "").strip(),
               "length": int(c.Length or 0), "bitrate": int(c.BitRate or 0), "path": c.FolderPath or ""}
              for c in db.get_content() if str(c.ID) not in skip]
    db.close()

    dupes = duplicate_groups(tracks)
    names = {field: spelling_groups(Counter(t[field] for t in tracks if t[field]))
             for field in ("artist", "album", "genre")}
    titles = [{**t, "problems": title_problems(t["title"])} for t in tracks if title_problems(t["title"])]
    Path(args.out).write_text(json.dumps({"tracks": len(tracks), "duplicates": dupes, "names": names, "titles": titles},
                                         indent=2, ensure_ascii=False), encoding="utf-8")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Check", "Group", "Name or track", "Detail", "Path"])
            for n, group in enumerate(dupes, 1):
                for t in group:
                    w.writerow(["Duplicate", n, f"{t['artist']} - {t['title']}", f"{t['length']}s {t['bitrate']}k", t["path"]])
            for field, groups in names.items():
                for n, group in enumerate(groups, 1):
                    for name in group:
                        w.writerow([f"{field.title()} spelling", n, name, "", ""])
            for t in titles:
                w.writerow(["Title", "", f"{t['artist']} - {t['title']}", ", ".join(t["problems"]), t["path"]])
    print(f"{len(tracks)} track(s) checked.")
    print(f"Duplicate groups: {len(dupes)} ({sum(len(g) - 1 for g in dupes)} extra copies)")
    print("Spelling groups: " + ", ".join(f"{k} {len(v)}" for k, v in names.items()))
    print(f"Titles with problems: {len(titles)} {dict(Counter(p for t in titles for p in t['problems']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
