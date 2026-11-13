# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security
- Phones no longer receive the Final Jeopardy answer before the host reveals
  it (#86).
- The server checks Final Jeopardy wagers (0 up to the player's score) and
  only accepts wagers and answers while their prompt is open. A late Final
  answer is only taken for 3 seconds, from the phone that was connected when
  time ran out (#86).
- Fixed two cross-site scripting holes on the lectern page: the signature
  image is no longer built from raw HTML, and a bad player number in the
  lectern URL is rejected (#86).
- Updated dependencies with known vulnerabilities (Tornado, requests,
  PyInstaller, PyQt6, qrcode and others) (#82).

### Added
- `jparty self-check [--report FILE]` checks an installed or packaged app's
  metadata, assets, sound, QR codes and graphs without opening a window (#83).
- New saves record `history_format` and `jparty_version` in `general.json`
  (#60).

### Changed
- JParty now supports up to 6 players (was 8). A 7th phone is told the game
  is full instead of crashing the join (#87).
- Two monitors are required again by default. Use `jparty --debug` or
  `JPARTY_DEBUG=1` to run on one screen (#75).
- Clue history is append-only: score corrections add `score_correction`
  lines instead of rewriting the file, and a history line that fails to save
  is retried before the next one (#60).
- A damaged `question_history.jsonl` now stops Load Saved, the end-of-game
  summary and `jparty summary` with the file, line number and reason, instead
  of silently resetting scores (#60).
- Regular-mode Start reuses the game already loaded on the welcome screen
  instead of downloading it again (#85).
- All game audio plays through Qt Multimedia; simpleaudio is removed (#78).
- Python 3.11 or newer is required (#82).
- PyInstaller moved to a `build` extra, `requirements.txt` was removed, and
  `environment.yml` installs from `pyproject.toml` (#75, #83).

### Fixed
- Starting the same game twice within one minute no longer writes into the
  first save, which made both saves fail to load. The second save gets its
  own folder with a `-2` (`-3`, ...) suffix.
- The app reports its real version (3.0.0) instead of 2.0.2, including
  packaged builds (#75, #83).
- Moving or removing players in the resume lobby keeps each player's score
  with them. Seat changes are saved as `player_renumber` lines (#61).
- An empty Final resubmission no longer replaces an answer the player
  already gave (#82).
- Fixed app crashes on Windows when a sound finished or was stopped (#78).
- Websocket messages and clue timers run on the right thread, and closing a
  game stops its timers (#76).
- Daily Double wagers are capped at the larger of the player's score and the
  board's top clue value (#87).
- Resuming a save that already finished Final Jeopardy goes to the end of
  the game instead of opening wagers again (#87).
- Board row values are correct when a category is missing a clue, and in
  older games where a Daily Double showed a doubled value (#59, #81).
- Games without Final Jeopardy end instead of crashing, and a resumed game
  on a finished board can move on with Space (#57).
- End-of-game stats and `jparty summary` are correct for games that play
  only some rounds (#74).
- Regular-mode games that skip a round now play Final Jeopardy (for example
  Jeopardy + Final), and resuming them or running `jparty summary` marks
  clues on the right board. `selected_round_indices` now counts the rounds
  that were played (`0, 1, ...`). Saves from v3.0.0-rc.1 or earlier dev
  builds that skipped a round and were already resumed on that older
  version may mark some clues on the wrong board (#93).
- The welcome screen only applies the latest game load, a failed load can't
  start the previous game, and starting a different game never overwrites a
  prepared save (#72).
- Advanced mode: importing media reloads the rows that use that game, failed
  game ids can be retried, changing the board count keeps each board's Daily
  Doubles, the missing Daily Double warning uses the requested count, and a
  row's Random loads in the background and gives up after 10 tries (#88).
- JParty recovers from damaged game caches and question media zips (#77).
- An image clue lookup that fails offline no longer blanks the host board,
  and the lookup no longer freezes the host screen (#51).
- The image review only accepts the image the host is looking at (#73).
- Crash reporting is installed at startup again, so unhandled errors show a
  dialog and reach the log (#50).
- Tests stay offline and catch more real bugs (#84, #89).

## [3.0.0-rc.1] - 2026-05-02

Build used at a tournament in May 2026. Reports its version as `2.0.2`
internally because the version string was not bumped before the event.

### Added
- Frankengames: compose boards from rounds/categories of multiple source games,
  with configurable Daily Doubles (#38, #40).
- Stats tracking (#28) and score correction (#26, #27).
- Question media selection and review workflow before game start (#25).
- Game caching and welcome screen updates (#22, #24).
- Audience participation button and "stumped" sound (#33).
- Saved game state and resume (#9).
- Test suite (#15).

### Changed
- Restructured the codebase into app/services/domain/ui/web layers (#16, #43).
- Games with missing clues can now be played.

### Fixed
- Lectern countdown bug (#32).
- Infinite recursion on Frankengames with media.
- Audio thread handling; added a silent buffer to `stumped.wav`.

[Unreleased]: https://github.com/trevorspreadbury/JParty/compare/v3.0.0-rc.1...dev
[3.0.0-rc.1]: https://github.com/trevorspreadbury/JParty/releases/tag/v3.0.0-rc.1
