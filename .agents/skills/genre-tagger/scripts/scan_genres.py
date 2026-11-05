#!/usr/bin/env python3
"""Look up genres for rekordbox tracks and write a review manifest.

Read-only with respect to the database. Each track is looked up on Discogs (when
DISCOGS_TOKEN is set), then MusicBrainz. Responses are cached on disk, so an
interrupted scan resumes where it stopped and re-scoring costs no requests.

Usage:
    python3 scan_genres.py --out genres.json
    python3 scan_genres.py --out genres.json --limit 20
    python3 scan_genres.py --out genres.json --all
    python3 scan_genres.py --out genres.json --exclude-losers dedupe-manifest.json
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
                     discogs_search, musicbrainz_artist_genres, musicbrainz_search)
from rb_common import effective_artist, get_db, normalize, similarity, track_facts

ARTIST_THRESHOLD = 0.8
ALBUM_THRESHOLD = 0.8
MB_MIN_SCORE = 90
# Catch-all labels that a specific style can replace without it being a conflict.
BROAD_GENRES = {"electronic", "electronica", "electronicdance", "dance", "other",
                "unknown", "misc", "bass", "club", "edm", "alternative"}


def query_terms(track: dict) -> tuple[str, str]:
    """Artist and title to search for, with common tag noise removed: vinyl side
    prefixes ('A1 - Title') and an artist repeated in the title."""
    artist = effective_artist(track)
    title = track.get("base_title") or track.get("title") or ""
    title = re.sub(r"^[A-Da-d]\d?\s*[-.]\s+", "", title).strip()
    if artist and normalize(title).startswith(normalize(artist)) and " - " in title:
        title = title.split(" - ", 1)[1].strip()
    return artist, title


def score_discogs(results: list, artist: str, album: str) -> dict | None:
    """Vote on styles across the results by this artist. A hit on the track's own
    album counts double and makes the proposal high confidence; so does agreement
    across three or more releases. Compilations alone stay low confidence."""
    matched = []
    for r in results:
        rel_artist, _, release = (r.get("title") or "").partition(" - ")
        various = normalize(rel_artist) == "various"
        name_score = similarity(normalize(clean_discogs_name(rel_artist)), normalize(artist))
        if name_score < ARTIST_THRESHOLD and not various:
            continue
        album_hit = bool(album) and (
            similarity(normalize(release), normalize(album)) >= ALBUM_THRESHOLD)
        matched.append({"r": r, "release": release, "various": various, "album_hit": album_hit})
    if not matched:
        return None

    styles, broad = Counter(), Counter()
    for m in matched:
        weight = 2 if m["album_hit"] else 1
        styles.update({s: weight for s in m["r"].get("style") or []})
        broad.update({g: weight for g in m["r"].get("genre") or []})
    ranked = [s for s, _ in styles.most_common()] or [g for g, _ in broad.most_common()]
    if not ranked:
        return None

    direct = [m for m in matched if not m["various"]]
    agreeing = [m for m in direct
                if ranked[0] in (m["r"].get("style") or []) + (m["r"].get("genre") or [])]
    if any(m["album_hit"] for m in direct):
        confidence = "high"
    elif len(direct) >= 3 and len(agreeing) / len(direct) > 0.5:
        confidence = "high"
    elif direct:
        confidence = "medium"
    else:
        confidence = "low"

    best = next((m for m in direct if m["album_hit"]), (direct or matched)[0])
    return {"source": "discogs", "confidence": confidence, "proposed": ranked[0],
            "styles": ranked, "broad": [g for g, _ in broad.most_common()],
            "release": best["release"], "release_year": best["r"].get("year") or "",
            "evidence": f"{len(direct)} release(s) by artist, {len(matched)} matched"}


def score_musicbrainz(recordings: list, artist: str, artist_genres: list) -> dict | None:
    """MusicBrainz tags are sparse and free-form, and a compilation's tag can land
    on every track on it, so these always rate low."""
    matched = [r for r in recordings if r.get("score", 0) >= MB_MIN_SCORE
               and similarity(normalize(r.get("artist")), normalize(artist)) >= ARTIST_THRESHOLD]
    if not matched:
        return None
    tags = Counter(t for r in matched for t in r.get("tags") or [])
    ranked = [t for t, _ in tags.most_common()]
    evidence = f"recording tags on {len(matched)} match(es)"
    if not ranked:
        ranked = list(artist_genres)
        evidence = "artist-wide genre, not this recording"
    if not ranked:
        return None
    return {"source": "musicbrainz", "confidence": "low",
            "proposed": ranked[0].title(), "styles": [t.title() for t in ranked],
            "broad": [], "release": (matched[0].get("releases") or [""])[0],
            "release_year": matched[0].get("year") or "", "evidence": evidence}


def lookup(track: dict, client: Client, cache: Cache, token: str) -> dict | None:
    artist, title = query_terms(track)
    key = f"{normalize(artist)}|{normalize(title)}"
    if token:
        results = cache.fetch(f"discogs|{key}",
                              lambda: discogs_search(client, token, artist, title))
        found = score_discogs(results, artist, track.get("album") or "")
        if found:
            return found
    recordings = cache.fetch(f"musicbrainz|{key}",
                             lambda: musicbrainz_search(client, artist, title))
    artist_genres = []
    close = [r for r in recordings if r.get("score", 0) >= MB_MIN_SCORE and r.get("artist_id")
             and similarity(normalize(r.get("artist")), normalize(artist)) >= ARTIST_THRESHOLD]
    if close and not any(r.get("tags") for r in close):
        artist_id = close[0]["artist_id"]
        artist_genres = cache.fetch(f"musicbrainz-artist|{artist_id}",
                                    lambda: musicbrainz_artist_genres(client, artist_id))
    return score_musicbrainz(recordings, artist, artist_genres)


def genre_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold().replace("&", "and"))


def compare_genre(current: str, found: dict | None) -> str:
    """How an existing genre relates to a lookup: `blank`, `agrees` (same label or
    one the source also lists), `refines` (ours is a catch-all, theirs is specific)
    or `conflict` (they disagree, so a person decides)."""
    if not current:
        return "blank"
    if not found:
        return "no_lookup"
    parts = {genre_key(p) for p in re.split(r"[,;/&|()]+", current) if p.strip()}
    parts.add(genre_key(current))
    specific = parts - BROAD_GENRES
    if not specific or specific == {genre_key(current)} and len(parts) > 1 and parts - {genre_key(current)} <= BROAD_GENRES:
        return "refines"
    theirs = {genre_key(s) for s in found["styles"] + found["broad"]} - BROAD_GENRES
    return "agrees" if specific & theirs else "conflict"


def collapsed_losers(manifest_path: str) -> set[str]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    losers = set()
    for grp in manifest.get("groups", []):
        if grp.get("decision") == "collapse":
            winner = str(grp["winner_content_id"])
            losers |= {str(m["content_id"]) for m in grp["members"]} - {winner}
    return losers


def main() -> int:
    ap = argparse.ArgumentParser(description="Look up genres and write a review manifest.")
    ap.add_argument("--out", required=True, help="Manifest path to write.")
    ap.add_argument("--all", action="store_true",
                    help="Include tracks that already have a genre (default: blank only).")
    ap.add_argument("--only-existing", action="store_true",
                    help="Only tracks that already have a genre, to compare them.")
    ap.add_argument("--limit", type=int, help="Only look up this many tracks.")
    ap.add_argument("--exclude-losers", metavar="MANIFEST",
                    help="Skip tracks a playlist-dedupe manifest collapsed away.")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="Lookup cache path.")
    args = ap.parse_args()

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    token = os.environ.get("DISCOGS_TOKEN", "")
    print(f"Sources: {'Discogs, then ' if token else ''}MusicBrainz"
          f"{'' if token else ' (set DISCOGS_TOKEN to add Discogs)'}")

    skip = collapsed_losers(args.exclude_losers) if args.exclude_losers else set()
    tracks = []
    db = get_db()
    for c in db.get_content():
        t = track_facts(c)
        t["album"] = c.AlbumName or ""
        t["year"] = c.ReleaseYear or 0
        t["genre"] = (c.GenreName or "").strip()
        wanted = bool(t["genre"]) if args.only_existing else (args.all or not t["genre"])
        if t["content_id"] not in skip and wanted:
            tracks.append(t)
    db.close()  # the lookups take an hour; don't hold the database open for them
    tracks = tracks[:args.limit] if args.limit else tracks
    print(f"Looking up {len(tracks)} track(s).")

    client, cache = Client(), Cache(Path(args.cache))
    entries = []
    failures = 0
    try:
        for n, t in enumerate(tracks, 1):
            artist, title = query_terms(t)
            found, note = None, ""
            if not (artist and title):
                note = "no artist or title to search on"
            else:
                try:
                    found = lookup(t, client, cache, token)
                except LookupFailed as e:
                    failures += 1
                    note = f"lookup failed: {e}"
            comparison = compare_genre(t["genre"], found)
            entries.append({
                "content_id": t["content_id"], "artist": t["artist"], "title": t["title"],
                "album": t["album"], "year": t["year"], "current_genre": t["genre"],
                "confidence": found["confidence"] if found else "none",
                "proposed": found["proposed"] if found else "",
                "comparison": comparison,
                "status": ("no_change" if comparison == "agrees"
                           else "pending" if found else "no_match"),
                "note": note, **({k: found[k] for k in (
                    "source", "styles", "broad", "release", "release_year", "evidence")}
                    if found else {}),
            })
            if n % 100 == 0:
                print(f"  {n}/{len(tracks)}", flush=True)
    finally:
        cache.save()

    Path(args.out).write_text(json.dumps({
        "created_at": datetime.now().isoformat(), "entries": entries,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    counts = Counter(e["confidence"] for e in entries)
    print(f"Wrote {args.out}: {counts['high']} high, {counts['medium']} medium, "
          f"{counts['low']} low, {counts['none']} no match.")
    if failures:
        print(f"{failures} lookup(s) failed and were not cached. Re-run to retry them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
