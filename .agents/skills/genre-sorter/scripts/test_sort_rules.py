#!/usr/bin/env python3
"""Self-check of the placement rules (no database)."""
from __future__ import annotations

import json

from build_sort_plan import RULES, place


def main() -> int:
    config = json.loads(RULES.read_text(encoding="utf-8"))
    assert place("Techno", [], 1995, config) == ("TECHNO - 90s", "genre")
    assert place("Techno", [], 2015, config) == ("TECHNO", "genre")
    assert place("Techno", [], 0, config) == ("TECHNO", "genre")
    assert place("Deep House", [], 1996, config) == ("HOUSE - 90s", "genre")
    assert place("House", [], 2010, config) == ("HOUSE", "genre")
    assert place("EBM", [], 1988, config) == ("EBM", "genre")
    assert place("Ambient Techno", [], 2001, config) == ("TECHNO - AMBIENT", "genre")
    assert place("", ["Jungle", "Techno"], 1995, config) == ("JUNGLE", "style")
    assert place("Electronica", ["House"], 2012, config) == ("HOUSE", "style")
    assert place("", ["Ambient"], 2012, config) == (None, None)
    assert place("Post-Punk", ["Techno"], 2012, config) == ("POST-PUNK", "genre")
    assert place("Hip Hop", [], 1995, config) == ("HIPHOP - 90s", "genre")
    assert place("Hip Hop", [], 2012, config) == ("HIPHOP", "genre")
    assert place("", ["Post-Punk"], 2012, config) == (None, None)
    print("sort rule checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
