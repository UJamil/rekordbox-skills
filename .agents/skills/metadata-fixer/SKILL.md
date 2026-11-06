---
name: metadata-fixer
description: >-
  Find rekordbox tracks with no artist, where only the title has text, which
  usually means a file with no tags, like "slipmatt - breaking free". Parses the
  filename and folders, optionally looks up the correct metadata on Discogs and
  MusicBrainz, and writes accepted fixes after review. Use this when the user
  wants to find or fix untagged tracks or missing metadata -- e.g. "find tracks
  with no artist", "fix my untagged mp3s". Changes the rekordbox database only,
  never the audio files.
---

# metadata-fixer

Scripts live in `scripts/`. Only the rekordbox database changes, so the audio files'
own tags stay as they are.

## Workflow

1. **Find** (read-only, rekordbox can stay open). Add `--lookup` to check online:

   ```
   python3 scripts/find_missing_metadata.py --out metadata.json
   python3 scripts/find_missing_metadata.py --out metadata.json --lookup
   ```

   Discogs needs `DISCOGS_TOKEN` in the environment. Never ask for the token in chat.

2. **Review** (edits only the manifest):

   ```
   python3 scripts/review_metadata.py metadata.json
   python3 scripts/review_metadata.py metadata.json --list high
   python3 scripts/review_metadata.py metadata.json --accept-high
   python3 scripts/review_metadata.py metadata.json --set ID "Artist" "Title"
   ```

   - **high**: Discogs found the artist on the track's own album, or on 2+ releases.
   - **medium**: one Discogs release, or a MusicBrainz match.
   - **filename**: parsed only, not confirmed online. Accept these one at a time.
   - **none**: nothing to go on.

   Show a sample before offering `--accept-high`. Sample packs and stems often turn
   up here and are best rejected.

3. **Apply**:

   ```
   python3 scripts/apply_metadata.py metadata.json
   python3 scripts/apply_metadata.py metadata.json --apply
   ```

   `--apply` refuses while rekordbox is running and saves a full backup first. It
   sets artist and title, fills album and year only if blank, and skips any track
   that gained an artist since the scan. A `metadata-log-<stamp>.json` beside
   `master.db` records old values.

After fixing tracks, run genre-tagger to fill in their genres.

## Artists left in titles

`find_artist_titles.py` finds titles like `Artist - Track`. It removes the artist when
it repeats the artist field. When the artist field holds a label or series name, list
that name in `--labels` and the real artist moves out of the title. Uncertain rows
start as `pending` and are skipped until reviewed.

```
python3 scripts/find_artist_titles.py --labels labels.txt --out titles.json --csv titles.csv
python3 scripts/apply_metadata.py titles.json            # dry run
python3 scripts/apply_metadata.py titles.json --apply
```

## Duplicates and spelling

`find_name_issues.py` is read-only. It lists tracks that look like the same recording,
artist, album and genre names spelled more than one way, and titles with junk in them.
Tracks with no artist can't be compared, so fix those first.

```
python3 scripts/find_name_issues.py --out issues.json --csv issues.csv
```

