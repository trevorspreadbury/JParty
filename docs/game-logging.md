# Game Logging and Saved State

This guide documents how JParty saves per-game state, how clue history is
logged, and how score corrections are preserved for resumed games.

## Session Folders

JParty writes per-game state to the game-state directory under the configured
data directory. Each saved game session gets its own folder named like:

```text
<game_id>-<local timestamp>
```

For example:

```text
4453-20260422T2130
```

The two main files are:

- `general.json`: high-level session metadata
- `question_history.jsonl`: one JSON object per completed clue, including
  Final Jeopardy

## `general.json`

`general.json` is rewritten over the course of the game and currently uses this
schema:

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
- `players[].name`: either plain text or the signature image data URL used by
  the scoreboard/lecterns
- `players[].player_number`: stable player slot index used for saved-game
  restore and stat tracking
- `selected_round_indices`: the original round indices chosen on the welcome
  screen
- `started_at`: Unix timestamp for when the game session started
- `last_updated`: Unix timestamp for when the metadata was last saved

## `question_history.jsonl`

`question_history.jsonl` is append-only. Each line is one completed clue.
Standard clues and Final Jeopardy use the same top-level shape:

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

### `buzz_phases`

For standard clues, `buzz_phases` records the main response window plus any
rebound windows after incorrect responses.

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
- `in_timeout`: `true` if the player buzzed while locked out of the current
  response window

### `answer_attempts`

Each judged response appends an `answer_attempts[]` record:

- `player_index`: player slot index
- `answer_correct`: whether the host ruled the response correct
- `timestamp`: Unix timestamp of the ruling
- `score_before`: player score before the ruling
- `score_after`: player score after the ruling

## How Final Jeopardy Is Logged

Final Jeopardy writes its own entry to `question_history.jsonl` when the game
ends.

It uses the same top-level schema, with these important differences:

- `question_index` points to the Final Jeopardy clue, usually
  `[final_round_index, [0, 0]]`
- `round_index` is the Final Jeopardy round index in `game.data.rounds`
- `category` is the Final Jeopardy category
- `value` is the Final Jeopardy clue value stored on the question object
- `is_daily_double` is always `false`
- `buzz_phases` is always `[]` because Final Jeopardy has no buzzer race
  windows
- `answer_attempts` contains one record per player that was judged in Final
  Jeopardy order

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

## Score Corrections and Logging

Hosts can correct scoring in two ways once a game is in progress:

- Click `Edit Score` on the host scoreboard to review the previous five played
  clues. Each clue shows its category, value, correct response, and one
  selector per player with `no answer`, `correct`, and `incorrect`. Daily
  Doubles also expose an editable clue value so the wager can be fixed. Saving
  rewrites the relevant clue entries in `question_history.jsonl` and
  recalculates every downstream score.
- Click a player's podium when no clue is active to enter a manual score
  override directly. These overrides are appended to `question_history.jsonl`
  as `manual_score_adjustment` events so resumed games preserve the manual
  total.

The `Edit Score` button is disabled while a clue is active, while selecting a
Daily Double player, or when there is no saved clue history yet.

For the host-side gameplay flow and score correction UI, see
[HOST.md](../HOST.md).
