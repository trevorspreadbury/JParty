# JParty!

This is based on stuartthomas25's [JParty](https://github.com/stuartthomas25/JParty) and updated to include additional features:
- Physical Buzzers
- Lectern Monitor displays with player's name, score, countdown timer
- Image resolution
- Mixing, matching, and configuring boards from J-archive to create "frankengames"
- Game logging and resumption
- Game summary graphics
- Various code improvements and tests

## Screenshots:

Welcome screen:

<img src="screenshots/welcome_screen.png" height="300"/>

The main game board:

<img src="screenshots/main_board.png" height="300"/>

The host sees the answer on the laptop screen and can adjudicate with the arrow keys:

<img src="screenshots/alex_view.png" height="300"/>

## Documentation

- [Host guide](HOST.md)
- [Game logging and saved state](docs/game-logging.md)
- [Saving question images](docs/saving-question-images.md)

## Features:
- WebSocket buzzer for use on mobile devices 
- Up to 8 players
- Complete access to all games on J-Archive
- Load custom games via a <a href="https://docs.google.com/spreadsheets/d/1JqfJ_OgTstaXTyH5nV3_eN6YXqvZ1RviPmN7OwLhG0U/edit?usp=sharing">simple Google Sheets template</a>
- Scrape games from https://jeopardylabs.com using this <a href="https://chrome.google.com/webstore/detail/jeopardy-labs-to-csv/biijijhfghhckhlkjbonjedmgnkmenlk?hl=en&authuser=0">Google Chrome extension</a>
- Final Jeopardy, Daily Doubles, Double Jeopardy
- Visual Clues
- Host score correction tools with history-backed audit logging

## Visual Clues

JParty supports visual clues! By default, any question with a hyperlink on the J-Archive page will prompt the host to either find an image for the question or determine that no image is needed before displaying the question to contestants. The host uses a search box to either enter a url to an image or a query to Wikimedia to find an appropriate image. 

If you want to prepare clue images before the game, see
[Saving Question Images](docs/saving-question-images.md). For the host-side
workflow for importing and approving image clues, see [HOST.md](HOST.md).


## Requirements
### For running the app (binary)
- macOS, Windows or Linux
- Two monitors
- A device with web access for each player

### For compiling from source code
- Python [>=3.10]
- `uv` is the preferred development workflow
- `conda` is still supported as a fallback if you run into platform-specific Qt/audio issues

## Installation
### Recommended: `uv`
Create a virtual environment and install the project with test dependencies:

```
uv venv
uv sync --extra test
```

Install the Playwright browser runtime if you want to run the browser smoke tests:

```
uv run playwright install chromium
```

### Fallback: `conda`
If `uv` gives you trouble on your machine, especially around audio or Qt, you can still use conda:

```
conda env create -f environment.yml
conda activate JParty
pip install -e .[test]
python -m playwright install chromium
```

## Development
To keep downloads, saved state, logs, and graphs in a predictable repo-local location, create a `.env` file with:

```
DATA_DIR=.jparty-data
```

Run the app with either:

```
uv run jparty
```

or:

```
uv run python -m jparty
```

Useful development commands:

```
uv run pytest tests -q
uv run jparty download 4453 4454
uv run jparty download games.txt
uv run jparty summary --game-state-directory .jparty-data/game_states/4453-20260422T2130
```

If you are using conda instead of `uv`, use the same commands without the `uv run` prefix.

### Generate a Summary Image from Saved State

You can render the same audience summary visual used at the end of the game from a saved game-state directory:

```
jparty summary --game-state-directory /path/to/game_state_dir
```

Arguments:

- `--game-state-directory`: required path to a saved game-state directory containing `general.json`
- `--output-file`: optional output path for the rendered image

If `--output-file` is omitted, JParty writes:

```
<game-state-directory>/summary.png
```

## Score Corrections

For the host-side score correction workflow, see [HOST.md](HOST.md). For how
those corrections are stored in `question_history.jsonl`, see
[Game Logging and Saved State](docs/game-logging.md).

## Build
To build from source, run:

```
uv run pyinstaller -y JParty.spec
```

If you are using conda, run:

```
pyinstaller -y JParty.spec
```

## Game State Tracking

JParty saves per-session metadata and clue history under the configured data
directory, with one folder per saved session. For the file layout, field
definitions, Final Jeopardy logging behavior, and how score edits are recorded,
see [Game Logging and Saved State](docs/game-logging.md).

## FAQ

### How does it work? (technical details)
JParty minimally scrapes the J-Archive (https://j-archive.com) to download a previously-played game and then simulates that on the screen. The game then uses PyQt6 to produce a GUI that simulates the motions of a full _Jeopardy!_ game. A `tornado` web server uses WebSockets to connect to the contestants' smartphones. If that's all gibberish to you, don't worry! You can still play without any technical knowledge.

### Can I create my own custom game?
Yes! JParty supports playing your own custom game via <a target=_blank href="https://docs.google.com/spreadsheets/d/1JqfJ_OgTstaXTyH5nV3_eN6YXqvZ1RviPmN7OwLhG0U/edit?usp=sharing">this simple Google Sheets template</a>. First, make a copy of the template and change the sharing permissions to "Anyone With the Link Can View". Then, copy the Google Sheet file ID and paste it into the "Game ID" box. There are more detailed instructions on the template page. Limitations: there is no way to add pictures (yet!) and you are limited to the traditional 6 categories x 5 dollar values board. 

If you don't want to write your own questions but want to play a topical _Jeopardy!_ game, use this handy <a target=_blank href="https://chrome.google.com/webstore/detail/jeopardy-labs-to-csv/biijijhfghhckhlkjbonjedmgnkmenlk?hl=en&authuser=0">Google Chrome extension to scrape Jeopardy Labs questions</a> (<a href=https://github.com/benf2004/JeopardyLabsToCSV>source code</a>). There are millions of games available on https://jeopardylabs.com that are free to play on a variety of topics. While Jeopardy Labs is a great repository for many topical games & worked great 20 years ago, it lacks in features such as daily doubles, final jeopardy, music/sound effects, and buzzers. 

To use the extension:
1. Make a copy of the <a target=_blank href="https://docs.google.com/spreadsheets/d/1JqfJ_OgTstaXTyH5nV3_eN6YXqvZ1RviPmN7OwLhG0U/edit?usp=sharing">Jparty Google Sheets custom game template</a>
2. Find a game on https://jeopardylabs.com. 
3. Click the extension icon.
4. The questions will download as a csv (spreadsheet) in the style of the template. 
5. Copy the questions into your Google Sheet template
6. Paste the Google Sheet file ID into the "Game ID" box in JParty.

### The QR code doesn't work!
First, make sure you are on the same wireless network as the computer. If this still doesn't work, it may be an issue with allowing local devices on the network. In this case, you can try another network or try tethering both the phones and the computer to another phone.
