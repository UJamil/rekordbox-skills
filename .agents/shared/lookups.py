#!/usr/bin/env python3
"""Discogs and MusicBrainz lookups, shared by the skills that fetch metadata.

Requests are throttled and responses cached on disk, so an interrupted scan resumes
where it stopped. DISCOGS_TOKEN is read by callers from the environment.
"""
from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "rekordbox-skills/0.1 (https://github.com/sean-a-wilson/rekordbox-skills)"
DEFAULT_CACHE = Path.home() / ".cache" / "rekordbox-skills" / "genre-lookups.json"
REQUEST_INTERVAL = 1.1  # both services allow about one request per second


class LookupFailed(Exception):
    pass


class Client:
    """Throttled JSON GET with a retry when the service asks us to slow down."""

    def __init__(self):
        self.last = 0.0

    def get(self, url: str, headers: dict) -> dict:
        for attempt in range(3):
            wait = REQUEST_INTERVAL - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    raise SystemExit("Discogs rejected DISCOGS_TOKEN (401). Check the token.")
                if e.code in (429, 503) and attempt < 2:
                    time.sleep(int(e.headers.get("Retry-After") or 60))
                    continue
                raise LookupFailed(f"HTTP {e.code}")
            except (OSError, http.client.HTTPException, json.JSONDecodeError) as e:
                raise LookupFailed(str(e) or type(e).__name__)
        raise LookupFailed("rate limited")


def clean_discogs_name(name: str) -> str:
    return re.sub(r"\s*\(\d+\)$", "", name.strip()).rstrip("*").strip()


def discogs_search(client: Client, token: str, artist: str, title: str) -> list:
    params = urllib.parse.urlencode(
        {"artist": artist, "track": title, "type": "release", "per_page": 10})
    data = client.get(f"https://api.discogs.com/database/search?{params}",
                      {"Authorization": f"Discogs token={token}"})
    keep = ("title", "genre", "style", "year")
    return [{k: r.get(k) for k in keep} for r in data.get("results", [])]


def musicbrainz_search(client: Client, artist: str, title: str) -> list:
    def quoted(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    params = urllib.parse.urlencode({
        "query": f"artist:{quoted(artist)} AND recording:{quoted(title)}",
        "fmt": "json", "limit": 5})
    data = client.get(f"https://musicbrainz.org/ws/2/recording?{params}", {})
    out = []
    for r in data.get("recordings", []):
        credit = (r.get("artist-credit") or [{}])[0]
        out.append({
            "score": r.get("score", 0),
            "artist": credit.get("name", ""),
            "artist_id": (credit.get("artist") or {}).get("id", ""),
            "tags": [t["name"] for t in r.get("tags") or []],
            "releases": [x.get("title", "") for x in r.get("releases") or []][:5],
            "year": (r.get("first-release-date") or "")[:4],
        })
    return out


def musicbrainz_artist_genres(client: Client, artist_id: str) -> list:
    data = client.get(
        f"https://musicbrainz.org/ws/2/artist/{artist_id}?inc=genres&fmt=json", {})
    ranked = sorted(data.get("genres") or [], key=lambda g: -g.get("count", 0))
    return [g["name"] for g in ranked]


class Cache:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.unsaved = 0

    def fetch(self, key: str, fn):
        if key not in self.data:
            self.data[key] = fn()
            self.unsaved += 1
            if self.unsaved >= 25:
                self.save()
        return self.data[key]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
        self.unsaved = 0
