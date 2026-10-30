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

Most startup complexity lives in `src/jparty/ui/widgets/welcome.py`.

Important behaviors there include:

- debounced single-game loading
- advanced "Frankenstein" board composition
- source-board row caching and async loading
- round selection and summary warnings
- local question media preview before game start

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

If you touch DD logic, review both:

- `src/jparty/services/game_loader.py`
- `src/jparty/ui/widgets/welcome.py`

and run the relevant Qt tests in `tests/qt/test_welcome_widget.py`.

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
