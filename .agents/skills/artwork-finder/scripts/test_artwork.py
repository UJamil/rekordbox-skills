#!/usr/bin/env python3
"""Self-check of grouping, matching and planning (no database or network)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from apply_artwork import new_image_path, plan
from find_artwork import (folder_cover, group_key, leftover_art, match_leftover, score_album, score_track,
                          sibling_art)


def track(cid, album, path, artist="A"):
    return {"content_id": cid, "album": album, "path": path, "artist": artist, "title": "T"}


def main() -> int:
    a, b = track("1", "Heaven EP", "/m/a/1.mp3"), track("2", "heaven ep", "/m/a/2.mp3")
    assert group_key(a) == group_key(b)
    assert group_key(a) != group_key(track("3", "Heaven EP", "/m/b/1.mp3")), "other folder, other group"
    assert group_key(track("4", "", "/m/a/4.mp3")) != group_key(track("5", "", "/m/a/5.mp3"))
    assert group_key(track("6", "Unknown Album", "/m/a/4.mp3")) != group_key(track("7", "Unknown Album", "/m/a/5.mp3"))

    art = {("heaven ep", "/m/a"): "/PIONEER/x.jpg"}
    assert sibling_art([a], art) == "/PIONEER/x.jpg"
    assert sibling_art([track("8", "Other", "/m/a/1.mp3")], art) == ""
    assert sibling_art([track("9", "", "/m/a/1.mp3")], {("", "/m/a"): "/PIONEER/y.jpg"}) == "", "no album, no sharing"

    hit = {"title": "Skanna (2) - Heaven E.P", "cover_image": "http://x/1.jpg"}
    blank = {"title": "Skanna - Heaven E.P", "cover_image": "http://x/spacer.gif"}
    other = {"title": "Other - Heaven E.P", "cover_image": "http://x/2.jpg"}
    assert score_album([blank, hit], "Skanna", "Heaven E.P", False)["url"].endswith("1.jpg")
    assert score_album([other], "Skanna", "Heaven E.P", False) is None
    assert score_album([other], "Various", "Heaven E.P", True)["confidence"] == "medium"
    assert score_album([hit], "Skanna", "Something Else", False) is None
    assert score_track([other, hit], "Skanna")["confidence"] == "medium"

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "._cover.jpg").write_text("sidecar")
        assert folder_cover(tmp + "/1.mp3") == ""
        (Path(tmp) / "Cover.JPG").write_text("x")
        (Path(tmp) / "back.jpg").write_text("x")
        assert folder_cover(tmp + "/1.mp3").endswith("Cover.JPG")

    with tempfile.TemporaryDirectory() as tmp:
        for name, files in (("Skanna/Heaven EP", ["folder.jpg"]), ("Moby - Go", ["cover.png"]),
                            ("Actress/RIP", ["cover.jpg", "1.flac"])):
            Path(tmp, name).mkdir(parents=True)
            for f in files:
                Path(tmp, name, f).write_text("x")
        left = leftover_art(tmp)
        assert {x["album"] for x in left} == {"Heaven EP", "Go"}, "a folder with audio isn't left over"
        assert match_leftover({"album": "Heaven EP", "artist": "Skanna", "mixed": False}, left)[1] == "high"
        assert match_leftover({"album": "Go", "artist": "Moby", "mixed": False}, left)[1] == "high"
        assert match_leftover({"album": "Go", "artist": "Other", "mixed": False}, left) == ("", "")

    groups = [{"status": "accepted", "tracks": [{"content_id": "1"}, {"content_id": "2"}, {"content_id": "3"}]},
              {"status": "pending", "tracks": [{"content_id": "4"}]}]
    rows = {"1": SimpleNamespace(ImagePath=""), "2": SimpleNamespace(ImagePath="/has.jpg"), "4": SimpleNamespace(ImagePath="")}
    writes, skipped = plan(groups, rows, None)
    assert [i for _, i in writes] == [["1"]] and skipped == 2
    p = new_image_path().split("/")
    assert p[:3] == ["", "PIONEER", "Artwork"] and len(p[3]) == 3 and p[-1] == "artwork.jpg"
    print("artwork checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
