#!/usr/bin/env python3
"""Self-check of the genre scoring and write planning (no database or network)."""
from __future__ import annotations

from apply_genres import plan_writes
from scan_genres import (clean_discogs_name, compare_genre, query_terms, score_discogs,
                         score_musicbrainz)


def release(title, style, genre=("Electronic",), year="1994"):
    return {"title": title, "style": list(style), "genre": list(genre), "year": year}


def main() -> int:
    assert query_terms({"artist": "Synaesthesia", "base_title": "A1 - Feel the Dream"}) == (
        "Synaesthesia", "Feel the Dream")
    assert query_terms({"artist": "Liam Costar",
                        "base_title": "Liam Costar - Eyes of tempt"}) == (
        "Liam Costar", "Eyes of tempt")
    assert query_terms({"artist": "", "title": "Shy FX - Original Nuttah"})[0] == "Shy FX"
    assert clean_discogs_name("Age Coin (2)") == "Age Coin"
    assert clean_discogs_name("Front 242*") == "Front 242"

    hit = score_discogs([release("Shy FX - Original Nuttah", ["Jungle"])],
                        "Shy FX", "Original Nuttah")
    assert hit["confidence"] == "high" and hit["proposed"] == "Jungle", hit

    one = score_discogs([release("Shy FX - Something Else", ["Jungle"])], "Shy FX", "Album")
    assert one["confidence"] == "medium", one

    three = score_discogs([release(f"Shy FX - R{i}", ["Jungle"]) for i in range(3)],
                          "Shy FX", "")
    assert three["confidence"] == "high", three

    split = score_discogs([release("Shy FX - A", ["Jungle"]), release("Shy FX - B", ["Dub"]),
                           release("Shy FX - C", ["House"])], "Shy FX", "")
    assert split["confidence"] == "medium", split

    comp = score_discogs([release("Various - Jungle Hits", ["Jungle"])], "Shy FX", "")
    assert comp["confidence"] == "low", comp

    assert score_discogs([release("Someone Else - Album", ["House"])], "Shy FX", "") is None

    broad = score_discogs([release("Shy FX - A", [], ["Electronic"])], "Shy FX", "")
    assert broad["proposed"] == "Electronic", broad

    rec = {"score": 100, "artist": "Shy FX", "tags": ["jungle"], "releases": ["X"]}
    assert score_musicbrainz([rec], "Shy FX", [])["confidence"] == "low"
    bare = {**rec, "tags": []}
    assert score_musicbrainz([bare], "Shy FX", ["drum and bass"])["confidence"] == "low"
    assert score_musicbrainz([bare], "Shy FX", []) is None
    assert score_musicbrainz([{**rec, "score": 50}], "Shy FX", []) is None

    found = {"styles": ["Jungle", "Drum n Bass"], "broad": ["Electronic"]}
    assert compare_genre("", found) == "blank"
    assert compare_genre("House", None) == "no_lookup"
    assert compare_genre("electronic", found) == "refines"
    assert compare_genre("Electronica/Dance", found) == "refines"
    assert compare_genre("Electronic; Jungle", found) == "agrees"
    assert compare_genre("Drum n Bass, Jungle", found) == "agrees"
    assert compare_genre("Dance", found) == "refines"
    assert compare_genre("Electronica", found) == "refines"
    assert compare_genre("Metal", found) == "conflict"
    assert compare_genre("Dance/Metal", found) == "conflict"

    def entry(cid, status="accepted", proposed="Jungle", current=""):
        return {"content_id": cid, "status": status, "proposed": proposed,
                "current_genre": current, "artist": "a", "title": "t"}

    writes, skipped, new = plan_writes(
        [entry("1"), entry("2", "pending"), entry("3"), entry("4", proposed="techno"),
         entry("5")],
        {"1": "", "2": "", "3": "Manual Edit", "4": ""}, {"techno": "Techno"})
    assert [w["content_id"] for w in writes] == ["1", "4"], writes
    assert writes[1]["genre"] == "Techno", writes
    assert new == {"Jungle"}, new
    assert len(skipped) == 2, skipped

    print("genre lookup checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
