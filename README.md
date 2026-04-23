<img src="resources/icon.png" align="right" height="100"/>

# JParty!
![](https://img.shields.io/github/v/release/stuartthomas25/JParty)
![](https://img.shields.io/github/downloads/stuartthomas25/JParty/total)
![](https://img.shields.io/github/stars/stuartthomas25/JParty?style=social)

_The Jeopardy! Party Game_

Homepage: https://www.stuartthomas.us/jparty/

Ever wanted to play the game show Jeopardy? This Python-based application aims to provide a full _Jeopardy!_ simulator complete with real questions from actual games. This game is perfect for parties and supports 3-8 players plus a host. Typically, _Jeopardy!_ has three contestants which is recommended for the best experience; JParty supports up to 8 players for larger groups (warning: may cause many complaints about buzzer races). For ideal usage, plug a laptop into a TV, setting the laptop as the main monitor. Note that connecting wirelessly using AirPlay works but may cause latency in the buzzer. Instruct contestants to join the same Wifi network as the computer and scan the QR code on the screen. The person with the laptop is the host and runs the game by reading the questions and running the buzzers.

## Download
See <a href="https://github.com/stuartthomas25/JParty/releases">Releases</a> page.

## Screenshots:

Welcome screen:

<img src="screenshots/welcome_screen.png" height="300"/>

The main game board:

<img src="screenshots/main_board.png" height="300"/>

The host sees the answer on the laptop screen and can adjudicate with the arrow keys:

<img src="screenshots/alex_view.png" height="300"/>

## Features:
- WebSocket buzzer for use on mobile devices 
- Up to 8 players
- Complete access to all games on J-Archive
- Load custom games via a <a href="https://docs.google.com/spreadsheets/d/1JqfJ_OgTstaXTyH5nV3_eN6YXqvZ1RviPmN7OwLhG0U/edit?usp=sharing">simple Google Sheets template</a>
- Scrape games from https://jeopardylabs.com using this <a href="https://chrome.google.com/webstore/detail/jeopardy-labs-to-csv/biijijhfghhckhlkjbonjedmgnkmenlk?hl=en&authuser=0">Google Chrome extension</a>
- Final Jeopardy, Daily Doubles, Double Jeopardy
- Visual Clues

## Visual Clues

JParty supports visual clues! By default, any question with a hyperlink on the J-Archive page will prompt the host to either find an image for the question or determine that no image is needed before displaying the question to contestants. The host uses a search box to either enter a url to an image or a query to Wikimedia to find an appropriate image. 

Users also have the option to find images beforehand by going through the following process:
1. Create a folder in the JParty user data directory under `question_media` with the game of interest's J-Archive url id.
2. Then for each question that needs visual clues, add an image with the board number (Jeopardy is '0', Double Jeopardy is '1') the name of the question coordinates separated by a "-". For example the first clue of the game is "0-0-0". Any common image file extension should work (tested on jpeg, jpg, webp, png). For reference the layout of the single jeopardy round is as follows:
<img src="resources/question-media-labelling.png" height="300" />


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
```

If you are using conda instead of `uv`, use the same commands without the `uv run` prefix.

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

JParty writes per-game state to the game-state directory under the configured data directory. Each saved game session gets its own folder named like:

```
<game_id>-<local timestamp>
```

For example:

```
4453-20260422T2130
```

The two main files are:

- `general.json`: high-level session metadata
- `question_history.jsonl`: one JSON object per completed clue, including Final Jeopardy

### `general.json`

`general.json` is rewritten over the course of the game and currently uses this schema:

```json
{
  "game_id": "4453",
  "players": [
    {
      "name": "Alice",
      "player_number": 0
    },
    {
      "name": "data:image/png;base64,...",
      "player_number": 1
    }
  ],
  "selected_round_indices": [0, 1, 2],
  "started_at": 1700000000.0,
  "last_updated": 1700000300.0
}
```

Field notes:

- `game_id`: the J-Archive game id or Google Sheets id currently being played
- `players`: the players in slot order when the state file was written
- `players[].name`: either plain text or the signature image data URL used by the scoreboard/lecterns
- `players[].player_number`: stable player slot index used for saved-game restore and stat tracking
- `selected_round_indices`: the original round indices chosen on the welcome screen
- `started_at`: Unix timestamp for when the game session started
- `last_updated`: Unix timestamp for when the metadata was last saved

### `question_history.jsonl`

`question_history.jsonl` is append-only. Each line is one completed clue. Standard clues and Final Jeopardy use the same top-level shape:

```json
{
  "question_index": [0, [2, 3]],
  "question_number": 17,
  "round_index": 0,
  "category": "SCIENCE",
  "value": 800,
  "is_daily_double": false,
  "buzz_phases": [
    {
      "phase_type": "main",
      "start_time": 1700000100.1,
      "end_time": 1700000103.8,
      "buzz_attempts": [
        {
          "player_index": 1,
          "question_index": [0, [2, 3]],
          "timestamp": 1700000100.9,
          "is_early": false,
          "is_success": true,
          "is_rebound": false,
          "in_timeout": false
        }
      ]
    }
  ],
  "answer_attempts": [
    {
      "player_index": 1,
      "answer_correct": true,
      "timestamp": 1700000102.0,
      "score_before": 1200,
      "score_after": 2000
    }
  ],
  "completed_at": 1700000104.0
}
```

Field notes:

- `question_index`: `[round_index, [category_index, row_index]]`
- `question_number`: running clue number for the session
- `round_index`: zero-based round index in the currently loaded game data
- `category`: clue category text
- `value`: clue value at the time it was played
- `is_daily_double`: whether the clue was a Daily Double
- `buzz_phases`: response-window breakdown for standard buzzed clues
- `answer_attempts`: every judged answer attempt for the clue, in order
- `completed_at`: Unix timestamp for when the clue finished

#### `buzz_phases`

For standard clues, `buzz_phases` records the main response window plus any rebound windows after incorrect responses.

Each phase contains:

- `phase_type`: `"main"` or `"rebound"`
- `start_time`: Unix timestamp
- `end_time`: Unix timestamp
- `buzz_attempts`: every buzz attempt that fell inside that window

Each `buzz_attempts[]` object contains:

- `player_index`: player slot index
- `question_index`: same shape as the entry-level `question_index`
- `timestamp`: Unix timestamp of the buzz
- `is_early`: `true` if the player buzzed before responses opened
- `is_success`: `true` if the buzz won that response window
- `is_rebound`: `true` if the attempt happened during a rebound window
- `in_timeout`: `true` if the player buzzed while locked out of the current response window

#### `answer_attempts`

Each judged response appends an `answer_attempts[]` record:

- `player_index`: player slot index
- `answer_correct`: whether the host ruled the response correct
- `timestamp`: Unix timestamp of the ruling
- `score_before`: player score before the ruling
- `score_after`: player score after the ruling

### How Final Jeopardy Is Logged

Final Jeopardy now writes its own entry to `question_history.jsonl` when the game ends.

It uses the same top-level schema, with these important differences:

- `question_index` points to the Final Jeopardy clue, usually `[final_round_index, [0, 0]]`
- `round_index` is the Final Jeopardy round index in `game.data.rounds`
- `category` is the Final Jeopardy category
- `value` is the Final Jeopardy clue value stored on the question object
- `is_daily_double` is always `false`
- `buzz_phases` is always `[]` because Final Jeopardy has no buzzer race windows
- `answer_attempts` contains one record per player that was judged in Final Jeopardy order

Example Final Jeopardy entry:

```json
{
  "question_index": [2, [0, 0]],
  "question_number": 61,
  "round_index": 2,
  "category": "WORLD CAPITALS",
  "value": -1,
  "is_daily_double": false,
  "buzz_phases": [],
  "answer_attempts": [
    {
      "player_index": 2,
      "answer_correct": false,
      "timestamp": 1700001001.0,
      "score_before": 600,
      "score_after": 500
    },
    {
      "player_index": 1,
      "answer_correct": true,
      "timestamp": 1700001008.0,
      "score_before": 800,
      "score_after": 1100
    }
  ],
  "completed_at": 1700001015.0
}
```

This is the same data the end-of-game summary screen uses for:

- score-over-time graph
- right/wrong counts
- Coryat
- questions buzzed on
- early buzzes
- buzzer race win percentage

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
