#!/usr/bin/env python3
"""Self-check of filename parsing, scoring and write planning (no database or network)."""
from __future__ import annotations

from apply_metadata import plan_writes
from find_artist_titles import propose
from find_missing_metadata import parse_track, score_discogs, score_musicbrainz

M = "/Volumes/Drive/Music/"


def main() -> int:
    cases = {
        ("slipmatt - breaking free", M + "x/y/z.mp3"): ("slipmatt", "breaking free"),
        ("11 - front 242 - dancesoundtrackmusic (d.s.m.)", M + "x/y/z.mp3"):
            ("front 242", "dancesoundtrackmusic (d.s.m.)"),
        ("01-anthony_linell-nylon_metal_(original_mix)", M + "x/y/z.mp3"):
            ("anthony linell", "nylon metal (original mix)"),
        ("Glass", M + "Zomby/Ultra/06 Glass.mp3"): ("Zomby", "Glass"),
        ("02 Rhythm of Time", M + "Front 242/Tyranny/02 Rhythm of Time.mp3"):
            ("Front 242", "Rhythm of Time"),
        ("Grandstand Theme", M + "Unknown Artist/Unknown Album/g.mp3"): ("", "Grandstand Theme"),
        ("a1 computers are in control", M + "_2025/April/a1.wav"): ("", "computers are in control"),
    }
    for (title, path), expected in cases.items():
        assert parse_track(title, path) == expected, (title, parse_track(title, path))

    one = [{"title": "Slipmatt (2) - Breaking Free", "year": "1992"}]
    found = score_discogs(one, "slipmatt", "")
    assert found["artist"] == "Slipmatt" and found["confidence"] == "medium", found
    assert score_discogs(one * 2, "slipmatt", "")["confidence"] == "high"
    assert score_discogs(one, "slipmatt", "Breaking Free")["confidence"] == "high"
    assert score_discogs([{"title": "Various - Rave"}], "slipmatt", "") is None
    assert score_musicbrainz([{"score": 95, "artist": "Slipmatt"}], "slipmatt")["confidence"] == "medium"
    assert score_musicbrainz([{"score": 50, "artist": "Slipmatt"}], "slipmatt") is None

    entries = [{"content_id": c, "status": s} for c, s in
               [("1", "accepted"), ("2", "pending"), ("3", "accepted"), ("4", "accepted")]]
    writes, skipped = plan_writes(entries, {"1": "", "2": "", "3": "Someone"})
    assert [e["content_id"] for e in writes] == ["1"] and len(skipped) == 2, (writes, skipped)
    entries = [{"content_id": c, "status": "accepted", "replace_artist": True,
                "current": {"artist": "Label"}} for c in ("1", "2")]
    writes, skipped = plan_writes(entries, {"1": "Label", "2": "Someone"})
    assert [e["content_id"] for e in writes] == ["1"] and len(skipped) == 1, (writes, skipped)

    labels = ["causal chain"]
    cases = {
        ("Anthony Linell", "Anthony Linell - Genesis (Version)"):
            ("remove", "Anthony Linell", "Genesis (Version)"),
        ("DJ QU", "B2. DJ QU –  Loveboxx"): ("remove", "DJ QU", "Loveboxx"),
        ("Beverly Hills 808303", "17_Beverly Hills 808303 - Acid Planet 4 - A2"):
            ("remove", "Beverly Hills 808303", "Acid Planet 4 - A2"),
        ("Causal Chain", "DivPro - Leaking"): ("move", "DivPro", "Leaking"),
        ("Various Artists", "Valley Of The Shadows - Origin Unknown"):
            ("check", "Valley Of The Shadows", "Origin Unknown"),
        ("Razor Boy & Mirror Man", "Cutter Mix - Razor Boy & Mirror Man"):
            ("check", "Razor Boy & Mirror Man", "Cutter Mix"),
        ("Special Request", "Tessela - Hackney Parrot (Special Request VIP)"):
            ("check", "Tessela", "Hackney Parrot (Special Request VIP)"),
    }
    for (artist, title), expected in cases.items():
        assert propose(artist, title, labels) == expected, (title, propose(artist, title, labels))
    for artist, title in [("Squarepusher", "Squarepusher Theme"),
                          ("Laraaji", "Trance Celestial - Movement 1"),
                          ("Alloy Sea", "Petrichor (full - continuous)")]:
        assert propose(artist, title, labels) is None, title

    print("metadata checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
