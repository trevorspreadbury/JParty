# AGENTS.md

This file is for coding agents working in this repository. It complements
`README.md`, `CONTRIBUTING.md`, and `HOST.md` with practical implementation
guidance for making safe changes in JParty.

## Project Snapshot

JParty is a desktop Jeopardy-style game with:

- a PyQt6 host/audience UI
- a Tornado-based local buzzer server
- game loading from J-Archive and Google Sheets
- saved game state in repo-local or user-configured data directories

Primary code lives in `src/jparty`:

- `app`: bootstrap, CLI, config, paths, logging
- `services`: remote fetches, parsing, media lookup, caching
- `domain`: game engine, models, persistence, gameplay rules
- `ui`: widgets, windows, presentation logic
- `web`: Tornado app, handlers, controller

Tests live in `tests` and are split into `unit`, `integration`, `qt`, and
`e2e`.

## Recommended Workflow

Use `uv` unless you hit local Qt/audio issues:

```bash
uv sync --extra test
uv run pytest tests -q
uv run pre-commit run --all-files
```

Useful targeted commands:

```bash
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run pytest tests/qt -q
uv run pytest tests/e2e -q
uv run ruff check .
uv run ruff format .
```

If you are working on GUI startup or welcome-screen behavior, prefer running
the smallest relevant Qt subset first.

## Repo Conventions

- Keep changes within the correct layer when possible.
  - Parsing/fetching changes belong in `services`
  - Rules/state changes belong in `domain`
  - Presentation and interaction changes belong in `ui`
- Prefer behavior-level fixes over ad hoc UI-only patches when game rules are
  involved.
- Add or update tests for gameplay logic, parsing rules, persistence, and
  welcome-screen behavior.
- This repo expects docstrings and reasonably explicit code. Match surrounding
  style.
- Let `pre-commit` own final formatting.

## High-Value Areas and Gotchas

### Welcome screen

Most startup complexity lives in `src/jparty/ui/widgets/welcome.py` and the
advanced board editor it embeds, `src/jparty/ui/widgets/advanced_boards.py`.

Important behaviors in `welcome.py` include:

- debounced single-game loading
- round selection and summary warnings
- pushing the chosen board (regular or advanced) into the game for Start
- local question media preview before game start

