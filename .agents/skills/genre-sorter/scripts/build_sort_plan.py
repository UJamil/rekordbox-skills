#!/usr/bin/env python3
"""Plan which genre playlist each track belongs in, as an apply_changes.py manifest.

Read-only unless --create-playlists is passed. Rules live in ../rules.json and are
tried in order, so specific playlists come before general ones. A track's rekordbox
genre decides first. Discogs styles are only used when that genre is blank or a
catch-all. Tracks already in any playlist under the folder are left where they are.

Usage:
    python3 build_sort_plan.py --out sort.json --report sort.csv
    python3 build_sort_plan.py --out sort.json --exclude-losers dedupe.json
    python3 build_sort_plan.py --out sort.json --styles genres.json --styles more.json
    python3 build_sort_plan.py --out sort.json --create-playlists
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from apply_core import backup_database, rekordbox_running
from rb_common import build_playlist_index, get_db, playlist_path

RULES = Path(__file__).resolve().parents[1] / "rules.json"


def year_fits(rule: dict, year: int) -> bool:
    low, high = rule.get("years", [None, None])
    return low is None or low <= year <= high


def place(genre: str, styles: list, year: int, config: dict) -> tuple:
    """Return (playlist, 'genre' or 'style'), or (None, None) if nothing fits."""
    for rule in config["rules"]:
        if genre in rule["genres"] and year_fits(rule, year):
            return rule["playlist"], "genre"
    if genre in config["weak_genres"]:
        top = set(styles[:3])
        for rule in config["rules"]:
            if not rule.get("genre_only") and top & set(rule["genres"]) and year_fits(rule, year):
                return rule["playlist"], "style"
    return None, None


def load_styles(paths: list) -> dict:
    styles = {}
    for path in paths:
        for entry in json.loads(Path(path).read_text(encoding="utf-8"))["entries"]:
            if entry.get("styles"):
                styles[entry["content_id"]] = entry["styles"]
    return styles


def collapsed_losers(path: str) -> set:
    losers = set()
    for grp in json.loads(Path(path).read_text(encoding="utf-8")).get("groups", []):
        if grp.get("decision") == "collapse":
            members = {str(m["content_id"]) for m in grp["members"]}
            losers |= members - {str(grp["winner_content_id"])}
    return losers


def create_missing(db, folder_id: str, names: list) -> None:
    if rekordbox_running():
        raise SystemExit("rekordbox appears to be RUNNING. Close it completely first.")
    backup_database(db)
    parent = db.get_playlist(ID=folder_id)
    for name in names:
        db.create_playlist(name, parent=parent)
        print(f"Created playlist: {parent.Name} / {name}")
    db.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description="Plan tracks into genre playlists.")
    ap.add_argument("--out", required=True, help="Manifest to write.")
    ap.add_argument("--report", help="CSV of the plan, for review.")
    ap.add_argument("--rules", default=str(RULES))
    ap.add_argument("--styles", action="append", default=[],
                    help="genre-tagger manifest to read Discogs styles from. Repeatable.")
    ap.add_argument("--exclude-losers", metavar="MANIFEST",
                    help="Skip tracks a playlist-dedupe manifest collapsed away.")
    ap.add_argument("--create-playlists", action="store_true",
                    help="Create playlists the rules name that don't exist yet.")
    args = ap.parse_args()

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    config = json.loads(Path(args.rules).read_text(encoding="utf-8"))
    styles = load_styles(args.styles)
    skip = collapsed_losers(args.exclude_losers) if args.exclude_losers else set()

    db = get_db()
    from pyrekordbox.db6 import tables

    prefix = config["folder"] + " / "
    index = build_playlist_index(db)
    folder_id = next(k for k in index if playlist_path(index, k) == config["folder"])

    def existing() -> dict:
        tree = build_playlist_index(db)
        return {playlist_path(tree, k)[len(prefix):]: str(k) for k in tree
                if playlist_path(tree, k).startswith(prefix)}

    playlists = existing()
    wanted = list(dict.fromkeys(r["playlist"] for r in config["rules"]))
    missing = [name for name in wanted if name not in playlists]
    if missing and args.create_playlists:
        create_missing(db, folder_id, missing)
        playlists = existing()
        missing = []
    if missing:
        print("Rules name playlists that don't exist:", ", ".join(missing))

    sorted_ids = set()
    pids = set(playlists.values())
    for row in db.get_playlist_songs().filter(tables.DjmdSongPlaylist.rb_local_deleted == 0):
        if str(row.PlaylistID) in pids:
            sorted_ids.add(str(row.ContentID))

    groups, rows = [], []
    skipped, unplaced, placed = Counter(), Counter(), Counter()
    for c in db.get_content():
        cid = str(c.ID)
        genre = (c.GenreName or "").strip()
        if cid in skip:
            skipped["dedupe duplicate"] += 1
        elif cid in sorted_ids:
            skipped["already in a genre playlist"] += 1
        elif not os.path.exists(c.FolderPath or ""):
            skipped["no file"] += 1
        else:
            year = int(c.ReleaseYear or 0)
            name, how = place(genre, styles.get(cid, []), year, config)
            if not name or name not in playlists:
                unplaced[genre or "(blank)"] += 1
                continue
            placed[name] += 1
            artist, title = c.ArtistName or "", c.Title or ""
            rows.append([name, how, genre, year, artist, title, cid])
            groups.append({
                "decision": "collapse", "scope": "everywhere", "match_type": "genre_sort",
                "winner_content_id": cid,
                "members": [{"content_id": cid, "artist": artist, "title": title}],
                "actions": [{"type": "add", "content_id": cid, "track_no": None,
                             "playlist_id": playlists[name], "playlist_name": name,
                             "playlist_path": prefix + name}],
            })
    db.close()

    order = sorted(range(len(rows)), key=lambda i: (rows[i][0], rows[i][4].casefold(), rows[i][5]))
    Path(args.out).write_text(json.dumps({
        "created_at": datetime.now().isoformat(),
        "playlist": {"id": "genre-sort", "name": "Genre sort", "path": config["folder"]},
        "groups": [groups[i] for i in order],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.report:
        with open(args.report, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Playlist", "Matched on", "Genre", "Year", "Artist", "Title", "Track ID"])
            writer.writerows(rows[i] for i in order)

    print(f"{len(groups)} track(s) placed. Skipped: {dict(skipped)}")
    for name, n in placed.most_common():
        print(f"  {n:5}  {name}")
    print(f"Unplaced: {sum(unplaced.values())}. Top: {unplaced.most_common(12)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
