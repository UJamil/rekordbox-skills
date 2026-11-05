# genre-sorter

Sort your collection into your genre playlists, using each track's genre, Discogs
styles and release year. The mapping lives in `rules.json`, so you can change it.

## Using it

Run [genre-tagger](../genre-tagger/) first, then ask Claude:

> "sort my library into my genre playlists"

You'll see how many tracks would go in each playlist, and which genres have no
home, before anything is written.

## Safety

- Tracks are only added to playlists, never removed.
- Anything you've already placed in a genre playlist stays put.
- Writing needs rekordbox closed. It saves a full database backup and a snapshot of
  each changed playlist first.
