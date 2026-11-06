# artwork-finder

Find rekordbox tracks with no album artwork and fill it in. It reuses art you already
have, from the same album, inside the audio files or in the folder, then looks up the
rest on Discogs and the Cover Art Archive. You review a contact sheet before anything
is written.

## Using it

Ask Claude in plain language:

> "which tracks have no artwork?"
> "fill in my missing album art"

Requires macOS. Online lookups use Discogs (with a `DISCOGS_TOKEN` in your shell) and
MusicBrainz. To read art inside files, run `pip3 install mutagen`.

## Safety

- Finding and reviewing never touch the database, so rekordbox can stay open.
- Writing needs rekordbox closed and saves a full database backup first.
- Tracks that already have art are left alone.
- Your audio files stay as they are.
- Artist and album names are sent to Discogs and MusicBrainz for lookups.
