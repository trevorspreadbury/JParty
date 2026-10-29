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
- `question_history.jsonl`: one JSON object per line for each completed
  clue (including Final Jeopardy), manual score override, and score correction

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

`question_history.jsonl` is append-only: lines are only ever added to the
end during play, and the file is never rewritten. There are three line types:

- clue lines (no `type`, or `"type": "question"`), one per completed clue
- `manual_score_adjustment` lines, one per manual podium override
- `score_correction` lines, one per clue changed in the `Edit Score` dialog

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
  appends one `score_correction` line for each clue whose ruling changed.
- Click a player's podium when no clue is active to enter a manual score
  override directly. These overrides are appended to `question_history.jsonl`
  as `manual_score_adjustment` events so resumed games preserve the manual
  total.

The `Edit Score` button is disabled while a clue is active, while selecting a
Daily Double player, or when there is no saved clue history yet.

### `manual_score_adjustment`

```json
{
  "type": "manual_score_adjustment",
  "player_index": 0,
  "timestamp": 1700000500.0,
  "score_before": 1600,
  "score_after": 2000,
  "new_score": 2000
}
```

### `score_correction`

A correction never edits the original clue line. Instead it records the
corrected ruling and the score change it caused at the moment it was made:

```json
{
  "type": "score_correction",
  "question_number": 12,
  "timestamp": 1730200000.0,
  "player_states": {"0": "correct", "1": "no answer"},
  "value": 400,
  "adjustments": [
    {"player_index": 0, "score_before": 1600, "score_after": 2400}
  ]
}
```

Field notes:

- `question_number`: the clue being corrected
- `player_states`: the corrected ruling for every player, keyed by player
  index: `"correct"`, `"incorrect"`, or `"no answer"`
- `value`: the corrected clue value; only present for Daily Doubles, where it
  fixes the wager
- `adjustments`: one record per player whose score changed. Each is the change
  in that clue's effect on the player (for example, wrong -$400 to right +$400
  is +$800), applied to the player's current total

If the same clue is corrected more than once, the latest `score_correction`
line for that `question_number` wins.

## The Score Chain

Every line that changes a score records `score_before` and `score_after`
(on each `answer_attempts[]` record, on manual adjustments, and on each
correction adjustment). Read in file order, each player's `score_before`
must equal their previous `score_after`, and every player starts at `0`. The
file works like a ledger, so a player's current total is simply their last
`score_after`.

Readers use the file in two ways:

- **Totals** (resume and the live scoreboard) take each player's last
  `score_after`.
- **Per-clue views** (Coryat, right/wrong counts, triple stumpers, the score
  editor, and the end-of-game score graph) show the game as it should have
  been: each clue takes its latest correction, and scores are recomputed in
  memory in file order. Uncorrected clues and manual adjustments keep their
  recorded score change, so the recomputed totals always match the ledger
  totals. Nothing is written back to disk.

## Damaged History Files

Loading `question_history.jsonl` is all-or-nothing. If any line is not valid
JSON, the last line has no trailing newline (the file was cut off while it was
being written), or the score chain breaks (a line is missing or was edited),
every reader stops with the same error:

```text
Could not read saved clue history.
File: <path>/question_history.jsonl
Line 3: not valid JSON (unterminated string starting at, column 73).
Fix or delete that line, then try again.
```

- **Load Saved** shows it in the "Saved Game Error" dialog.
- **During play**, the score editor and the end-of-game summary show it in a
  warning dialog. The host can still close the game.
- **`jparty summary`** prints it and exits with code 1.

Fix or delete the reported line by hand, then try again. Deleting a line that
changed a score breaks the chain at the next line for that player, so fix
that line's `score_before` too, or delete the later lines as well.

JParty avoids creating bad lines: each entry is written as one complete line
and flushed. If a write fails partway (for example, the disk is full), the
file is truncated back to its previous size and the host sees "Could not save
clue history: ...". The clue that failed to save is missing from the file, so
the next score change for those players breaks the chain until that line is
restored. The one-time migration of legacy round indices rewrites the file by
writing a temporary copy and swapping it in.

For the host-side gameplay flow and score correction UI, see
[HOST.md](../HOST.md).