`AdvancedBoardEditor` in `advanced_boards.py` owns the advanced "Frankenstein"
board rows: source-board row caching and async loading, per-row Random and
media import, and composing the board. It never touches a game object; it
emits `setup_changed` and callers read `current_setup()`. The welcome screen
and the tournament board picker (`ui/widgets/board_setup.py`) both use it, so
change board-slot behavior there, not in either caller. Helpers both the
single-game and advanced setups share (Random's search, warnings, summaries)
live in `src/jparty/ui/board_sources.py`.

If you change advanced options:

- preserve the distinction between original source board data and composed board
  data
- avoid re-fetching/re-parsing source games unnecessarily
- keep warnings scoped to selected boards/rounds only

### Daily Doubles

Daily Double handling now has two important invariants:

- original HTML Daily Doubles are the baseline for each source board
- advanced-mode extra DDs are additive on top of that baseline; reducing below
  the original count keeps only a random subset of the original DDs

DD rules live in `src/jparty/services/game_loader.py`:
`select_advanced_daily_double_indices` picks the baseline to keep for an
advanced board, and `normalize_standard_board_daily_doubles` applies the layout
and draws any extras. `src/jparty/ui/widgets/advanced_boards.py` only calls
them and keeps each row's chosen coordinates stable across reloads.

If you touch DD logic, run `tests/unit/test_game_loading.py` and the relevant
Qt tests in `tests/qt/test_welcome_widget.py` and `tests/qt/test_board_picker.py`.

### Tournament mode

Tournament PRs target the `tournament` integration branch, not `dev`.

Tournament rules are pure functions over plain data in
`src/jparty/domain/tournament*.py`. Widgets call them; they don't decide who
plays, advances, or may resume. Put a new rule in the domain, with a unit
test, even if only one widget needs it today.

Domain modules:

- `roster.py`: player slots and the Google Form sign-ups linked to them
- `tournament.py`: bracket planning (qualifying rounds, wildcards, chase
  games, the optional second round and its byes)
- `tournament_setup.py`: bracket settings, each game's board, and
  `game_key`, which builds every game key
- `tournament_advancement.py`: who advances, chasers, byes, tiebreaker
  ties, who may sit in a game, and conflicts after a fixed result
- `tournament_dropouts.py`: dropout records and how they change each round;
  `tournament_drop_choices.py`: the host's choices for a dropout, and
  applying or undoing one
- `tournament_play.py`: result rows and player introductions;
  `tournament_rankings.py`: rankings; `tournament_saves.py`: finding the
  saved games of half-played tournament games; `tournament_host.py`: the
  `/host` phone page's data
- `tournament_store.py`: reading and writing the tournament folder

Elsewhere: `services/board_prep.py` builds and caches every board ahead of
time; `ui/widgets/tournament_window.py` (with `tournament_editor.py`,
`tournament_roster.py`, `tournament.py`, `tournament_games.py`,
`board_setup.py`, `tournament_prep.py`, and `tournament_rankings.py`) is the
setup window; `ui/widgets/tournament_play.py` and `tournament_dropouts.py`
are the welcome screen's play panel and dropout dialogs; and
`web/handlers.py` with `assets/buzzer/templates/host.html` serves `/host`.
`Game` in `domain/game_engine.py` records a tournament game's results when it
ends.

Each tournament's folder, `<data dir>/tournaments/<name>/`, is a
compatibility contract, like `general.json`. That covers `tournament.json`,
`players.csv`, `results.csv`, `tiebreaks.csv`, `dropouts.csv`,
`voided_results.csv`, and `used_prompts.csv`. The game key format
`"<Round>: <Game>"` (for example `"Quarterfinals: Chase 1"`) is stored in
several of those files and in tournament games' `general.json`. Don't change
file columns or the key format without loading older files, and update
`HOST.md`, which documents the files for hosts.

If you touch tournament rules, run `tests/unit/test_tournament*.py`. For the
play panel and welcome-screen flow, also run `tests/qt/test_welcome_tournament.py`,
`tests/qt/test_tournament_prep.py`, `tests/qt/test_drop_player.py`, and
`tests/integration/test_tournament_results.py`.

### Saved game state

Saved game metadata lives in `general.json`; clue history lives in
`question_history.jsonl`.

If you change startup selection, composed boards, or restore behavior:

- ensure resume still works
- preserve backwards compatibility for existing saved games when practical
- update tests around `general.json` and resume flows

Relevant files:

- `src/jparty/domain/game_engine.py`
- `src/jparty/domain/state.py`
- `tests/unit/test_game_state.py`
- `tests/integration/test_game_resume_and_logging.py`

### Network and startup performance

Some welcome-screen actions are intentionally async because source game loading
can hit network-backed paths. Before adding synchronous work on startup or in
advanced options, check whether it can be done from cached/resolved data
instead.

## Testing Guidance

Choose the narrowest meaningful test slice:

- `tests/unit/test_game_loading.py` for parsing/composition helpers
- `tests/unit/test_game_state.py` for saved-state serialization
- `tests/integration/test_game_resume_and_logging.py` for resume/start flows
- `tests/qt/test_welcome_widget.py` for welcome-screen interactions

When changing welcome or advanced options behavior, at minimum run:

```bash
uv run pytest tests/qt/test_welcome_widget.py -q
```

When changing packaging (`JParty.spec`, bundled assets, or dependencies that
PyInstaller has to bundle), run the opt-in build smoke test. It takes a few
minutes:

```bash
JPARTY_RUN_BUILD_TEST=1 uv run --extra build pytest tests/build -q
```

When changing board composition or persistence, also run:

```bash
uv run pytest tests/unit/test_game_loading.py tests/integration/test_game_resume_and_logging.py -q
```

Finish with:

```bash
uv run pre-commit run --all-files
```

## Agent Expectations

- Read surrounding tests before changing nontrivial behavior.
- Prefer extending existing helpers over duplicating startup/composition logic.
- Do not silently change persistence formats without updating tests and docs.
- If a feature touches both advanced mode and regular mode, verify both flows.
- Keep the host experience responsive; avoid putting network or full reparse
  work on the UI thread unless there is a strong reason.
