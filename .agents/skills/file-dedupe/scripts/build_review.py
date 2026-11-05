#!/usr/bin/env python3
"""Fill the review page with a scan from scan_drive.py. Read-only.

Usage:
    python3 build_review.py drive_duplicates.json --out drive-diff.html
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "review.html"


def tidiest(paths: list) -> int:
    """Index of the best filename: not cut short, not 'Artist - Album - 01 Title',
    not a numbered copy. Ties go to the longest name."""
    stems = [os.path.splitext(os.path.basename(p))[0] for p in paths]

    def score(i: int) -> tuple:
        stem = stems[i]
        cut = any(o != stem and o.startswith(stem) and not re.fullmatch(r" \d+", o[len(stem):])
                  for o in stems)
        return (not cut, not re.search(r" - .+ - ", stem), not re.search(r" \d$", stem), len(stem))
    return max(range(len(stems)), key=score)


def page_data(scan: dict) -> dict:
    root = scan["root"].rstrip("/") + "/"
    rel = lambda p: p[len(root):] if p.startswith(root) else p
    sets = []
    for s in scan["sets"]:
        used = next(iter(s["entries"]), None)
        entry = s["entries"].get(used, {})
        sets.append({"h": s["hash"][:12], "s": s["size"], "p": [rel(p) for p in s["paths"]],
                     "rb": s["paths"].index(used) if used else -1,
                     "c": entry.get("cues", 0), "n": entry.get("slots", 0),
                     "tidy": tidiest(s["paths"])})
    pairs = []
    for p in scan["pairs"]:
        left, right = rel(p["left"]), rel(p["right"])
        pairs.append({"k": hashlib.sha1(f"{left}|{right}".encode()).hexdigest()[:12],
                      "l": left, "r": right, "sets": [sets[n]["h"] for n in p["sets"]],
                      "ol": [os.path.basename(f) for f in p["only_left"]],
                      "or": [os.path.basename(f) for f in p["only_right"]]})
    scan_id = hashlib.sha1(",".join(s["h"] for s in sets).encode()).hexdigest()[:12]
    return {"scan": scan_id, "sets": sets, "pairs": pairs}


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the drive review page.")
    ap.add_argument("scan")
    ap.add_argument("--out", default="drive-diff.html")
    args = ap.parse_args()

    data = page_data(json.loads(Path(args.scan).read_text(encoding="utf-8")))
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    Path(args.out).write_text(TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/", body),
                              encoding="utf-8")
    print(f"{len(data['pairs'])} comparison(s), {len(data['sets'])} set(s), "
          f"scan {data['scan']}: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
