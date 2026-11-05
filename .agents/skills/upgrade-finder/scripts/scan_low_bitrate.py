#!/usr/bin/env python3
"""Flag low-bitrate lossy tracks across the whole library. Read-only.

Writes a CSV of every lossy track at or below --max-bitrate, with what's attached to
it and any better copy already in the library, so the rest can be shopped for.
rekordbox stores 0 for some files, so those use an estimate from size and length.

Usage:
    python3 scan_low_bitrate.py --report low-bitrate.csv
    python3 scan_low_bitrate.py --report low.csv --max-bitrate 256
    python3 scan_low_bitrate.py --report low.csv --exclude-losers dedupe-manifest.json
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from find_upgrades import find_best_upgrade
from rb_common import (DEFAULT_ARTIST_THRESHOLD, DEFAULT_TITLE_THRESHOLD, build_playlist_index,
                       get_db, playlist_path, track_facts)

MAX_PLAUSIBLE_KBPS = 1500  # above this the stored length is wrong, not the bitrate


def effective_bitrate(bitrate: int, size: int, length: int) -> tuple[int, bool]:
    """Return (kbps, estimated). 0 means unknown."""
    if bitrate:
        return bitrate, False
    if not (size and length):
        return 0, True
    kbps = round(size * 8 / length / 1000)
    return (kbps, True) if kbps <= MAX_PLAUSIBLE_KBPS else (0, True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Flag low-bitrate tracks in the whole library.")
    ap.add_argument("--report", required=True, help="CSV to write.")
    ap.add_argument("--max-bitrate", type=int, default=192)
    ap.add_argument("--exclude-losers", metavar="MANIFEST",
                    help="Skip tracks a playlist-dedupe manifest collapsed away.")
    args = ap.parse_args()

    skip = set()
    if args.exclude_losers:
        for grp in json.loads(Path(args.exclude_losers).read_text(encoding="utf-8")).get("groups", []):
            if grp.get("decision") == "collapse":
                skip |= ({str(m["content_id"]) for m in grp["members"]}
                         - {str(grp["winner_content_id"])})

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    db = get_db()
    from pyrekordbox.db6 import tables

    index = build_playlist_index(db)
    playlists = defaultdict(list)
    for r in db.get_playlist_songs().filter(tables.DjmdSongPlaylist.rb_local_deleted == 0):
        path = playlist_path(index, str(r.PlaylistID))
        if not path.startswith("Claude Backups"):
            playlists[str(r.ContentID)].append(path)
    cues = Counter(str(q.ContentID) for q in
                   db.query(tables.DjmdCue).filter(tables.DjmdCue.rb_local_deleted == 0))

    library, plays = [], {}
    for c in db.get_content():
        t = track_facts(c)
        t["bitrate"], t["estimated"] = effective_bitrate(t["bitrate"], t["file_size"], t["length"])
        plays[t["content_id"]] = int(c.DJPlayCount or 0)
        library.append(t)
    db.close()

    usable = [t for t in library if os.path.exists(t["path"]) and t["content_id"] not in skip]
    low = [t for t in library if not t["lossless"] and t["content_id"] not in skip
           and 0 < t["bitrate"] <= args.max_bitrate]
    unknown = sum(not t["lossless"] and not t["bitrate"] for t in library)

    rows = []
    for t in low:
        best, _, _, tier = find_best_upgrade(
            t, usable, DEFAULT_TITLE_THRESHOLD, DEFAULT_ARTIST_THRESHOLD)
        status = "already own same recording" if tier in ("exact", "looks_same") else "need to find"
        rows.append([status, t["artist"], t["title"], t["ext"], t["bitrate"],
                     "yes" if t["estimated"] else "", len(playlists[t["content_id"]]),
                     cues[t["content_id"]], plays[t["content_id"]],
                     "yes" if os.path.exists(t["path"]) else "no",
                     tier or "", best["path"] if best else "",
                     f"{best['ext']} {best['bitrate']}k" if best else "",
                     "; ".join(sorted(playlists[t["content_id"]])), t["path"], t["content_id"]])
    rows.sort(key=lambda r: (r[0] != "need to find", -r[6], -r[7], -r[8], r[1].casefold()))
    with open(args.report, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Status", "Artist", "Title", "Format", "Bitrate (kbps)", "Estimated",
                         "Playlist count", "Cues", "Plays", "File found", "Better copy match",
                         "Better copy path", "Better copy quality", "Playlists", "Path", "Track ID"])
        writer.writerows(rows)

    print(f"{len(rows)} lossy track(s) at or below {args.max_bitrate} kbps: "
          f"{dict(Counter(r[0] for r in rows))}")
    print(f"By format: {dict(Counter(r[3] for r in rows))}; estimated: "
          f"{sum(r[5] == 'yes' for r in rows)}; unknown bitrate skipped: {unknown}")
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
