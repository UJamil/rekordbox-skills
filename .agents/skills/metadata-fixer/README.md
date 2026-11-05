# metadata-fixer

Find rekordbox tracks with no artist, where only the title has text. That usually
means a file with no tags, like `slipmatt - breaking free`. It parses the filename
and folders, can look up the correct metadata online, and writes what you accept.

## Using it

Ask Claude in plain language:

> "find tracks with no artist"
> "fix my untagged mp3s"

Online lookups use Discogs (with a `DISCOGS_TOKEN` in your shell) and MusicBrainz.

## Safety

- Finding and reviewing never touch the database, so rekordbox can stay open.
- Writing needs rekordbox closed and saves a full database backup first.
- Your audio files' own tags stay as they are.
- Track titles and artists are sent to Discogs and MusicBrainz for lookups.
