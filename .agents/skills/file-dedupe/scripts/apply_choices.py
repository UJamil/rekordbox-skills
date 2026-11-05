#!/usr/bin/env python3
"""Carry out the choices from the review page: repoint rekordbox entries, then move
the extra copies to the quarantine folder. Nothing is unlinked.

A file stays if any comparison kept it, so a set can never lose its last copy. Every
file in a set is hashed again first, and a set that changed since the scan is skipped.
Dry run unless --apply is given. --limit N takes N sets, half of them repoints.

Usage:
    python3 apply_choices.py drive_duplicates.json decisions.json
    python3 apply_choices.py drive_duplicates.json decisions.json --limit 6 --apply
    python3 apply_choices.py drive_duplicates.json decisions.json --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import stat
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from apply_core import (QUARANTINE_DIRNAME, backup_database, path_key, quarantine_files,
                        rekordbox_running)
from build_review import page_data
from rb_common import get_db
from scan_drive import AUDIO, file_hash


def dir_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def members(pair: dict, s: dict) -> list:
    return [i for i, p in enumerate(s["p"]) if dir_of(p) in (pair["l"], pair["r"])]


def on_side(s: dict, folder: str) -> int:
    return next((i for i, p in enumerate(s["p"]) if dir_of(p) == folder), -1)


def keeper(pair: dict, s: dict, decision: dict):
    """The page's rule: the index that stays in this comparison, or 'both'."""
    override = (decision.get("overrides") or {}).get(s["h"])
    if override is not None:
        return override
    choice = decision.get("choice")
    if choice == "both":
        return "both"
    if choice == "left":
        return on_side(s, pair["l"])
    if choice == "right":
        return on_side(s, pair["r"])
    if choice == "tidy":
        return s["tidy"]
    return s["rb"] if s["rb"] >= 0 else s["tidy"]


def plan_removals(data: dict, decisions: dict) -> tuple[list, int]:
    """One row per set losing a file, and how many files were spared because one
    comparison dropped what another kept."""
    sets = {s["h"]: s for s in data["sets"]}
    kept, keepers, drops = {}, {}, {}
    for pair in data["pairs"]:
        decision = decisions.get(pair["k"])
        if not decision:
            continue
        for h in pair["sets"]:
            s = sets[h]
            k, m = keeper(pair, s, decision), members(pair, s)
            if k == "both" or k not in m:
                kept.setdefault(h, set()).update(m)
                continue
            kept.setdefault(h, set()).add(k)
            keepers.setdefault(h, []).append(k)
            drops.setdefault(h, set()).update(i for i in m if i != k)
    rows, spared = [], 0
    for h, dropped in drops.items():
        gone = dropped - kept[h]
        spared += len(dropped) - len(gone)
        if gone:
            rows.append({"h": h, "size": sets[h]["s"], "paths": sets[h]["p"],
                         "drop": sorted(gone), "target": keepers[h][0]})
    return rows, spared


