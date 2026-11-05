# file-dedupe

Finds byte-identical audio files on a drive and compares the folders that hold them.

## What it does

- Scans a folder tree, including files rekordbox doesn't know about.
- Shows each folder pair as a diff: files in both, and files only on one side.
- Lists files saved twice in one folder under two names.
- Marks the copy rekordbox uses, with its cues and playlist count.
- Records which copies you want to keep.
- Repoints rekordbox entries to the kept copies and moves the rest to a quarantine folder. Nothing is deleted until you empty that folder.

## Prerequisites

`pip3 install pyrekordbox`, and the drive connected.

## Usage

```sh
python3 scripts/scan_drive.py /Volumes/<YourDrive>/Music --out drive_duplicates.json
python3 scripts/build_review.py drive_duplicates.json --out drive-diff.html
```

Ask your agent to publish the page. Opened as a plain file, it saves choices in that
browser only and offers a button to copy them.

## Safety

The scan and the page are read-only. Hashing reads every candidate file in full, so
large drives take a few minutes.
