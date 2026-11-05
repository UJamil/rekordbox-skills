# path-relocate

Repoint rekordbox tracks after a drive or folder rename, for when rekordbox's own
Relocate doesn't work or doesn't save.

It swaps a path prefix in the database, but only for tracks whose file exists at
the new location. Everything else is listed for you to sort out by hand.

## Using it

Ask Claude in plain language:

> "rekordbox still points at my old drive"
> "relocate didn't stick"

You'll see a dry run first, then a trial on a few tracks to check in rekordbox,
then the full run.

## Safety

- The dry run changes nothing.
- Writing needs rekordbox closed and saves a full database backup first.
- Audio files and analysis files aren't touched. The analysis files keep the old
  path inside them.
