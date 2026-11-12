# Contributing

This guide is for contributors working on JParty from source. It covers how the
project is organized, how to set up a local development environment, and which
commands to use for linting and testing.

## Project Overview

JParty is a desktop Jeopardy-style game built with PyQt6 for the host and board
displays, plus a Tornado-based local web server for buzzer and lectern clients.
The source code lives under `src/jparty` and is organized by responsibility:

- `src/jparty/app`
  Application bootstrap and shared runtime configuration. This package contains
  the CLI entry point, startup checks, app-level constants, logging setup, and
  path resolution for local data and packaged assets.
- `src/jparty/services`
  Data-loading and integration helpers. These modules fetch and normalize game
  data from J-Archive, Google Sheets, and cached files, and also expose
  lightweight media and persistence-related service interfaces.
- `src/jparty/domain`
  Core gameplay state and rules. This is where the main `Game` engine lives,
  along with domain models, keyboard/timer primitives, and helpers for saving
  and reconstructing game state.
- `src/jparty/ui`
  Desktop presentation layer. This package contains shared styles, reusable
  widgets, and the full-screen host/audience windows built on PyQt6.
- `src/jparty/web`
  Local network buzzer server. These modules define the Tornado application,
  websocket handlers, and controller that connect player phones and lectern
  displays back to the game engine.

Other useful top-level directories:

- `tests`
  Automated test suite, grouped into `unit`, `integration`, `qt`, and `e2e`.
- `resources`
  Project artwork and supporting assets used outside the packaged source tree.
- `docs`
  Additional project documentation.
- `.jparty-data`
  Repo-local runtime data directory when `DATA_DIR=.jparty-data` is configured.

## Development Setup

### Requirements

- Python 3.11 or newer
- `uv` for the recommended workflow
- Two monitors if you want to run the full GUI manually (or use
  [single-monitor debug mode](#single-monitor-debug-mode))

### Recommended setup with `uv`

Create a virtual environment and install the project with test dependencies:

```bash
uv venv
uv sync --extra test
```

If you plan to run the browser smoke tests, also install the Playwright browser:

```bash
uv run playwright install chromium
```

### Fallback setup with `conda`

If you run into platform-specific Qt or audio issues with `uv`, the repo also
supports a conda environment:

```bash
conda env create -f environment.yml
conda activate JParty
pip install -e .[test]
python -m playwright install chromium
```

## Local Runtime Configuration

For development, it is helpful to keep saved games, logs, graphs, and runtime
state inside the repository rather than in a user profile directory. Create a
`.env` file with:

```env
DATA_DIR=.jparty-data
```

## Running the App

Start the application with:

```bash
uv run jparty
```

You can also run the package entry point directly:

```bash
uv run python -m jparty
```

Useful helper commands:

```bash
uv run jparty download 4453 4454
uv run jparty download games.txt
```

If you are using conda instead of `uv`, use the same commands without the
`uv run` prefix.

### Single-monitor debug mode

JParty normally refuses to start unless two displays are attached, so the host
window (which shows the answers) stays off the audience screen. For development
on one monitor, turn on debug mode with either:

```bash
JPARTY_DEBUG=1 uv run jparty
uv run jparty --debug
```

`JPARTY_DEBUG` accepts `1`, `true`, `yes` or `on`, and can also go in your
`.env` file. Debug mode is off by default; don't enable it for real games.

## Linting and Formatting

This project uses Ruff and pre-commit.

Run Ruff directly:

```bash
uv run ruff check .
uv run ruff format .
```

Run the full pre-commit suite:

```bash
uv run pre-commit run --all-files
```

The pre-commit config currently includes:

- trailing whitespace cleanup
- end-of-file fixes
- YAML validation
- large file checks
- `ruff --fix`
- `ruff format`

## Testing

The test suite is configured in `pyproject.toml` under
`[tool.pytest.ini_options]` and grouped with markers:

- `unit`: pure parsing and state reconstruction tests
- `integration`: integration tests using fakes and monkeypatching
- `qt`: PyQt widget tests
- `e2e`: end-to-end and smoke tests

Run the full suite:

```bash
uv run pytest tests -q
```

Run a subset by directory:

```bash
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run pytest tests/qt -q
uv run pytest tests/e2e -q
```

Run by marker:

```bash
uv run pytest -m unit
uv run pytest -m integration
uv run pytest -m qt
uv run pytest -m e2e
```

Notes:

- The Qt tests require the PyQt test dependencies from `.[test]`.
- The browser smoke tests under `tests/e2e` require Playwright's Chromium
  runtime to be installed first.

## Packaging

PyInstaller is in the optional `build` extra, not the runtime dependencies,
so running the app doesn't install it. Build the desktop app with:

```bash
uv run --extra build pyinstaller -y JParty.spec
```

If using conda:

```bash
pip install -e .[build]
pyinstaller -y JParty.spec
```

Then check the packaged app without opening any windows. It has no console,
so it writes its results to a file and returns a non-zero exit code on failure:

```bash
dist/JParty.exe self-check --report self-check.txt
```

On macOS the app is `dist/JParty.app/Contents/MacOS/JParty`.

`self-check` checks the package version, bundled assets, the game sounds
(through Qt Multimedia), the buzzer QR code, and chart rendering. It also
works on a source install: `uv run jparty self-check`.

To build and check the app in one step, run the opt-in build smoke test. It
builds into a temporary folder and takes a few minutes:

```bash
JPARTY_RUN_BUILD_TEST=1 uv run --extra build pytest tests/build -q
```

The version shown on the welcome screen and in builds comes from
`src/jparty/_version.py`; `pyproject.toml` reads it from there, so bump it in
that one place.

## Contribution Notes

- Keep changes scoped to the layer you are working in when possible.
- Prefer adding or updating tests when changing gameplay logic, parsing, or web
  message flow.
- The repo enforces docstrings and type annotations more aggressively than many
  projects, so it is worth running Ruff before opening a PR.
