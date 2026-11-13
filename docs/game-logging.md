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
  clue (including Final Jeopardy), manual score override, score correction,
  and seat change in the resume lobby

## `general.json`

`general.json` is written when a game starts and again when a saved game is
resumed. It is not updated during play; everything that happens during play
goes into `question_history.jsonl`. A new save looks like this:

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
  "selected_round_indices": [0, 1],
  "board_selections": [
    {
      "game_id": "4453",
      "source_round_index": 1,
      "source_round_label": "Double Jeopardy!",
      "board_type": "standard",
      "row_values": [400, 800, 1200, 1600, 2000],
      "daily_double_count": 2,
      "daily_double_indices": [[1, 3], [4, 2]]
    },
    {
      "game_id": "4453",
      "source_round_index": 2,
      "source_round_label": "Final Jeopardy!",
      "board_type": "final",
      "row_values": []
    }
  ],
  "reveal_answers_after_triple_stumper": false,
  "started_at": 1700000000.0,
  "last_updated": 1700000000.0,
  "history_format": 2,
  "jparty_version": "3.0.0"
}
```

Field notes:

- `game_id`: the J-Archive game id or Google Sheets id being played. For a
  Frankenstein game built from more than one source game, it is
  `frankenstein-<id>-<id>-...`, with one id per board. Resume refuses a save
  without it.
- `players`: the players as they were when the session started. Resume
  refuses a save with no players, and each phone in the resume lobby reclaims
  one of these profiles. Resuming keeps this list as it is, even if the host
  reorders seats in the resume lobby; see
  [Player Numbers](#player-numbers-and-player_renumber)
- `players[].name`: either plain text or the signature image data URL used by
  the scoreboard/lecterns
- `players[].player_number`: the player's number when the session started.
  Their current number is this number with every `player_renumber` line in
  `question_history.jsonl` applied in order
- `selected_round_indices`: the rounds being played, as positions in the game
  that was played, the same numbering as the history's `round_index`. In
  both regular and advanced mode the game is built from `board_selections`,
  so this is `0, 1, 2, ...`, one per board. The example above is a regular
  game with Jeopardy unticked: Double Jeopardy is round `0`. (The welcome
  screen's checkboxes use the source game's round numbers until Start.)
  Older saves recorded the source game's numbers here instead; see
  [Older Saves](#older-saves).
- `board_selections`: one entry per board being played, in play order. Both
  regular and advanced mode write it; it is `[]` only when no board was set
  up. Each entry has:
  - `game_id`: the source game for this board
  - `source_round_index`: the round's index in that source game
  - `source_round_label`: the label shown on the welcome screen, also used in
    the composed game's description
  - `board_type`: `"standard"` or `"final"`. Resume fails if the source round
    is no longer that type.
  - `row_values`: the five clue values for a standard board, top row first;
    `[]` for Final
  - `daily_double_count` and `daily_double_indices` (standard boards only):
    how many Daily Doubles the board has and where they are, as
    `[category_index, row_index]` pairs
- `reveal_answers_after_triple_stumper`: whether the host chose to show the
  correct response after a clue nobody gets right. Resume restores it, and a
  save without it resumes with the option off.
- `started_at`: Unix timestamp for when the game session started. Resume
  keeps it.
- `last_updated`: Unix timestamp for when `general.json` was last written,
  which is the last start or resume
- `history_format`: version of the `question_history.jsonl` format the session
  was started with. `2` is the append-only ledger described below, with
  `score_correction` lines and the score-chain rule. Saves without this field
  were started by an older JParty. Resuming such a save doesn't add the field,
  so a missing value always means "started before format 2".
- `jparty_version`: the JParty version that started the session, kept as-is
  when the game is resumed. This is for diagnosing saves only; between
  releases, dev builds all report the same number.

JParty doesn't act on `history_format` or `jparty_version` yet; resume only
copies them forward. They record where a save came from so that differences
between versions can be found. `last_updated` is never read.

### How resume rebuilds the game

Resume (`Load Saved`) and the `jparty summary` command rebuild the game from
`game_id`, `board_selections` and `selected_round_indices` in the same way, so
the `round_index` values in the history point at the same boards in both:

- `board_selections` present (every regular or advanced game started by this
  version): build the game from `board_selections` and play every board.
  This is the same game that was played, so history `round_index` values are
  positions in `board_selections`.
- No `board_selections` (or `[]`): load the full game `game_id` and play
  `selected_round_indices`. A missing `selected_round_indices` means every
  round. History `round_index` values are the full game's round indices.
- An older regular-mode save, whose `selected_round_indices` are source round
  numbers that skip a round (such as `[1, 2]`), with every board an unchanged
  round of `game_id` (same round, board type, row values and Daily Doubles):
  load the full game `game_id` and play `selected_round_indices`, and
  translate history lines as described in [Older Saves](#older-saves).
  Resuming keeps `general.json` in this older shape, so the history can
  always be read the same way.

The second case also translates history lines when `selected_round_indices`
skips a round, because older versions played only the selected rounds.

Resume reads the history before it fetches the game, so a damaged
`question_history.jsonl` fails before anything is downloaded.

## `question_history.jsonl`

`question_history.jsonl` is append-only: lines are only ever added to the
end during play, and the file is never rewritten. Each line is one JSON
object. There are four line types:

- clue lines, one per completed clue. JParty writes them without a `type`
  field; a line with no `type`, or with `"type": "question"`, is a clue line
- `manual_score_adjustment` lines, one per manual podium override
- `score_correction` lines, one per clue changed in the `Edit Score` dialog
- `player_renumber` lines, written when a resumed game starts after the host
  reordered players in the lobby (see
  [Player Numbers](#player-numbers-and-player_renumber))

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
- `question_number`: running clue number for the session. Resume continues
  from the highest one in the file.
- `round_index`: zero-based index of the round in the game being played; see
  [How resume rebuilds the game](#how-resume-rebuilds-the-game). Resume uses
  `round_index` and `question_index` to mark the clue as played.
- `category`: clue category text
- `value`: clue value at the time it was played; for a Daily Double, the
  wager
- `is_daily_double`: whether the clue was a Daily Double
- `buzz_phases`: response-window breakdown for standard buzzed clues; `[]`
  for Daily Doubles and Final Jeopardy, which have no buzzer race
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
- `is_rebound`: currently always `false`. To find rebound buzzes, use the
  phase's `phase_type` instead.
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

Field notes:

- `player_index`: the player whose podium was clicked
- `score_before`: the player's total before the override
- `score_after`: the total the host entered
- `new_score`: the same number as `score_after`. Lines from older versions
  may have only `new_score`; it is then used as `score_after`.

An override that doesn't change the total writes no line.

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

## Player Numbers and `player_renumber`

Every line identifies players by `player_index`, which is the same number as
`players[].player_number` in `general.json`. In the resume lobby each phone
reclaims a saved profile, and the host can still rearrange the lobby:

- `▲`/`▼` swap two neighboring seats. The two players trade numbers (and
  buzzer keys); everyone else keeps theirs.
- `✕` releases a player's saved slot: the phone returns to the chooser, its
  reconnect token stops working, and another phone can claim the slot. The
  seat keeps its number, so whoever claims it next gets the same number and
  nobody else is renumbered. Start is blocked until every slot is claimed
  again.

When the resumed game starts and any player's seat differs from the number
they were saved under, JParty appends one line before restoring scores:

```json
{"type": "player_renumber", "mapping": {"0": 1, "1": 0, "2": 2}, "timestamp": 1730200000.0}
```

`mapping` maps each saved player number to the player's new number, and is
always a one-to-one reordering. When reading the file, every `player_index`
(and every `player_states` key) on the lines *before* a `player_renumber`
line is translated through its mapping, and then the score chain is checked.
Later resumes add further `player_renumber` lines, which apply on top of the
earlier ones. Saves without a `player_renumber` line read exactly as before.

`general.json` is not changed when seats move: its `players` keep the numbers
the session started with. To find a player's current number, start from
`general.json` and apply every `player_renumber` line in file order (in code,
`current_saved_players`). The history is the only record of seat changes, so
the two files can't disagree: if the app stops right after Start, the next
resume still matches every player to their own score.

If the `player_renumber` line can't be saved (for example, the disk is full),
the host sees "Seat Order Not Saved" and the game stays in the lobby. Unlike
clue lines, the mapping is not kept for a later retry: pressing Start again
builds the whole mapping again, so a kept copy would be written twice, and two
copies of the same mapping cancel each other out.

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

Loading `question_history.jsonl` is all-or-nothing. Every reader (resume,
the score editor, the end-of-game summary and graph, and `jparty summary`)
uses the same strict reader, and stops with the same error if:

- the file is not valid UTF-8 text
- a line is not valid JSON (for example, the last line was cut off while it
  was being written)
- a line is valid JSON but not an object
- a `player_renumber` mapping is not a one-to-one reordering of numbers
- the score chain breaks (a line is missing or was edited)

Blank lines are skipped, and a complete last line without a trailing newline
is accepted. The error looks like this:

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
and flushed. If a write fails partway (for example, the disk is full, or
antivirus or a sync tool briefly locks the file), the file is truncated back
to its previous size and the host sees "Could not save clue history: ...".
JParty keeps the unsaved lines in memory and writes them, in order, in front
of the next line. The file never skips a line, so it always passes the
score-chain check. While lines are waiting, the score editor and end-of-game
summary include them. If they still can't be written when the host closes the
game, the host is told how many are missing. The save still loads, and resumes
from before those clues. JParty never rewrites or reorders existing lines.

## Older Saves

The reader still accepts saves written by earlier versions:

- `general.json` without `history_format` or `jparty_version` (started
  before these were added). Resume leaves them missing.
- `general.json` without `board_selections`: the full game `game_id` is
  loaded and `selected_round_indices` is played (every round if that is
  missing too). Older versions played only those rounds, so when they skip
  one, history lines are translated as described below.
- `general.json` without `reveal_answers_after_triple_stumper`: the option
  is off.
- `general.json` with `history_round_indices_original`: this field is
  ignored. It belonged to a one-time round-index rewrite that has been
  removed, so the history file is never rewritten.
- Clue lines with no `type` field (all clue lines are written this way).
- `manual_score_adjustment` lines with only `new_score`, used as
  `score_after`.
- Score changes without `score_before` or `score_after`: the score chain
  check skips the missing value instead of failing.

### Regular-mode saves with a skipped round

Before this was fixed (issue #93), a regular-mode game with a round unticked
(for example Jeopardy + Final, or Double Jeopardy + Final) saved
`selected_round_indices` as the source game's round numbers (`[0, 2]`,
`[1, 2]`), but was played on a game built from the ticked rounds only. Such
saves come from v3.0.0-rc.1 (which also writes
`history_round_indices_original`) and from later builds before the fix
(which write `history_format` 2). Their history can hold two numberings:

- Lines from the session that started the save count rounds by position in
  the built game: with Jeopardy unticked, Double Jeopardy is `0` and Final is
  `1`.
- Lines written after the save was resumed on one of those versions use the
  source game's numbers (Double Jeopardy is `1`), because those versions
  resumed onto the full source game. v3.0.0-rc.1 also rewrote the earlier
  lines to source numbers when it resumed a save.

`general.json` doesn't say which lines are which, so JParty checks each clue
line: it looks the clue up on both candidate boards and keeps the board whose
clue has the same category (and, as a tie-break, the same value). Lines
whose two readings point at the same board need no check. If both boards fit
equally well, the line is read like the closest earlier line that could be
told apart, or by position if there is none; position lines always come
first, so this only goes wrong when the first line written after an older
resume lands on two boards with the same category and value at the same
spot. J-Archive games almost never repeat a category between rounds. The
history file is never changed; the translation happens each time it is read
(resume, the score editor, the end-of-game summary and `jparty summary`).

These saves resume onto the full source game, as older versions did, and
keep their older `general.json` shape, so new lines use source numbers and
every later read can tell them apart the same way. When the ticked rounds
didn't skip one (all rounds, or Jeopardy + Double Jeopardy), both numberings
agree and nothing needs translating.

For the host-side gameplay flow and score correction UI, see
[HOST.md](../HOST.md).
