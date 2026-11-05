#!/usr/bin/env python3
"""Find tracks with no artist and propose metadata. Read-only.

A blank artist usually means a file imported with no tags, so rekordbox used the
filename as the title ("slipmatt - breaking free"). This parses the title and folder
path into an artist and title. With --lookup it also checks them on Discogs (when
DISCOGS_TOKEN is set) and MusicBrainz.

Usage:
    python3 find_missing_metadata.py --out metadata.json
    python3 find_missing_metadata.py --out metadata.json --lookup
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from lookups import (DEFAULT_CACHE, Cache, Client, LookupFailed, clean_discogs_name,
                     discogs_search, musicbrainz_search)
from rb_common import get_db, normalize, similarity

ARTIST_THRESHOLD = 0.8
ALBUM_THRESHOLD = 0.8
MB_MIN_SCORE = 90
NOT_ARTIST_FOLDERS = {"unknown artist", "unknownartist", "contents", "music", "various artists",
                      "compilations", "soulseek downloads", "complete", "downloads"}


def tidy(text: str) -> str:
    text = re.sub(r"\.(mp3|wav|aiff?|flac|m4a)$", "", text.strip(), flags=re.I)
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip()


def strip_position(text: str) -> str:
    """Remove a leading track or vinyl position: `06 - x`, `01-x`, `a1 x`."""
    return re.sub(r"^(\d{1,3}|[a-dA-D]\d)[\s.\-]+(?=\S)", "", text).strip()


def nice_case(text: str) -> str:
    return text.title() if text == text.lower() else text


def artist_from_folder(path: str) -> str:
    parts = path.replace("\\", "/").split("/")
    if len(parts) < 3:
        return ""
    folder = parts[-3]
    if folder.casefold() in NOT_ARTIST_FOLDERS or re.fullmatch(r"_?\d{4}", folder):
        return ""
    return folder


def parse_track(title: str, path: str) -> tuple[str, str]:
    """Best guess at (artist, title) from a filename-style title and its folders."""
    stem = strip_position(tidy(title or os.path.basename(path)))
    if " - " in stem:
        artist, rest = stem.split(" - ", 1)
    elif re.search(r"\w-\w", stem):
        artist, rest = stem.split("-", 1)
    else:
        return artist_from_folder(path), stem
    return artist.strip(), strip_position(rest.strip())


def score_discogs(results: list, artist: str, album: str) -> dict | None:
    """Pick the best release by this artist. Compilations are ignored for the album."""
    hits = []
    for r in results:
        rel_artist, _, release = (r.get("title") or "").partition(" - ")
        name = clean_discogs_name(rel_artist)
        if similarity(normalize(name), normalize(artist)) >= ARTIST_THRESHOLD:
            album_hit = bool(album) and similarity(normalize(release), normalize(album)) >= ALBUM_THRESHOLD
            hits.append({"artist": name, "album": release, "year": r.get("year") or "",
                         "album_hit": album_hit})
    if not hits:
        return None
    best = next((h for h in hits if h["album_hit"]), hits[0])
    confidence = "high" if best["album_hit"] or len(hits) >= 2 else "medium"
    return {"source": "discogs", "confidence": confidence, "artist": best["artist"],
            "album": best["album"], "year": best["year"]}


def score_musicbrainz(recordings: list, artist: str) -> dict | None:
    for r in recordings:
        if (r.get("score", 0) >= MB_MIN_SCORE
                and similarity(normalize(r.get("artist")), normalize(artist)) >= ARTIST_THRESHOLD):
            return {"source": "musicbrainz", "confidence": "medium", "artist": r["artist"],
                    "album": (r.get("releases") or [""])[0], "year": r.get("year") or ""}
    return None


def lookup(artist: str, title: str, album: str, client, cache, token: str) -> dict | None:
    key = f"{normalize(artist)}|{normalize(title)}"
    if token:
        results = cache.fetch(f"discogs|{key}", lambda: discogs_search(client, token, artist, title))
        found = score_discogs(results, artist, album)
        if found:
            return found
    recordings = cache.fetch(f"musicbrainz|{key}", lambda: musicbrainz_search(client, artist, title))
    return score_musicbrainz(recordings, artist)


def main() -> int:
    ap = argparse.ArgumentParser(description="Find tracks with no artist.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lookup", action="store_true", help="Check matches online.")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    args = ap.parse_args()

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    db = get_db()
    tracks = [{"content_id": str(c.ID), "title": c.Title or "", "album": c.AlbumName or "",
               "year": int(c.ReleaseYear or 0), "path": c.FolderPath or ""}
              for c in db.get_content() if not (c.ArtistName or "").strip()]
    db.close()
    tracks = tracks[:args.limit] if args.limit else tracks
    print(f"{len(tracks)} track(s) have no artist.")

    token = os.environ.get("DISCOGS_TOKEN", "")
    client, cache = Client(), Cache(Path(args.cache))
    entries, failures = [], 0
    try:
        for t in tracks:
            artist, title = parse_track(t["title"], t["path"])
            found, note = None, ""
            if args.lookup and artist and title:
                try:
                    found = lookup(artist, title, t["album"], client, cache, token)
                    if not found:
                        found = lookup(title, artist, t["album"], client, cache, token)
                        if found:
                            title = artist
                except LookupFailed as e:
                    failures += 1
                    note = f"lookup failed: {e}"
            has_guess = bool(artist and title)
            entries.append({
                "content_id": t["content_id"], "path": t["path"],
                "current": {"title": t["title"], "album": t["album"], "year": t["year"]},
                "proposed": {
                    "artist": found["artist"] if found else nice_case(artist),
                    "title": nice_case(title),
                    "album": t["album"] or (found["album"] if found else ""),
                    "year": t["year"] or int(str(found["year"])[:4] or 0) if found else t["year"],
                },
                "confidence": found["confidence"] if found else ("filename" if has_guess else "none"),
                "source": found["source"] if found else "filename",
                "status": "pending" if has_guess else "no_match",
                "note": note,
            })
    finally:
        cache.save()

    Path(args.out).write_text(json.dumps({
        "created_at": datetime.now().isoformat(), "entries": entries,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.out}: {dict(Counter(e['confidence'] for e in entries))}")
    if failures:
        print(f"{failures} lookup(s) failed. Re-run to retry them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
