#!/usr/bin/env python3
"""Self-check of the --delete-files planning and quarantine logic (no database)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from apply_core import plan_file_removals, quarantine_files


def manifest(*groups):
    return {"groups": [
        {"decision": decision, "winner_content_id": winner,
         "members": [{"content_id": c} for c in [winner, *losers]]}
        for decision, winner, losers in groups
    ]}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        def touch(name):
            p = root / name
            p.write_bytes(b"audio")
            return str(p)

        keeper = touch("keeper.mp3")
        paths = {"w": keeper, "free": touch("free.mp3")}

        plan = plan_file_removals(manifest(("collapse", "w", ["free"])), paths, {})
        assert [e["content_id"] for e in plan["move"]] == ["free"], plan

        plan = plan_file_removals(manifest(("keep_all", "w", ["free"])), paths, {})
        assert plan == {"move": [], "missing": [], "blocked": []}, plan

        shared = {"w": keeper, "dup": keeper}
        plan = plan_file_removals(manifest(("collapse", "w", ["dup"])), shared, {})
        assert "shared" in plan["blocked"][0]["reason"] and not plan["move"], plan

        cased = {"w": keeper, "dup": keeper.upper()}
        plan = plan_file_removals(manifest(("collapse", "w", ["dup"])), cased, {})
        assert "shared" in plan["blocked"][0]["reason"], plan

        live = {"free": [("Genres / JUNGLE", False)]}
        plan = plan_file_removals(manifest(("collapse", "w", ["free"])), paths, live)
        assert "still in 1" in plan["blocked"][0]["reason"], plan

        backup_pl = {"free": [("Genres / JUNGLE Backup", False)]}
        plan = plan_file_removals(manifest(("collapse", "w", ["free"])), paths, backup_pl)
        assert plan["blocked"] and not plan["move"], plan

        snap = {"free": [("Claude Backups / Genres / JUNGLE", True)]}
        plan = plan_file_removals(manifest(("collapse", "w", ["free"])), paths, snap)
        assert plan["move"][0]["snapshots"] == 1, plan

        gone_keeper = {"w": str(root / "gone.mp3"), "free": paths["free"]}
        plan = plan_file_removals(manifest(("collapse", "w", ["free"])), gone_keeper, {})
        assert "kept copy" in plan["blocked"][0]["reason"], plan

        stale = {"w": keeper, "old": "/Volumes/OldDrive/Music/old.mp3"}
        plan = plan_file_removals(manifest(("collapse", "w", ["old"])), stale, {})
        assert len(plan["missing"]) == 1 and not plan["move"], plan

        chain = manifest(("collapse", "w", ["free"]), ("collapse", "free", ["x"]))
        chained = {**paths, "x": touch("x.mp3")}
        plan = plan_file_removals(chain, chained, {})
        assert any(e["content_id"] == "free" for e in plan["blocked"]), plan

        twice = {"w": keeper, "a": paths["free"], "b": paths["free"]}
        plan = plan_file_removals(manifest(("collapse", "w", ["a", "b"])), twice, {})
        assert len(plan["move"]) == 1, plan

        dest = root / "quarantine"
        moved, errors = quarantine_files(plan["move"], dest)
        assert len(moved) == 1 and not errors, (moved, errors)
        assert not Path(paths["free"]).exists() and Path(moved[0]["to"]).exists()
        assert Path(keeper).exists()
        log = json.loads((dest / "moved_files.json").read_text(encoding="utf-8"))
        assert log[0]["from"] == paths["free"], log

    print("file cleanup checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
