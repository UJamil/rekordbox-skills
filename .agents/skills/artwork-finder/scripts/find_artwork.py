#!/usr/bin/env python3
"""Find tracks with no artwork and propose some. Read-only for the library.

Tracks are grouped by album and folder. Each group tries, in order: art a track on the
same album already has in rekordbox, art inside the audio file, a cover image in the
folder, and with --lookup, Discogs and the Cover Art Archive.

Usage:
    python3 find_artwork.py --out art.json --limit 20
    python3 find_artwork.py --out art.json --lookup
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from lookups import (DEFAULT_CACHE, REQUEST_INTERVAL, USER_AGENT, Cache, Client, LookupFailed,
                     clean_discogs_name)
from rb_common import get_db, normalize, similarity

ARTIST_THRESHOLD = 0.8
ALBUM_THRESHOLD = 0.8
MB_MIN_SCORE = 90
MIN_PIXELS = 250
COVER_NAMES = ("cover", "folder", "front", "album", "artwork")
IMAGE_EXTS = (".jpg", ".jpeg", ".png")
AUDIO_EXTS = (".mp3", ".flac", ".aiff", ".aif", ".wav", ".m4a", ".ogg", ".wma")
NOT_ALBUMS = {"", "unknown album", "unknownalbum"}


def group_key(track: dict) -> tuple:
    """Same album in the same folder. A track with no album stands alone."""
    album = normalize(track["album"])
    if album in NOT_ALBUMS:
        return ("track", track["content_id"])
    return (album, os.path.dirname(track["path"]))


def sibling_art(tracks: list, art_by_album: dict) -> str:
    """An image path another track on this album already uses."""
    for t in tracks:
        album = normalize(t["album"])
        for key in ((album, os.path.dirname(t["path"])), (album, normalize(t["artist"]))):
            if album not in NOT_ALBUMS and key in art_by_album:
                return art_by_album[key]
    return ""


def embedded_art(path: str) -> bytes | None:
    try:
        import mutagen
        from mutagen.flac import FLAC
        from mutagen.mp4 import MP4
    except ImportError:
        return None
    try:
        audio = mutagen.File(path)
    except Exception:
        return None
    if audio is None:
        return None
    if isinstance(audio, FLAC):
        return audio.pictures[0].data if audio.pictures else None
    if isinstance(audio, MP4):
        covers = (audio.tags or {}).get("covr")
        return bytes(covers[0]) if covers else None
    for key in (audio.tags or {}):
        if key.startswith("APIC"):
            return audio.tags[key].data
    return None


def folder_cover(path: str) -> str:
    folder = os.path.dirname(path)
    try:
        names = os.listdir(folder)
    except OSError:
        return ""
    for wanted in COVER_NAMES:
        for name in names:
            stem, ext = os.path.splitext(name)
            if stem.lower() == wanted and ext.lower() in IMAGE_EXTS and not name.startswith("._"):
                return os.path.join(folder, name)
    return ""


def tidy_folder(name: str) -> str:
    """Drop years, labels and catalogue tags from a folder name."""
    return re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", name).strip()


def biggest_image(folder: str, names: list) -> str:
    images = [n for n in names if n.lower().endswith(IMAGE_EXTS) and not n.lower().startswith("albumartsmall")]
    return os.path.join(folder, max(images, key=lambda n: os.path.getsize(os.path.join(folder, n)))) if images else ""


def leftover_art(root: str) -> list:
    """Cover images in folders with no audio left. Tracks often move on and leave the
    sleeve behind. A folder is `Artist/Album`, or `Artist - Album` with or without a year."""
    found = []
    for folder, _, names in os.walk(root):
        names = [n for n in names if not n.startswith("._")]
        if any(n.lower().endswith(AUDIO_EXTS) for n in names):
            continue
        image = biggest_image(folder, names)
        if image:
            parent, name = os.path.split(folder)
            parts = [p.strip() for p in tidy_folder(name).split(" - ") if p.strip()]
            if not parts:
                continue
            found.append({"artist": parts[0] if len(parts) > 1 else os.path.basename(parent),
                          "parent": os.path.basename(parent), "album": parts[-1], "image": image})
    return found


def match_leftover(group: dict, leftovers: list) -> tuple:
    """A left-behind cover for this album by this artist, as (image, confidence).
    Compilations match on title alone. A near match on the title needs a look."""
    album = normalize(tidy_folder(group["album"]))
    if album in NOT_ALBUMS:
        return "", ""
    best, best_score = None, 0.0
    for hit in leftovers:
        score = similarity(album, normalize(hit["album"]))
        artist_ok = group["mixed"] or ARTIST_THRESHOLD <= max(
            similarity(normalize(hit[k]), normalize(group["artist"])) for k in ("artist", "parent"))
        if artist_ok and score >= ALBUM_THRESHOLD and score > best_score:
            best, best_score = hit, score
    if not best:
        return "", ""
    return best["image"], "high" if best_score >= 0.95 and not group["mixed"] else "medium"


def split_release(title: str) -> tuple:
    artist, _, release = (title or "").partition(" - ")
    return clean_discogs_name(artist), release.strip()


def score_album(results: list, artist: str, album: str, mixed: bool) -> dict | None:
    """The best release for an album. `mixed` means a compilation, matched on title alone."""
    for r in results:
        name, release = split_release(r.get("title"))
        cover = r.get("cover_image") or ""
        if not cover or cover.endswith("spacer.gif"):
            continue
        if similarity(normalize(release), normalize(album)) < ALBUM_THRESHOLD:
            continue
        if mixed:
            return {"confidence": "medium", "url": cover, "release": r.get("title")}
        if similarity(normalize(name), normalize(artist)) >= ARTIST_THRESHOLD:
            return {"confidence": "high", "url": cover, "release": r.get("title")}
    return None


def score_track(results: list, artist: str) -> dict | None:
    """The first release holding this track by this artist."""
    for r in results:
        name, _ = split_release(r.get("title"))
        cover = r.get("cover_image") or ""
        if cover and not cover.endswith("spacer.gif") \
                and similarity(normalize(name), normalize(artist)) >= ARTIST_THRESHOLD:
            return {"confidence": "medium", "url": cover, "release": r.get("title")}
    return None


def discogs_results(client, token: str, **params) -> list:
    query = urllib.parse.urlencode({**params, "type": "release", "per_page": 10})
    data = client.get(f"https://api.discogs.com/database/search?{query}",
                      {"Authorization": f"Discogs token={token}"})
    return [{"title": r.get("title"), "cover_image": r.get("cover_image")}
            for r in data.get("results", [])]


def musicbrainz_releases(client, artist: str, album: str) -> list:
    def quoted(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    query = f"release:{quoted(album)}" + (f" AND artist:{quoted(artist)}" if artist else "")
    params = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": 5})
    data = client.get(f"https://musicbrainz.org/ws/2/release?{params}", {})
    return [{"id": r.get("id"), "score": r.get("score", 0), "title": r.get("title"),
             "artist": ((r.get("artist-credit") or [{}])[0]).get("name", "")}
            for r in data.get("releases", [])]


def look_up(group: dict, client, cache, token: str) -> dict | None:
    artist, album, title = group["artist"], group["album"], group["tracks"][0]["title"]
    has_album = normalize(album) not in NOT_ALBUMS
    mixed = group["mixed"]
    if token and has_album:
        params = {"release_title": album} if mixed else {"artist": artist, "release_title": album}
        results = cache.fetch(f"art|discogs|{normalize(artist) if not mixed else ''}|{normalize(album)}",
                              lambda: discogs_results(client, token, **params))
        found = score_album(results, artist, album, mixed)
        if found:
            return {**found, "source": "discogs"}
    if token and artist and title:
        results = cache.fetch(f"art|discogs-track|{normalize(artist)}|{normalize(title)}",
                              lambda: discogs_results(client, token, artist=artist, track=title))
        found = score_track(results, artist)
        if found:
            return {**found, "source": "discogs"}
    if has_album:
        releases = cache.fetch(f"art|mb|{normalize(artist) if not mixed else ''}|{normalize(album)}",
                               lambda: musicbrainz_releases(client, "" if mixed else artist, album))
        for r in releases:
            if r["score"] >= MB_MIN_SCORE and similarity(normalize(r["title"]), normalize(album)) >= ALBUM_THRESHOLD \
                    and (mixed or similarity(normalize(r["artist"]), normalize(artist)) >= ARTIST_THRESHOLD):
                return {"confidence": "medium", "source": "cover art archive", "release": r["title"],
                        "url": f"https://coverartarchive.org/release/{r['id']}/front-500"}
    return None


def download(url: str, dest: Path, state: dict) -> bool:
    """Fetch an image, one request at a time. A 404 just means no cover."""
    wait = REQUEST_INTERVAL - (time.monotonic() - state.get("last", 0))
    if wait > 0:
        time.sleep(wait)
    state["last"] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())
        return True
    except (urllib.error.URLError, OSError):
        return False


def pixels(path: Path) -> int:
    """The image's smaller side, or 0 if it isn't a readable image."""
    out = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                         capture_output=True, text=True).stdout
    sides = [int(n) for n in re.findall(r"pixel(?:Width|Height): (\d+)", out)]
    return min(sides) if len(sides) == 2 else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Find tracks with no artwork and propose some.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--images", help="Folder for proposed images (default: beside --out).")
    ap.add_argument("--lookup", action="store_true", help="Also check Discogs and the Cover Art Archive.")
    ap.add_argument("--art-root", help="Also search this folder for covers left in folders with no audio.")
    ap.add_argument("--limit", type=int, help="Only check this many albums.")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    args = ap.parse_args()

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    db = get_db()
    tracks, art_by_album = [], {}
    for c in db.get_content():
        t = {"content_id": str(c.ID), "artist": (c.ArtistName or "").strip(), "title": c.Title or "",
             "album": (c.AlbumName or "").strip(), "path": c.FolderPath or ""}
        image = (c.ImagePath or "").strip()
        if image:
            album = normalize(t["album"])
            art_by_album.setdefault((album, os.path.dirname(t["path"])), image)
            art_by_album.setdefault((album, normalize(t["artist"])), image)
        elif os.path.exists(t["path"]):
            tracks.append(t)
    db.close()

    grouped = defaultdict(list)
    for t in tracks:
        grouped[group_key(t)].append(t)
    groups = []
    for n, members in enumerate(grouped.values(), 1):
        artists = Counter(t["artist"] for t in members if t["artist"])
        groups.append({"id": f"g{n:04}", "album": members[0]["album"], "tracks": members,
                       "artist": artists.most_common(1)[0][0] if artists else "",
                       "mixed": len(artists) > 1})
    groups.sort(key=lambda g: -len(g["tracks"]))
    groups = groups[:args.limit] if args.limit else groups
    print(f"{len(tracks)} track(s) with no artwork, in {len(groups)} group(s).")

    out = Path(args.out)
    images = Path(args.images) if args.images else out.with_name(out.stem + "-images")
    images.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("DISCOGS_TOKEN", "")
    client, cache, state, failures = Client(), Cache(Path(args.cache)), {}, 0
    leftovers = leftover_art(args.art_root) if args.art_root else []
    try:
        for n, g in enumerate(groups, 1):
            g.update(confidence="none", source="", image="", image_path="", release="", pixels=0,
                     status="no_match", note="")
            dest = images / f"{g['id']}.img"
            g["image_path"] = sibling_art(g["tracks"], art_by_album)
            if g["image_path"]:
                g.update(confidence="high", source="same album", status="pending")
            else:
                data = next(filter(None, (embedded_art(t["path"]) for t in g["tracks"][:3])), None)
                cover = folder_cover(g["tracks"][0]["path"])
                left, left_confidence = ("", "") if cover else match_leftover(g, leftovers)
                if data:
                    dest.write_bytes(data)
                    g["source"] = "inside file"
                elif cover:
                    dest.write_bytes(Path(cover).read_bytes())
                    g["source"] = "folder"
                elif left:
                    dest.write_bytes(Path(left).read_bytes())
                    g.update(source="left-behind cover", release=left, confidence=left_confidence)
                elif args.lookup:
                    try:
                        found = look_up(g, client, cache, token)
                    except LookupFailed as e:
                        failures += 1
                        g["note"] = f"lookup failed: {e}"
                        found = None
                    if found and download(found["url"], dest, state):
                        g.update(source=found["source"], release=found["release"] or "",
                                 confidence=found["confidence"])
                if dest.exists():
                    size = pixels(dest)
                    if size >= MIN_PIXELS:
                        g.update(image=str(dest), pixels=size, status="pending",
                                 confidence="high" if g["source"] in ("inside file", "folder") else g["confidence"])
                    else:
                        g.update(source="", release="", confidence="none",
                                 note=f"image too small or unreadable ({size}px)")
                        dest.unlink()
            if n % 50 == 0:
                print(f"  {n}/{len(groups)}", flush=True)
    finally:
        cache.save()

    out.write_text(json.dumps({"created_at": datetime.now().isoformat(), "groups": groups},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out}: {dict(Counter(g['confidence'] for g in groups))}")
    print(f"By source: {dict(Counter(g['source'] or 'none' for g in groups))}")
    if failures:
        print(f"{failures} lookup(s) failed. Re-run to retry them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
