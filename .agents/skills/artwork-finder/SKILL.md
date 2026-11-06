---
name: artwork-finder
description: >-
  Find rekordbox tracks with no album artwork and fill it in after review. Reuses art
  from the same album, art inside the audio files and cover images in the folder,
  then looks up the rest on Discogs and the Cover Art Archive. Shows a contact sheet
  to review before anything is written. Use this when the user wants to check, find,
  or fix missing album art, e.g. "which tracks have no artwork?", "find my missing
  covers", or "fill in the blank album art". Changes the rekordbox database and its
  artwork folder only, never the audio files.
---

# artwork-finder

Scripts live in `scripts/`. Art goes into rekordbox's own artwork folder, so the audio
files stay as they are. Needs macOS (`sips` resizes the images).

## Workflow

1. **Find** (read-only for the library, rekordbox can stay open). Tracks are grouped
   by album and folder, so one cover serves a whole album:

   ```
   python3 scripts/find_artwork.py --out art.json --limit 20    # try a sample first
   python3 scripts/find_artwork.py --out art.json --lookup --art-root <music folder>
   ```

   `--art-root` also matches covers left in folders that no longer hold audio, by
   album and artist name.

   Without `--lookup` only local sources are used. With it, a full scan takes a few
   seconds per album, so run it in the background. Discogs needs `DISCOGS_TOKEN` in
   the environment; never ask for it in chat. Reading art inside files needs
   `pip3 install mutagen`; without it that source is skipped.

2. **Review** (edits only the manifest):

   ```
   python3 scripts/review_artwork.py art.json
   python3 scripts/review_artwork.py art.json --sheet art.html
   python3 scripts/review_artwork.py art.json --list medium
   python3 scripts/review_artwork.py art.json --accept-high
   python3 scripts/review_artwork.py art.json --accept ID ...
   python3 scripts/review_artwork.py art.json --reject ID ...
   ```

   Always show the contact sheet before accepting. Only `accepted` groups are written.

   - **high**: art from the same album in rekordbox, inside the file or in the folder,
     or a Discogs release matching both artist and album.
   - **medium**: an artist-only Discogs match, a compilation matched on its title, or
     the Cover Art Archive. Check these by eye. A compilation series or a reissue can
     show the wrong sleeve.

3. **Apply**. Try a few first and have the user check them in rekordbox:

   ```
   python3 scripts/apply_artwork.py art.json
   python3 scripts/apply_artwork.py art.json --apply --limit 3
   python3 scripts/apply_artwork.py art.json --apply
   ```

   `--apply` refuses while rekordbox is running and saves a full backup first. It
   writes `artwork.jpg`, `artwork_m.jpg` and `artwork_s.jpg` at 600, 240 and 80 pixels,
   sets the track's image path and skips any track that gained art since the scan.
   `artwork-log-<stamp>.json` beside the manifest lists every change.

## Guardrails

- Never write without the user seeing the contact sheet.
- A track that already has art is never changed.
- To revert, close rekordbox and copy the backup over `master.db`. The added image
  folders are harmless, and the log lists them.
