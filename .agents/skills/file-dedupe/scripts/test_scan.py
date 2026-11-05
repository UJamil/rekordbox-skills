#!/usr/bin/env python3
"""Self-check of folder comparison and name choice (no database or real files)."""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from apply_choices import check_rows, emptied_folders, plan_removals
from apply_core import quarantine_files
from build_review import tidiest
from scan_drive import compare_folders, file_hash


def check_plan() -> None:
    three = {"h": "x", "s": 5, "p": ["a/1.mp3", "b/1.mp3", "c/1.mp3"], "rb": 0, "tidy": 0}
    same = {"h": "y", "s": 5, "p": ["d/2 1.mp3", "d/2.mp3"], "rb": 0, "tidy": 1}
    data = {"sets": [three, same],
            "pairs": [{"k": "ab", "l": "a", "r": "b", "sets": ["x"]},
                      {"k": "ac", "l": "a", "r": "c", "sets": ["x"]},
                      {"k": "bc", "l": "b", "r": "c", "sets": ["x"]},
                      {"k": "dd", "l": "d", "r": "d", "sets": ["y"]}]}
    # Each comparison drops what another keeps: nothing goes.
    rows, spared = plan_removals(data, {"ab": {"choice": "left"}, "ac": {"choice": "right"},
                                        "bc": {"choice": "left"}})
    assert rows == [] and spared == 3, (rows, spared)
    # Keep both protects its files from a third comparison.
    rows, _ = plan_removals(data, {"ab": {"choice": "both"}, "ac": {"choice": "right"}})
    assert rows == [], rows
    rows, _ = plan_removals(data, {"ab": {"choice": "right"}, "dd": {"choice": "tidy"}})
    assert [(r["h"], r["drop"], r["target"]) for r in rows] == [("x", [0], 1), ("y", [0], 1)]
    # A file override beats the comparison's choice.
    rows, _ = plan_removals(data, {"ab": {"choice": "right", "overrides": {"x": 0}}})
    assert [(r["drop"], r["target"]) for r in rows] == [([1], 0)]
    assert plan_removals(data, {"ab": {"choice": "both", "overrides": {"x": 1}}})[0][0]["drop"] == [0]


def check_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = tmp + "/"
        for name, body in (("a.mp3", "same"), ("b.mp3", "same"), ("c.mp3", "edit"), ("d.mp3", "same")):
            Path(root + name).write_text(body)
        digest = file_hash(root + "a.mp3")
        row = {"h": "x", "size": 4, "paths": ["a.mp3", "b.mp3"], "drop": [0], "target": 1}
        moves, repoints, skipped = check_rows([row], root, {"x": digest}, {root.casefold() + "a.mp3": ["7"]})
        assert not skipped and repoints == [{"content_id": "7", "old": root + "a.mp3", "new": root + "b.mp3"}]

        changed = {**row, "paths": ["c.mp3", "b.mp3"]}
        assert check_rows([changed], root, {"x": digest}, {})[2], "changed file must be skipped"
        absent = {**row, "paths": ["gone.mp3", "b.mp3"]}
        assert check_rows([absent], root, {"x": digest}, {})[2], "missing file must be skipped"
        taken = {root.casefold() + "a.mp3": ["7"], root.casefold() + "b.mp3": ["8"]}
        assert check_rows([row], root, {"x": digest}, taken)[2], "two entries must not share a file"

        os.chflags(root + "a.mp3", stat.UF_IMMUTABLE)
        assert "locked" in check_rows([row], root, {"x": digest}, {})[2][0], "locked file must be skipped"
        os.chflags(root + "a.mp3", 0)

        Path(root + "._a.mp3").write_text("sidecar")
        assert emptied_folders([{"path": root + "a.mp3"}, {"path": root + "b.mp3"}, {"path": root + "c.mp3"},
                                {"path": root + "d.mp3"}]) == [tmp], "sidecars are not audio"
        Path(root + "._a.mp3").unlink()

        dest = Path(tmp) / "quarantine"
        moved, errors = quarantine_files(moves, dest)
        assert not errors and not Path(root + "a.mp3").exists() and Path(moved[0]["to"]).read_text() == "same"
        assert (dest / "moved_files.json").exists() and Path(root + "b.mp3").exists()


def main() -> int:
    sets = [{"paths": ["/a/1.mp3", "/b/1.mp3"]}, {"paths": ["/a/2.mp3", "/b/two.mp3"]},
            {"paths": ["/c/3.mp3", "/c/3 1.mp3"]}, {"paths": ["/a/4.mp3", "/b/4.mp3", "/d/4.mp3"]}]
    listing = {"/a": ["/a/1.mp3", "/a/2.mp3", "/a/4.mp3", "/a/only.mp3"],
               "/b": ["/b/1.mp3", "/b/two.mp3", "/b/4.mp3"],
               "/c": ["/c/3.mp3", "/c/3 1.mp3", "/c/x.mp3"], "/d": ["/d/4.mp3"]}
    pairs = {(p["left"], p["right"]): p for p in compare_folders(sets, listing)}
    assert set(pairs) == {("/a", "/b"), ("/a", "/d"), ("/b", "/d"), ("/c", "/c")}, pairs
    ab = pairs["/a", "/b"]
    assert ab["sets"] == [0, 1, 3] and ab["only_left"] == ["/a/only.mp3"] and not ab["only_right"]
    assert pairs["/c", "/c"]["only_left"] == ["/c/x.mp3"]

    assert tidiest(["/a/01 Gypsy Woman (Radio M.aif", "/a/01 Gypsy Woman (Radio Mix).aif"]) == 1
    assert tidiest(["/a/01 Theeves.mp3", "/a/Jurango - Retreat Ites - 01 Theeves.mp3"]) == 0
    assert tidiest(["/a/03 Bins 1.mp3", "/a/03 Bins.mp3"]) == 1
    check_plan()
    check_files()
    print("scan checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
