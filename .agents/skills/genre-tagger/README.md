# genre-tagger

Look up genres for your rekordbox tracks on Discogs and MusicBrainz, review the
proposals, and write the ones you accept to rekordbox's Genre field. By default it
only touches tracks with no genre.

## Prerequisites

- rekordbox 6 and Python 3 with `pyrekordbox`.
- Recommended: a Discogs personal access token, set in your shell:

  ```sh
  export DISCOGS_TOKEN=your-token
  ```

  Without one, the scan uses MusicBrainz alone, which covers underground
  electronic music much less well.

## Using it

Ask Claude in plain language:

> "tag my tracks with genres"
> "half my library has no genre, can you fill it in?"

Claude tries a small sample, runs the full scan, walks you through the proposals,
and writes only what you accept.

## Safety

- Scanning and review never touch the database, so rekordbox can stay open.
- Writing needs rekordbox closed and saves a full database backup first.
- Tracks you've edited since the scan are skipped.
- Only the rekordbox database changes. Your audio files' own tags stay as they are.
- Track artist and title are sent to Discogs and MusicBrainz for the lookups.
