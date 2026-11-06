#!/usr/bin/env python3
"""Review proposed artwork. Edits only the manifest.

Usage:
    python3 review_artwork.py art.json
    python3 review_artwork.py art.json --sheet art.html
    python3 review_artwork.py art.json --list medium
    python3 review_artwork.py art.json --accept-high
    python3 review_artwork.py art.json --accept g0001 g0002
    python3 review_artwork.py art.json --reject g0003
"""
from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
from collections import Counter
from pathlib import Path

PAGE = """<!doctype html><meta charset=utf-8><title>Artwork review</title><style>
body{{font:13px -apple-system,sans-serif;margin:16px;background:#111;color:#eee}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}}
figure{{margin:0}}img,.empty{{width:100%;aspect-ratio:1;object-fit:cover;background:#333;display:block}}
figcaption{{padding-top:4px;overflow-wrap:anywhere}}b{{color:#fc6}}small{{color:#aaa}}h2{{margin:24px 0 8px}}
</style><h1>Artwork review</h1>{body}"""


def label(g: dict) -> str:
    return g["album"] or g["tracks"][0]["title"]


def card(g: dict, shared: Path) -> str:
    src = g["image"] or (str(shared) + g["image_path"] if g["image_path"] else "")
    # Browsers won't show the .img files by extension alone in every case, so link a jpg copy.
    if src.endswith(".img"):
        jpg = src[:-4] + ".jpg"
        if not os.path.exists(jpg):
            subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "300", src, "--out", jpg], capture_output=True)
        src = jpg
    img = f'<img loading=lazy src="file://{html.escape(src)}">' if src else '<div class=empty></div>'
    return (f"<figure>{img}<figcaption><b>{g['id']}</b> {html.escape(label(g))}<br>"
            f"{html.escape(g['artist'])}<br><small>{html.escape(g['source'])}, {len(g['tracks'])} track(s)"
            f"{', ' + html.escape(g['release']) if g['release'] else ''}</small></figcaption></figure>")


def main() -> int:
    ap = argparse.ArgumentParser(description="Review proposed artwork.")
    ap.add_argument("manifest")
    ap.add_argument("--sheet", help="Write a contact sheet to this HTML file.")
    ap.add_argument("--share", default="", help="rekordbox's share folder, to show same-album art.")
    ap.add_argument("--list", choices=["high", "medium", "none"])
    ap.add_argument("--accept-high", action="store_true")
    ap.add_argument("--accept", nargs="+", metavar="ID")
    ap.add_argument("--reject", nargs="+", metavar="ID")
    args = ap.parse_args()

    path = Path(args.manifest)
    data = json.loads(path.read_text(encoding="utf-8"))
    groups = data["groups"]
    by_id = {g["id"]: g for g in groups}
    changed = 0
    for wanted, status in ((args.accept, "accepted"), (args.reject, "rejected")):
        for gid in wanted or []:
            if gid not in by_id:
                raise SystemExit(f"No group {gid}.")
            if by_id[gid]["status"] == "no_match":
                raise SystemExit(f"{gid} has no image to {status[:-2]}.")
            by_id[gid]["status"] = status
            changed += 1
    if args.accept_high:
        for g in groups:
            if g["confidence"] == "high" and g["status"] == "pending":
                g["status"] = "accepted"
                changed += 1
    if changed:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Updated {changed} group(s).")

    if args.sheet:
        parts = []
        for level, title in (("medium", "Check these"), ("high", "Strong matches")):
            found = [g for g in groups if g["confidence"] == level]
            parts.append(f"<h2>{title} ({len(found)})</h2><main>"
                         + "".join(card(g, Path(args.share)) for g in found) + "</main>")
        Path(args.sheet).write_text(PAGE.format(body="".join(parts)), encoding="utf-8")
        print(f"Wrote {args.sheet}")
    if args.list:
        for g in groups:
            if g["confidence"] == args.list:
                print(f"{g['id']}  [{g['status']}]  {g['artist']} - {label(g)}  ({len(g['tracks'])} track(s))")
                print(f"    {g['source'] or 'nothing found'}  {g['release']}  {g['note']}".rstrip())
    tracks = Counter()
    for g in groups:
        tracks[g["confidence"]] += len(g["tracks"])
    print(f"Groups: {len(groups)}, tracks: {sum(tracks.values())}")
    print(f"Tracks by confidence: {dict(tracks)}")
    print(f"Groups by status: {dict(Counter(g['status'] for g in groups))}")
    print(f"Groups by source: {dict(Counter(g['source'] or 'none' for g in groups))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
