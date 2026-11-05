#!/usr/bin/env python3
"""Show a genre manifest and record review decisions. Edits only the manifest.

Usage:
    python3 review_genres.py genres.json                    # summary
    python3 review_genres.py genres.json --list medium      # one confidence level
    python3 review_genres.py genres.json --accept-high      # accept all high
    python3 review_genres.py genres.json --accept ID [ID ...]
    python3 review_genres.py genres.json --set ID "Jungle"  # choose the genre
    python3 review_genres.py genres.json --reject ID [ID ...]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def print_summary(entries: list) -> None:
    print(f"Tracks: {len(entries)}")
    print("By confidence:", dict(Counter(e["confidence"] for e in entries)))
    print("By status:", dict(Counter(e["status"] for e in entries)))
    print("By comparison:", dict(Counter(e.get("comparison", "blank") for e in entries)))
    print("Top proposed genres:")
    for genre, n in Counter(e["proposed"] for e in entries if e["proposed"]).most_common(25):
        print(f"  {n:5}  {genre}")


def print_rows(entries: list, level: str) -> None:
    for e in entries:
        if level == "conflict":
            if e.get("comparison") != "conflict":
                continue
        elif e["confidence"] != level:
            continue
        current = f" (now: {e['current_genre']})" if e["current_genre"] else ""
        print(f"{e['content_id']}  [{e['status']}]  {e['artist']} - {e['title']}{current}")
        if e["proposed"]:
            print(f"    -> {e['proposed']}  styles: {', '.join(e.get('styles', [])[:5])}")
            print(f"       {e.get('source')}: {e.get('release')} "
                  f"{e.get('release_year')} ({e.get('evidence')})")
        elif e["note"]:
            print(f"    {e['note']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Review a genre manifest.")
    ap.add_argument("manifest")
    ap.add_argument("--list", choices=["high", "medium", "low", "none", "conflict"])
    ap.add_argument("--accept-high", action="store_true")
    ap.add_argument("--accept", nargs="+", metavar="ID")
    ap.add_argument("--reject", nargs="+", metavar="ID")
    ap.add_argument("--set", nargs=2, metavar=("ID", "GENRE"))
    args = ap.parse_args()

    path = Path(args.manifest)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entries = manifest["entries"]
    by_id = {e["content_id"]: e for e in entries}

    def entry(cid: str) -> dict:
        if cid not in by_id:
            raise SystemExit(f"content_id {cid} is not in this manifest.")
        return by_id[cid]

    changed = 0
    if args.accept_high:
        for e in entries:
            if (e["confidence"] == "high" and e["status"] == "pending"
                    and e.get("comparison") != "conflict"):
                e["status"] = "accepted"
                changed += 1
    for cid in args.accept or []:
        if not entry(cid)["proposed"]:
            raise SystemExit(f"{cid} has no proposed genre. Use --set to choose one.")
        entry(cid)["status"] = "accepted"
        changed += 1
    for cid in args.reject or []:
        entry(cid)["status"] = "rejected"
        changed += 1
    if args.set:
        e = entry(args.set[0])
        e["proposed"], e["status"] = args.set[1].strip(), "accepted"
        changed += 1

    if changed:
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Updated {changed} track(s).")
    if args.list:
        print_rows(entries, args.list)
    else:
        print_summary(entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
