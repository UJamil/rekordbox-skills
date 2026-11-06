# rekordbox-skills

A collection of [Claude Code](https://claude.com/claude-code) skills to help
manage a [rekordbox](https://rekordbox.com) library — clone it, point Claude at
it, and ask in plain language.

> macOS / Linux only. Skill **discovery** relies on `.claude/skills/` symlinks
> committed to the repo, which don't resolve on Windows. (The skills' shared Python
> code is plain `sys.path` imports with no symlinks, so that part is portable — but
> Claude Code still won't find the skills on Windows without the discovery symlinks.)

**Disclaimer:** I do not support the use of AI in music making, DJing or any form of the Arts. I do think AI can be used to automate the mundane.

## Available skills

- **[playlist-dedupe](.agents/skills/playlist-dedupe/)** — find and prune
  duplicate tracks in a playlist (or your whole library), keeping the best-quality
  copy. Version-aware and reviews every group with you before changing anything.
- **[upgrade-finder](.agents/skills/upgrade-finder/)** — scan a playlist for
  low-bitrate tracks and find higher-quality copies of the same recording already
  in your library (lossless beats lossy, then higher bitrate). The report is
  read-only, with an optional step to apply the swaps after review.
- **[version-finder](.agents/skills/version-finder/)** — ask "what versions of
  this track do I have?" and get a read-only table of every version, edit, and
  remix already in your library (Version, Format, Bitrate, BPM, Key, and the
  playlists each lives in), one row per file. Version-aware; changes nothing.
- **[file-dedupe](.agents/skills/file-dedupe/)** — find byte-identical audio files
  on a drive, compare the folders side by side, and choose which copies to keep on
  an interactive page. Applying your choices repoints rekordbox entries to the kept
  copies and moves the rest to a quarantine folder for you to delete.
- **[genre-tagger](.agents/skills/genre-tagger/)** — look up missing genres on
  Discogs and MusicBrainz, review the proposals by confidence, and write the ones
  you accept to rekordbox. Can also rename genre labels across the library.
- **[metadata-fixer](.agents/skills/metadata-fixer/)** — find tracks with no artist,
  or with the artist in the title, look up the correct metadata, and write the fixes
  you accept. Also lists duplicates and spelling problems for review.
- **[artwork-finder](.agents/skills/artwork-finder/)** — find tracks with no album
  artwork and fill it in from the same album, the audio files, cover images left in
  folders, Discogs and the Cover Art Archive, after you review a contact sheet.
- **[genre-sorter](.agents/skills/genre-sorter/)** — sort your collection into your
  genre playlists from an editable rules file, with a plan to review first.
- **[path-relocate](.agents/skills/path-relocate/)** — repoint tracks in bulk after
  a drive rename, for when rekordbox's own Relocate doesn't save. Also merges
  entries that point at the same audio, keeping cues, playlists and play history.
- **[audio-converter](.agents/skills/audio-converter/)** — convert audio files
  between WAV, AIFF, and AAC using macOS's built-in `afconvert` (nothing to
  install). Standalone and non-destructive; it won't do lossy→lossless or
  same-format conversions. (MP3 not supported yet.)

Each skill's own README explains what it does and how to use it.

## How it's laid out

- Canonical skill files live under `.agents/skills/<name>/`.
- Helper code shared across skills lives once under `.agents/shared/`
  (`rb_common.py`, `resolve_playlist.py`, `apply_core.py`, and the canonical
  `references/data-model.md`). Each skill's scripts add that directory to
  `sys.path` and import from it — one copy on disk, no symlinks.
- A committed symlink `.claude/skills/<name> -> ../../.agents/skills/<name>` is what
  Claude Code discovers (Claude Code only scans `.claude/skills/`, not `.agents/`).

## Getting started

1. Clone this repo:

   ```sh
   git clone <repo-url> rekordbox-skills
   ```

2. Install [Claude Code](https://claude.com/claude-code). Individual skills may
   have extra prerequisites (e.g. Python packages) — see each skill's README.

3. Launch Claude from inside the repo, giving it access to your rekordbox library:

   ```sh
   cd rekordbox-skills
   claude --add-dir ~/Library/Pioneer/rekordbox
   ```

   - Launching in the repo loads the skills (via the committed `.claude/skills/`
     symlinks — Claude discovers skills from the directory you start in).
   - `--add-dir ~/Library/Pioneer/rekordbox` lets Claude read your library files
     directly, including `master.db` and any backups a skill creates.

4. Ask Claude to do the thing — e.g. *"dedupe my 'Disco' playlist."*

## Contributors
Sean Wilson aka Moon Trip | Disco House Producer & DJ | 
[@moontripdisco](https://www.instagram.com/moontripdisco) | [Spotify](https://open.spotify.com/artist/2LXK0OCfgTMrAcKaauWxag?si=stIynY2uTKanfDoK2BY7Jw) | [SoundCloud](https://soundcloud.com/moontripdisco)
Created this collection and wrote playlist-dedupe, upgrade-finder, version-finder and audio-converter.

[UJamil](https://github.com/UJamil) | Wrote file-dedupe, genre-tagger, genre-sorter, metadata-fixer, path-relocate and artwork-finder.

## Help Using
If you are new to anything related to code, Claude Code / AI, GitHub or tech like this, please send me a dm on instagram (@moontripdisco) or an email: (moontripdisco@gmail.com). I would love to help you!
