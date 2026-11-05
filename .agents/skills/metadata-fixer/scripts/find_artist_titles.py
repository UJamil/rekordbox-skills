#!/usr/bin/env python3
"""Find titles with an artist left in them, as 'Artist - Track'. Read-only.

The artist field isn't always the real artist: a compilation can carry its label or
series name there. List those names in --labels, one per line, and matching tracks
get the artist from the title. Lines match the start of the artist field.

Writes a manifest for apply_metadata.py. Fixes that follow a rule start as accepted,
and anything uncertain starts as pending.

Usage:
    python3 find_artist_titles.py --labels labels.txt --out titles.json --csv titles.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from rb_common import get_db, normalize

GENERIC_ARTISTS = {"", "various", "various artists", "va", "v a", "unknown", "unknown artist"}
DASH = r"\s+[-–—]\s+"
POSITION = r"^\s*(?:[A-Da-d]\d{1,2}[.\s-]+|\d{1,3}[_.]\s*)"
ACTIONS = {"remove": "Remove artist from title", "move": "Move artist out of title",
           "check": "Check by hand"}


def plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize(text)).strip()


def propose(artist: str, title: str, labels: list) -> tuple | None:
    """Return (kind, new artist, new title), or None if the title looks fine."""
    parts = re.split(DASH, re.sub(POSITION, "", title), maxsplit=1)
    if len(parts) != 2:
        return None
    first, second = (re.sub(r"\s+", " ", p).strip() for p in parts)
    name = plain(artist)
    if name and plain(second) == name:
        return "check", artist, first
    if name and plain(first) == name:
        return "remove", artist, second
    if any(name.startswith(label) for label in labels):
        return "move", first, second
    if name in GENERIC_ARTISTS or re.search(DASH, artist) or (name and name in plain(second)):
        return "check", first, second
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Find artists left in track titles.")
    ap.add_argument("--labels", help="Text file of label or series names, one per line.")
    ap.add_argument("--out", default="artist_titles.json")
    ap.add_argument("--csv", help="Also write a table for review.")
    args = ap.parse_args()

    labels = []
    if args.labels:
        lines = Path(args.labels).read_text(encoding="utf-8").splitlines()
        labels = [plain(line) for line in lines if line.strip()]

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    db = get_db()
    entries = []
    for c in db.get_content():
        artist, title = (c.ArtistName or "").strip(), (c.Title or "").strip()
        found = propose(artist, title, labels)
        if found:
            kind, new_artist, new_title = found
            entries.append({
                "content_id": str(c.ID), "action": ACTIONS[kind],
                "status": "pending" if kind == "check" else "accepted", "replace_artist": True,
                "current": {"artist": artist, "title": title},
                "proposed": {"artist": new_artist, "title": new_title, "album": "", "year": ""}})
    entries.sort(key=lambda e: (e["action"], e["current"]["artist"].lower(), e["current"]["title"]))
    Path(args.out).write_text(json.dumps({"entries": entries}, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    for action, n in Counter(e["action"] for e in entries).most_common():
        print(f"{n:4}  {action}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Action", "Current artist", "Current title", "New artist", "New title",
                        "Content ID"])
            for e in entries:
                w.writerow([e["action"], e["current"]["artist"], e["current"]["title"],
                            e["proposed"]["artist"], e["proposed"]["title"], e["content_id"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
