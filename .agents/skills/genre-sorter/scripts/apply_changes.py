#!/usr/bin/env python3
"""Apply a genre sort plan. Thin shim over the shared apply engine; dry run by default.

Usage:
    python3 apply_changes.py sort.json
    python3 apply_changes.py sort.json --apply
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from apply_core import main

MESSAGES = {
    "pending": "{n} track(s) are undecided. Rebuild the plan with build_sort_plan.py:",
    "unset_scope": "{n} track(s) have no scope. Rebuild the plan with build_sort_plan.py:",
}

if __name__ == "__main__":
    raise SystemExit(main(MESSAGES))
