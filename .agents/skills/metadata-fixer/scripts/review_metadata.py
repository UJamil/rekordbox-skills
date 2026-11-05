#!/usr/bin/env python3
"""Show a metadata manifest and record decisions. Edits only the manifest.

Usage:
    python3 review_metadata.py metadata.json
    python3 review_metadata.py metadata.json --list filename
    python3 review_metadata.py metadata.json --accept-high
    python3 review_metadata.py metadata.json --accept ID [ID ...]
    python3 review_metadata.py metadata.json --reject ID [ID ...]
    python3 review_metadata.py metadata.json --set ID "Artist" "Title"
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Review a metadata manifest.")
    ap.add_argument("manifest")
    ap.add_argument("--list", choices=["high", "medium", "filename", "none"])
    ap.add_argument("--accept-high", action="store_true")
    ap.add_argument("--accept", nargs="+", metavar="ID")
    ap.add_argument("--reject", nargs="+", metavar="ID")
    ap.add_argument("--set", nargs=3, metavar=("ID", "ARTIST", "TITLE"))
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
            if e["confidence"] == "high" and e["status"] == "pending":
                e["status"] = "accepted"
                changed += 1
    for cid in args.accept or []:
        entry(cid)["status"] = "accepted"
        changed += 1
    for cid in args.reject or []:
        entry(cid)["status"] = "rejected"
        changed += 1
    if args.set:
        e = entry(args.set[0])
        e["proposed"]["artist"], e["proposed"]["title"] = args.set[1], args.set[2]
        e["status"] = "accepted"
        changed += 1
    if changed:
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Updated {changed} track(s).")

    if args.list:
        for e in entries:
            if e["confidence"] == args.list:
                p = e["proposed"]
                print(f"{e['content_id']} [{e['status']}] {e['current']['title']!r}")
                print(f"    -> {p['artist']} - {p['title']} | {p['album']} {p['year'] or ''} ({e['source']})")
    else:
        print("By confidence:", dict(Counter(e["confidence"] for e in entries)))
        print("By status:", dict(Counter(e["status"] for e in entries)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
