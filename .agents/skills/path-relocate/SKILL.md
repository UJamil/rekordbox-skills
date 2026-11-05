---
name: path-relocate
description: >-
  Repoint rekordbox tracks after a drive or folder rename, when rekordbox's own
  Relocate didn't work or didn't save. Swaps a path prefix in the database for
  tracks whose file exists at the new location, and reports the rest. Use this
  when the user has missing tracks after renaming or moving a drive -- e.g. "all
  my tracks show file not found", "rekordbox still points at my old drive", or
  "relocate didn't stick". Changes the database only, never the audio files.
---

# path-relocate

Fix track paths in bulk with a prefix swap. Try rekordbox's own **File > Manage
Library > Relocate** first. Use this when that fails or doesn't persist.

## Workflow

1. **Dry run** (rekordbox can stay open):

   ```
   python3 scripts/relocate_paths.py --from /Volumes/Old/ --to /Volumes/New/
   ```

   Show the user the counts and `relocate_unresolved.json`.

2. **Trial** on a few tracks, with rekordbox closed:

   ```
   python3 scripts/relocate_paths.py --from /Volumes/Old/ --to /Volumes/New/ --limit 5 --apply
   ```

   Have the user open rekordbox, load those tracks, and confirm that they play and
   that beatgrids, waveforms and cues look right. If Cloud Library Sync is on, have
   them let a sync finish, then re-run the dry run to confirm the paths held.

3. **Full run**, only after the trial passes. Drop `--limit`. The dry run only
   counts tracks still on the old path, so this picks up where the trial left off.

## Kept copies whose file is claimed by a duplicate

rekordbox refuses to relocate an entry to a file another entry owns ("already in
the collection"). After a dedupe, `merge_duplicates.py` handles the clear-cut pairs
and lists the rest in `merge_review.json`:

```
python3 scripts/merge_duplicates.py <dedupe-manifest>                     # dry run
python3 scripts/merge_duplicates.py <dedupe-manifest> --limit 3 --apply   # trial
python3 scripts/merge_duplicates.py <dedupe-manifest> --apply
```

Have the user check the trial in rekordbox before the full run. Never advise
removing the entry that holds the cues: rekordbox deletes its cues, playlist slots,
history and analysis files with it.

For pairs the user picked by hand, pass a JSON list to `--pairs` instead of a manifest.
Each item names `kept` plus `duplicate` (the entry that owns the file) or `new_path`
(a file no entry claims). Unlike a manifest, the duplicate may sit in playlists: its
slots move to the kept entry.

```
python3 scripts/merge_duplicates.py --pairs fixes.json
```

## Two entries for one identical file

Files saved twice, in two folders or under two names in one folder, give two entries
for the same audio. `find_identical.py` confirms matches with a full file hash and
writes pairs. Then `merge_duplicates.py --identical` keeps the entry with cues (then
the most played and most used). The kept entry takes the other's playlist slots,
history and plays, plus any metadata it lacks. The extra audio file stays on disk.

```
python3 scripts/find_identical.py --out pairs.json --csv identical.csv
python3 scripts/merge_duplicates.py --identical pairs.json                     # dry run
python3 scripts/merge_duplicates.py --identical pairs.json --limit 5 --apply   # trial
python3 scripts/merge_duplicates.py --identical pairs.json --apply
```

## What it does and doesn't change

- Only tracks whose old file is gone and whose new file exists are changed.
- Only `FolderPath` changes. ANLZ analysis files keep the old path inside them,
  because pyrekordbox can't read every `.EXT` or `.3EX` file and rewriting them
  risks analysis data. Never swap this for `update_content_path`.
- `--apply` refuses while rekordbox is running, saves a full database backup, then
  verifies every write. A `relocate-log-<stamp>.json` beside `master.db` records
  each old and new path.

To revert, close rekordbox and copy the backup over `master.db`.
