---
name: genre-sorter
description: >-
  Sort rekordbox tracks into the user's genre playlists using each track's genre,
  Discogs styles and release year. Rules live in an editable rules.json. Shows a
  plan first and writes through the same backup and snapshot engine as
  playlist-dedupe. Use this when the user wants to sort, file, or organize their
  collection into genre playlists -- e.g. "sort my library into my genre
  playlists", "fill my Genres folder", or "put my techno in the right crates".
---

# genre-sorter

Add tracks to playlists under a folder (default `Genres`) based on `rules.json`.
Run genre-tagger first: a track with no useful genre can't be placed.

## Workflow

1. **Plan** (read-only, rekordbox can stay open):

   ```
   python3 scripts/build_sort_plan.py --out sort.json --report sort.csv \
       --styles <genre-tagger manifest> --exclude-losers <dedupe manifest>
   ```

   Show the user the per-playlist counts and the unplaced genres. If the rules name
   playlists that don't exist, ask, then add `--create-playlists` (rekordbox closed).

2. **Adjust** `rules.json` with the user and rebuild. Rules run top to bottom, so
   put specific playlists first. `genre_only` stops a rule matching on Discogs
   styles, for styles too common to mean much.

3. **Dry run, then apply**, with rekordbox closed for the apply:

   ```
   python3 scripts/apply_changes.py sort.json
   python3 scripts/apply_changes.py sort.json --apply
   ```

## Guardrails

- Tracks only get added. Nothing is removed from any playlist.
- A track already in any playlist under the folder stays where the user put it.
- Each track goes in one playlist.
- Dedupe duplicates and tracks with no file are skipped.
- Years come from rekordbox and can be reissue dates, so decade splits have errors.
- Taste-based playlists, like Detroit or Vox crates, can't be filled from tags.
  Leave them to the user.
