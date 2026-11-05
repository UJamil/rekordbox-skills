---
name: file-dedupe
description: Find byte-identical audio files on a drive, compare the folders that hold them side by side, and record which copies to keep on an interactive review page. The scan is read-only and covers files rekordbox doesn't know about. Use this when the user wants to find, compare or clean up duplicate files on disk, for example "what duplicate files are on my drive?", "compare these two folders", "which copies can I delete?" or "free up space from duplicates". For duplicate entries in rekordbox rather than files, use playlist-dedupe or path-relocate.
---

# file-dedupe

Compares locations on a drive so the user can choose which copy of each file stays.

## Workflow

1. **Scan.** Confirms matches with a full hash, and matches each set to the rekordbox
   entry that uses it. rekordbox can stay open.

   ```
   python3 scripts/scan_drive.py /Volumes/<YourDrive>/Music --out drive_duplicates.json
   ```

2. **Build the page**, then publish it as an Artifact with `db` and `user` capabilities.

   ```
   python3 scripts/build_review.py drive_duplicates.json --out drive-diff.html
   ```

3. **Review.** The user decides per folder pair and can override single files. Choices
   save to the `review/decisions` document. Read it with `ArtifactData`.

4. **Apply.** Save the document to a file, dry-run, try a few sets, then do the rest.
   rekordbox must be closed for `--apply`.

   ```
   python3 scripts/apply_choices.py drive_duplicates.json decisions.json
   python3 scripts/apply_choices.py drive_duplicates.json decisions.json --limit 6 --apply
   python3 scripts/apply_choices.py drive_duplicates.json decisions.json --apply
   ```

   Use the same scan for every run, since a new scan won't match the saved choices.
   Sets finished by a trial show as skipped on the next run.

## Guardrails

- Files move to `rekordbox-deleted-files/<stamp>` beside `master.db` and stay there
  until the user deletes that folder. `moved_files.json` and
  `repointed_entries.json` in it list every change.
- The database is backed up and entries are repointed before any file moves, or the
  tracks would go missing.
- A file stays if any comparison kept it. A file override with no choice saves as
  `both`, so `both` with overrides is a hand pick, not a request to keep everything.
- Every file in a set is hashed again before it moves. A changed set is skipped, and
  so is a file locked in Finder: unlocking it is the user's call.
- Treat a review from an older scan as stale: its `scan` id won't match the page.
