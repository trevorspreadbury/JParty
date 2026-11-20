# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- The host screen shows J-Archive's category hints, such as "(Ken: Each
  response ends in -ing.)", in gold italics under the category name (#135).
  They also show under the Final Jeopardy and tiebreaker category until the
  clue is revealed. The audience screen and lecterns don't show them.
- Lecterns can be set up from the keyboard, without the mouse (#46):
  - `/lectern` with no seat asks which lectern it is (press 1 to 6), and
    the browser remembers the answer. Every lectern laptop can open the same
    address.
  - `F` turns full screen on or off, `1` to `6` change the seat without
    reloading, and `H` shows which lectern this is.
  - `R` turns the lectern a quarter turn for monitors mounted on their side,
    so the laptop's display settings can stay as they are. `rotate=` in the
    address does the same, and the page remembers it.
  - The mouse cursor hides itself after two seconds.
- HOST.md has a new "Setting Up Lecterns" section: showing only the external
  monitor, kiosk-mode commands and keeping the laptop awake, for Windows,
  macOS and Ubuntu.
- Clue and tiebreaker clue lines in `question_history.jsonl` have a new
  `responses_open_times` field (#136): the time buzzing unlocked, then one
  more time for each rebound after an incorrect response. Daily Doubles,
  Final Jeopardy and clues that never opened for buzzing log `[]`.
  docs/game-logging.md describes it.

### Changed
- `/lectern` with no `player` no longer opens lectern 1. It opens the seat
  this browser used last, or asks for one. `/lectern?player=0` still opens
  lectern 1.

### Fixed
- Lectern pages no longer need a manual refresh (#46):
  - They keep reconnecting for as long as they are open, through JParty
    restarts, instead of giving up after about 30 seconds with "Connection
    lost". They never reload themselves, so a full-screen lectern stays full
    screen.
  - The server sends each lectern a heartbeat every 3 seconds. A lectern
    that hears nothing for 10 seconds drops the dead connection and
    reconnects.
  - A lectern shows the logo whenever its seat is empty. That includes the
    last seat after a player is removed in the lobby (it used to keep the
    removed player's name), and any lectern 5 seconds after JParty closes.
  - In the resume lobby, a lectern shows the player in its seat. It used to
    show whoever was at that position in the roster, which was wrong after a
    seat was released.
  - The lectern page no longer loads jQuery from the internet, so it starts
    on a laptop with no internet access.
  - On restart, JParty waits up to 3 seconds for port 8080 to free up before
    moving to the next port, where open lecterns would never find it.
- Tiebreaker tossups. When players tie for first, the host can enter a game
  ID (or leave it blank for a random game) and play that game's
  highest-value clues until a tied player answers one correctly. Only the
  tied players can buzz (the other players' phones say they are sitting
  out), scores don't change, and the summary names the winner. Scores are
  locked once the tie is offered. Each tiebreaker clue is saved to `question_history.jsonl` as a new
  `tiebreaker_clue` line (#44).

## [3.0.0] - 2026-11-14

First stable 3.0 release. It contains everything since the May 2026
tournament build (3.0.0-rc.1), plus the fixes from the post-tournament
reviews.

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
- Player names and Final answers are shown on the host exactly as typed.
  Qt used to read them as HTML, so a name like `<img src=...>` made the host
  fetch an image. That froze the game and could leak the host's Windows login
  hash to another computer (#117).
- A second lectern page for the same player now takes over that lectern
  cleanly. The old page is told and stops reconnecting, and the old page
  closing no longer cuts off the new one (#117).

### Added
- `jparty self-check [--report FILE]` checks an installed or packaged app's
  metadata, assets, sound and QR codes without opening a window (#83).
- New saves record `history_format` and `jparty_version` in `general.json`
  (#60).
- While JParty waits for Final Jeopardy wagers, the host can press Enter to
  open the clue right away. Anyone who hasn't wagered is counted as wagering
  $0, so a dead phone or a player who left no longer stalls the game (#108).

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
- `JPARTY_DATA_DIR` now wins over `DATA_DIR` when both are set, and a
  relative data folder in `.env` is found next to the `.env` file instead
  of in whatever folder JParty was started from.

### Fixed
- The triple-stumper sound now plays on a TV or monitor connected by HDMI.
  HDMI audio goes to sleep after a few seconds of silence and takes up to a
  second to wake, which swallowed the whole sound. JParty now keeps the audio
  output awake with a silent loop from Start until Close Game or quitting.
- Clicking a podium in the lobby no longer changes a score. Before Start this
  made a stray save folder and broke the new save, and after Close Game it
  wrote into the previous game's save. Either way that save would no longer
  load. Close Game now also forgets the old save folder.
- The Edit Score dialog now limits a Daily Double wager to the same range as
  the in-game wager prompt: $5 up to the player's score before that clue or
  the board's top value, whichever is larger. Before, it allowed up to 50,000
  for anyone. A board whose clues are all under $5 no longer breaks the wager
  prompt.
- The Edit Score dialog is readable on a light Windows theme. Player names
  were white on a light background, and the clue value ran into the Daily
  Double label. Scrolling over a wager no longer changes it.
- The Edit Score button no longer re-reads the whole clue history file every
  time the host screen updates.
- Final answers are stored on the game's main thread, like buzzes and
  wagers, instead of on the buzzer server's thread (#117).
- When a phone reconnects, its old connection is closed and can no longer
  buzz or answer for the player. If the same player has the buzzer open in
  two tabs (for example after scanning the QR code again), the older tab
  says "Opened in another tab or screen" and offers a Play here button,
  instead of the two tabs reloading each other (#117).
- A garbled message from a phone is logged and ignored. It used to drop the
  phone's connection (#117).
- The lectern page no longer opens a second connection when it is shown
  again while it is still connecting or waiting to reconnect (#117).
- End-of-game buzzer stats are more accurate. A buzz after time runs out on
  a clue no longer counts as an early buzz or as buzzing on that clue. When
  the host rules within about 2 seconds of a buzz, each buzz now counts in
  only one buzzer race, so races are no longer counted twice and a player who
  already answered no longer gets a rebound race. A race is credited to the
  player who won the buzz, even if the host later changes that player's
  ruling to "no answer".
- When the Wayback Machine rate-limits JParty (HTTP 429) or sends a page that
  isn't a game, the game is now loaded straight from J-Archive. Before, every
  game that wasn't already saved failed to load. Error pages are no longer
  kept in memory, and only snapshots J-Archive served successfully are used.
- Google Sheets games no longer lose or shift rows at random, and a line
  break inside a cell is kept. A Sheets error page is reported as an error
  instead of being read as a game.
- The `jparty summary` image is always 1920x1080 and shows every Game Stats
  value. On a smaller or scaled screen the stats wrapped and their numbers
  were cut off, and the graph's "Score" label overlapped a tick label.
- The end-of-game summary shows its "Game Summary" title again, and negative
  amounts read `-$200` instead of `$-200`.
- A slow J-Archive at startup shows the "Cannot connect" message instead of
  the crash dialog.
- A J-Archive clue with no recorded response loads with a blank response
  instead of failing the whole game.
- Closing JParty during a clue or Final now exits at once. A cancelled clue
  timer kept the app, and the buzzer server's port, running for up to 31 s,
  so a quick relaunch moved to the next port (#115).
- The welcome screen now warns about a missing Daily Double in Double
  Jeopardy! even when Jeopardy! is unticked, or when an advanced board uses
  the Double Jeopardy! round on its own (#107).
- Going to 4 or more advanced boards now gives every board the new point
  values in order. Only values the host typed are kept (#107).
- The buzzer server checks what phones send. A name or Final answer that the
  host can't show is rejected instead of stalling the lobby or judging. A
  double-tap on "Play!" no longer adds a ghost player. A wager typed as `1e3`
  is accepted, and an unreadable wager asks the phone again instead of
  stalling Final. An old connection closing after a phone reconnects no
  longer marks that player as disconnected (#110).
- Saving `general.json` no longer empties it first, so a full disk or a
  crash mid-save keeps the previous save loadable. A save briefly locked by
  Windows is retried, and if saving still fails the host is warned instead of
  the error only going to the log (#111).
- Closing the window now makes a last attempt to save clue history that
  failed to save earlier, warns the host if it still cannot, and stops a
  running clue or Final Jeopardy timer (#111).
- A damaged clue history line with a negative round number no longer marks
  or shows a clue from a different round (#111).
- Quitting in the middle of a clue no longer hangs or crashes the app. The
  border flash, key hints and podium lights now run on the GUI thread (#113).
- Clicking No Image Necessary after a failed image lookup no longer crashes
  the app on conda-based Python on Windows. Image lookups now use Windows'
  own TLS instead of OpenSSL (#113).
- Load Saved now reads the save without freezing the window. A save that
  can't be loaded no longer leaves a Start button that does nothing, and the
  screen goes back to the typed game. Importing question media while a game
  is still loading no longer lets Start play the previous game. Random now
  gives up after 10 tries instead of retrying forever, and one network error
  no longer ends the search (#114).
- A player name or Final answer containing "BUZZ" (such as "What is a
  BUZZARD?") is no longer read as a buzz. Such names now join, such answers
  are recorded, and a buzz from a phone that has not joined is ignored
  instead of crashing the socket.
- Starting the same game twice within one minute no longer writes into the
  first save, which made both saves fail to load. The second save gets its
  own folder with a `-2` (`-3`, ...) suffix (#96).
- `jparty --debug` no longer crashes on startup. The buzzer server stopped
  reading the command line, so it no longer rejects JParty's own flags or
  changes the app's logging setup (#97).
- An advanced-mode game with more than one Final Jeopardy board now plays
  every Final in order, with fresh wagers and answers for each. Before, the
  game ended after the first Final. Load Saved resumes at the first Final not
  yet judged (#98).
- Each launch keeps the previous log as `latest.log.1` instead of wiping it,
  so a crash still leaves a log behind. Errors in background threads are now
  logged and show the crash dialog too (#109).
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
- A player who buzzed too early is no longer locked out again when the clue
  reopens after a wrong answer. The early-buzz penalty now only applies to
  the window they buzzed early on (#108).
- Holding a host key down no longer repeats it, so a long press of Space
  can't skip a step, such as jumping past a Final answer reveal (#108).
- Advanced Start can no longer launch a game with a board missing. Pressing
  Start while a board was reloading, for example right after Load Media,
  played only the loaded boards and wrote a save that resumed the wrong
  rounds. Start now turns off while any board reloads and ignores a click
  until every board is ready (#120).
- Changing the number of advanced boards, or turning Advanced off, now stops
  a board's Random search instead of letting it keep fetching games in the
  background (#120).
- After a board's Random gives up, its "Kept game" note stays until that
  board changes, instead of vanishing on the next edit elsewhere (#120).
- A board whose own Daily Doubles share a category now keeps them where they
  are. One of them used to move to a random clue each time the welcome
  screen refreshed, and again on resume (#120).
- Missing-clue warnings now read the same on the regular summary, each
  advanced board and the advanced summary ("WARNING: Missing N questions")
  (#120).

### Removed
- Unused code: the `jparty.services.persistence` re-export module, the
  unused Google Sheets text parser, and an unused in-memory copy of cached
  game pages.
- The crash dialog no longer offers to email a report. It shows the error and
  where the log file is instead (#109).
- The unused matplotlib score graph, the `game_scores` folder and the
  matplotlib dependency. The end-of-game summary is unchanged (#109).
- The end-of-game summary fits a 1080p screen with up to 6 players (more
  than 3 players get smaller cards in two columns), and the original
  contestants' line on the score graph lines up with the clue numbers again.
  The image review text is readable on the black host screen, and editing
  scores no longer cuts a Daily Double wager above 50,000 down to 50,000
  (#112).
- Unused buzzer server code: the `/play` page (its template no longer
  existed), a message cache, an empty cookie secret, and a buzz branch that
  could never run (#117).

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

[Unreleased]: https://github.com/trevorspreadbury/JParty/compare/v3.0.0...dev
[3.0.0]: https://github.com/trevorspreadbury/JParty/compare/v3.0.0-rc.1...v3.0.0
[3.0.0-rc.1]: https://github.com/trevorspreadbury/JParty/releases/tag/v3.0.0-rc.1