def pick(rows: list, limit: int, repoints: set) -> list:
    """A trial covers both kinds of set."""
    moved = [r for r in rows if r["h"] in repoints][:(limit + 1) // 2]
    plain = [r for r in rows if r["h"] not in repoints][:limit - len(moved)]
    return moved + plain


def library_path(path: str) -> str:
    """rekordbox stores composed accents, while the drive lists decomposed ones."""
    composed = unicodedata.normalize("NFC", path)
    return composed if os.path.exists(composed) else path


def check_rows(rows: list, root: str, hashes: dict, entries: dict) -> tuple[list, list, list]:
    """Hash each set and match its files to live entries. Returns (moves, repoints, skipped)."""
    moves, repoints, skipped = [], [], []
    for r in rows:
        paths = [root + p for p in r["paths"]]
        target = paths[r["target"]]
        needed = [target] + [paths[i] for i in r["drop"]]
        gone = [p for p in needed if not os.path.exists(p)]
        if gone:
            skipped.append(f"{gone[0]}: not on the drive any more")
            continue
        locked = [p for p in needed[1:] if os.stat(p).st_flags & stat.UF_IMMUTABLE]
        if locked:
            skipped.append(f"{locked[0]}: locked in Finder")
            continue
        if any(file_hash(p) != hashes[r["h"]] for p in needed):
            skipped.append(f"{target}: set changed since the scan")
            continue
        users = [(i, entries.get(path_key(paths[i]), [])) for i in r["drop"]]
        if sum(len(ids) for _, ids in users) and entries.get(path_key(target)):
            skipped.append(f"{target}: kept copy already has its own entry")
            continue
        for i, ids in users:
            repoints += [{"content_id": c, "old": paths[i], "new": library_path(target)}
                         for c in ids]
            moves.append({"content_id": ids[0] if ids else "", "path": paths[i], "size": r["size"]})
    return moves, repoints, skipped


def emptied_folders(moves: list) -> list:
    leaving = {m["path"] for m in moves}
    out = []
    for folder in sorted({os.path.dirname(p) for p in leaving}):
        left = [n for n in os.listdir(folder) if os.path.splitext(n)[1].lower() in AUDIO
                and not n.startswith("._") and os.path.join(folder, n) not in leaving]
        if not left:
            out.append(folder)
    return out


def write_repoints(db, repoints: list, now: datetime) -> None:
    for r in repoints:
        row = db.get_content(ID=r["content_id"])
        row.FolderPath = r["new"]
        row.FileNameL = os.path.basename(r["new"])
        row.updated_at = now
    db.commit()


def verify(db, repoints: list, moved: list) -> list:
    stored = {str(c.ID): c.FolderPath or "" for c in db.get_content()}
    problems = [f"{r['content_id']}: entry not repointed" for r in repoints
                if stored.get(r["content_id"]) != r["new"]]
    problems += [f"{p}: entry has no file" for p in (stored[r["content_id"]] for r in repoints)
                 if not os.path.exists(p)]
    used = {path_key(p) for p in stored.values()}
    problems += [f"{m['from']}: moved but still in use" for m in moved if path_key(m["from"]) in used]
    problems += [f"{m['from']}: still on the drive" for m in moved if os.path.exists(m["from"])]
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply the drive review choices.")
    ap.add_argument("scan")
    ap.add_argument("decisions")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    scan = json.loads(Path(args.scan).read_text(encoding="utf-8"))
    saved = json.loads(Path(args.decisions).read_text(encoding="utf-8"))
    data = page_data(scan)
    if saved.get("scan") != data["scan"]:
        raise SystemExit("These choices come from a different scan. Review the new page first.")
    if args.apply and rekordbox_running():
        raise SystemExit("rekordbox appears to be RUNNING. Close it completely first.")

    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)
    db = get_db()
    entries = {}
    for c in db.get_content():
        entries.setdefault(path_key(c.FolderPath or ""), []).append(str(c.ID))

    root = scan["root"].rstrip("/") + "/"
    hashes = {s["hash"][:12]: s["hash"] for s in scan["sets"]}
    rows, spared = plan_removals(data, saved["decisions"])
    if args.limit:
        used = {r["h"] for r in rows
                if any(entries.get(path_key(root + r["paths"][i])) for i in r["drop"])}
        rows = pick(rows, args.limit, used)
    moves, repoints, skipped = check_rows(rows, root, hashes, entries)

    print(f"Comparisons decided: {len(saved['decisions'])} of {len(data['pairs'])}")
    print(f"Files to quarantine: {len(moves)} ({sum(m['size'] for m in moves) / 1e9:.2f} GB)")
    print(f"Entries to repoint:  {len(repoints)}")
    print(f"Spared, kept by another comparison: {spared}")
    print(f"Skipped: {len(skipped)}")
    for s in skipped[:20]:
        print(f"  {s}")
    empty = emptied_folders(moves)
    print(f"Folders left with no audio: {len(empty)}")
    for f in empty[:40]:
        print(f"  {f[len(root):]}")

    if not args.apply:
        print("\nDRY RUN. Nothing changed. Re-run with --apply.")
        return 0

    db_path, backup = backup_database(db)
    write_repoints(db, repoints, datetime.now())
    dest = db_path.parent / QUARANTINE_DIRNAME / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    moved, errors = quarantine_files(moves, dest)
    problems = verify(get_db(), repoints, moved)
    if moved:
        (dest / "repointed_entries.json").write_text(
            json.dumps(repoints, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRepointed {len(repoints)} entries. Moved {len(moved)} file(s) to {dest}")
    for e in errors + problems:
        print(f"  PROBLEM  {e}")
    if errors or problems:
        print(f"Database backup: {backup}")
        return 1
    print("Verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
