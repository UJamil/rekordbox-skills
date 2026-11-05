---
name: genre-tagger
description: >-
  Look up genres for rekordbox tracks on Discogs and MusicBrainz and write them
  to the rekordbox Genre field after review. Scans tracks with a blank genre by
  default, rates every proposal high, medium or low confidence, and never writes
  until the user has reviewed the proposals. Use this whenever the user wants to
  find, fill in, fix, or scrape genres or metadata for their rekordbox library --
  e.g. "tag my tracks with genres", "half my library has no genre", or "get genre
  info from Discogs". Changes the rekordbox database only, never the audio files.
---

# genre-tagger

Fill in rekordbox's Genre field from online sources, with a review step before
anything is written.

Scripts live in `scripts/`. The genre reaches rekordbox only, so the audio files'
own tags stay as they are.

## Workflow

### 1. Scan (read-only, rekordbox can stay open)

```
python3 scripts/scan_genres.py --out genres.json --limit 20    # try a sample first
python3 scripts/scan_genres.py --out genres.json
```

- Always run a `--limit 20` sample first and show the user the results.
- Add `--exclude-losers <dedupe-manifest>` to skip tracks a dedupe collapsed away.
- `--all` also includes tracks that already have a genre. Only use it if the user
  wants existing genres replaced.
- A full scan takes at least a second per track, so run it in the background.
  Interrupted scans resume from the cache at
  `~/.cache/rekordbox-skills/genre-lookups.json`.

**Discogs needs a token.** The user creates one in their Discogs developer
settings and sets it in their own shell as `DISCOGS_TOKEN`. Never ask them to
paste it into chat. Without it the scan uses MusicBrainz alone, which has far
fewer tags for underground electronic music and can never rate a proposal high.

### 2. Review (edits only the manifest)

```
python3 scripts/review_genres.py genres.json                  # summary
python3 scripts/review_genres.py genres.json --list medium    # inspect a level
python3 scripts/review_genres.py genres.json --accept-high    # accept all high
python3 scripts/review_genres.py genres.json --accept ID ...
python3 scripts/review_genres.py genres.json --set ID "Jungle"
python3 scripts/review_genres.py genres.json --reject ID ...
```

Confidence means:

- **high**: Discogs found the track on its own album, or three or more releases
  by the artist agree.
- **medium**: Discogs found the artist with less agreement.
- **low**: Discogs matched only compilations, or the result came from MusicBrainz,
  whose tags are sparse and can come from a compilation rather than the track.

To check genres the library already has, scan with `--only-existing`. Each track is
marked `agrees` (left alone), `refines` (a catch-all like `Electronic` replaced by
a specific style) or `conflict`. `--accept-high` never accepts a conflict: show
them with `--list conflict` and let the user decide each one.

Show the summary and a sample of high proposals before offering `--accept-high`.
Only `accepted` tracks are written, so anything left pending is simply unchanged.

### 3. Apply

```
python3 scripts/apply_genres.py genres.json            # dry run
python3 scripts/apply_genres.py genres.json --apply    # write
```

`--apply` refuses while rekordbox is running, saves a full database backup to
`rekordbox-db-backups/`, then verifies every write. It reuses existing genre
spellings regardless of case and skips any track whose genre changed since the
scan. `genres_applied_log.json` records each track's previous value.

## Renaming labels

To merge or clean up existing labels across the library, give `rename_genres.py` a
JSON map of `{"old label": "new label"}`. An empty new label clears the genre. Matching
is exact, so `techno` and `Techno` are separate keys. `--apply` refuses while rekordbox
is running and saves a full backup first.

```
python3 scripts/rename_genres.py renames.json            # dry run
python3 scripts/rename_genres.py renames.json --apply    # write
```

## Guardrails

- Never write without the user reviewing the proposals first.
- Never use `--all` unless the user asked to replace existing genres.
- To revert, close rekordbox and copy the backup over `master.db`.
