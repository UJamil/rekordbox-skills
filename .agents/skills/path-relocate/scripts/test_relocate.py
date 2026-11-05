#!/usr/bin/env python3
"""Self-check of the relocation planning (no database or real files)."""
from __future__ import annotations

from merge_duplicates import metadata_fills, plan_identical, plan_merges, plan_pairs
from relocate_paths import plan_relocation

OLD, NEW = "/Volumes/Old/", "/Volumes/New/"


def main() -> int:
    on_disk = {NEW + "a.mp3", NEW + "dup.mp3", OLD + "still.mp3", NEW + "still.mp3"}
    paths = {
        "1": OLD + "a.mp3",
        "2": OLD + "gone.mp3",
        "3": OLD + "still.mp3",
        "4": OLD + "dup.mp3",
        "5": NEW + "dup.mp3",
        "6": "/Users/me/other.mp3",
        "7": "",
    }
    moves, unresolved = plan_relocation(paths, OLD, NEW, exists=on_disk.__contains__)
    assert moves == [{"content_id": "1", "old": OLD + "a.mp3", "new": NEW + "a.mp3"}], moves
    reasons = {u["content_id"]: u["reason"] for u in unresolved}
    assert reasons == {
        "2": "no file at the new path",
        "3": "file still exists at the old path",
        "4": "another track already uses the new path",
    }, reasons
    def group(kept, *dups):
        return {"decision": "collapse", "winner_content_id": kept,
                "members": [{"content_id": c} for c in (kept, *dups)]}

    disk = {"/d", "/e", "/f", "/g", "/h", "/ok"}
    paths = {"k1": "/x1", "d1": "/d", "k2": "/x2", "d2": "/e", "d2b": "/f", "k3": "/x3",
             "d3": "/g", "k4": "/x4", "d4": "/h", "k5": "/ok", "d5": "/d", "k6": "/x6"}
    sizes = {k: 1 for k in paths}
    sizes["d3"] = 2
    manifest = {"groups": [group("k1", "d1"), group("k2", "d2", "d2b"), group("k3", "d3"),
                           group("k4", "d4"), group("k5", "d5"), group("k6"),
                           {"decision": "keep_all", "winner_content_id": "k1", "members": []}]}
    merges, review = plan_merges(manifest, paths, sizes, {"d4": 1},
                                 {"d1": [("Claude Backups / x", True)]},
                                 exists=disk.__contains__)
    assert [(m["kept"], m["duplicate"]) for m in merges] == [("k1", "d1")], merges
    assert {r["kept"]: r["reason"] for r in review} == {
        "k2": "several working duplicates", "k3": "file sizes differ",
        "k4": "duplicate has cues", "k6": "no working duplicate"}, review
    merges, review = plan_merges({"groups": [group("k1", "d1")]}, paths, sizes, {},
                                 {"d1": [("Mixes / x", False)]}, exists=disk.__contains__)
    assert not merges and review[0]["reason"] == "duplicate is in a playlist", review

    paths = {"k": "/x", "d": "/d", "k2": "/x2", "d2": "/e", "k3": "/x3", "k4": "/x4",
             "k5": "/ok", "d5": "/f"}
    sizes = {k: 1 for k in paths}
    sizes["k4"] = 9
    pairs = [{"kept": "k", "duplicate": "d"}, {"kept": "k2", "duplicate": "d2"},
             {"kept": "k3", "new_path": "/g"}, {"kept": "k4", "new_path": "/h"},
             {"kept": "k5", "duplicate": "d5"}, {"kept": "k3", "new_path": "/d"}]
    member = {"d": [("Mixes / a", False)], "d2": [("Mixes / b", False)],
              "k2": [("Mixes / b", False)]}
    merges, review = plan_pairs(pairs, paths, sizes, {}, member,
                                exists=disk.__contains__, disk_size=lambda p: 1)
    assert [(m["kept"], m["moved_playlists"]) for m in merges] == [
        ("k", ["Mixes / a"]), ("k3", [])], merges
    assert [r["reason"] for r in review] == [
        "both entries are in the same playlist", "file sizes differ",
        "kept entry already has a file", "another entry already uses the file"], review
    assert plan_pairs([{"kept": "k", "duplicate": "d"}], paths, sizes, {"d": 2}, {},
                      exists=disk.__contains__)[1][0]["reason"] == "duplicate has cues"

    paths = {"k": "/d", "d": "/e", "k2": "/f", "d2": "/g", "k3": "/x3", "d3": "/h", "k4": "/ok"}
    pairs = [{"kept": "k", "duplicate": "d"}, {"kept": "k2", "duplicate": "d2"},
             {"kept": "k3", "duplicate": "d3"}, {"kept": "k4", "duplicate": "gone"}]
    merges, review = plan_identical(pairs, paths, {"d2": 1}, exists=disk.__contains__,
                                    disk_size=lambda p: 1)
    assert [(m["kept"], m["new_path"]) for m in merges] == [("k", "/d")], merges
    assert [r["reason"] for r in review] == [
        "duplicate has cues", "a file is missing", "entry is no longer in the library"], review
    assert plan_identical(pairs[:1], paths, {}, exists=disk.__contains__,
                          disk_size=len)[0], "same-length paths count as same size"
    assert plan_identical(pairs[:1], {"k": "/d", "d": "/long"}, {}, exists=lambda p: True,
                          disk_size=len)[1][0]["reason"] == "file sizes differ"

    kept = {"artist": "Various Artists", "ArtistID": "1", "GenreID": "", "Rating": 0,
            "AlbumID": "7"}
    dup = {"artist": "Batu", "ArtistID": "2", "GenreID": "5", "Rating": 4, "AlbumID": "8"}
    assert metadata_fills(kept, dup) == {"GenreID": "5", "Rating": 4, "ArtistID": "2"}
    assert metadata_fills({**dup, "artist": "Someone"}, kept) == {}

    print("relocate checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
