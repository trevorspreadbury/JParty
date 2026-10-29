"""Persist and reconstruct game-state snapshots and analytics data.

This module contains the domain-level helpers used to serialize high-level game
state, append per-question history, and rebuild score or buzz-phase summaries
from saved sessions. The game engine delegates persistence work here to keep
state-shaping logic separate from live gameplay orchestration.
"""

import json
import logging
import time
from copy import deepcopy
from dataclasses import asdict, dataclass
from itertools import zip_longest
from pathlib import Path

QUESTION_HISTORY_FILE_NAME = "question_history.jsonl"
QUESTION_HISTORY_ENTRY_TYPE = "question"
MANUAL_SCORE_ADJUSTMENT_TYPE = "manual_score_adjustment"
SCORE_CORRECTION_TYPE = "score_correction"
PLAYER_RENUMBER_TYPE = "player_renumber"
CORRECT_RESULT = "correct"
INCORRECT_RESULT = "incorrect"
NO_ANSWER_RESULT = "no answer"
QUESTION_INDEX_TOP_LEVEL_PART_COUNT = 2
QUESTION_COORD_PART_COUNT = 2
RESULT_ENTRY_PART_COUNT = 2
MIN_RACE_BUZZERS = 2
INITIAL_SCORE = 0
PERCENT_MULTIPLIER = 100
JSON_INDENT_SPACES = 2
PHASE_TIME_PADDING_SECONDS = 1
FIRST_REBOUND_RESPONSE_INDEX = 1
SINGLE_WINNER_COUNT = 1


class HistoryFileError(ValueError):
    """Raised when ``question_history.jsonl`` cannot be trusted.

    Loading clue history is all-or-nothing: every reader (resume, the score
    editor, the end-of-game summary, and the ``jparty summary`` CLI) raises
    this error with the same message instead of silently using partial data.
    The host fixes or removes the reported line by hand.
    """

    def __init__(self, path: object, line_number: int, reason: str) -> None:
        """Store where the history file is broken and why.

        Args:
            path: Path of the history file.
            line_number: One-based line number of the offending line.
            reason: Short description of the problem.
        """
        self.path = Path(path)
        self.line_number = line_number
        self.reason = reason
        super().__init__(
            "\n".join(
                [
                    "Could not read saved clue history.",
                    f"File: {self.path}",
                    f"Line {line_number}: {reason}.",
                    "Fix or delete that line, then try again.",
                ]
            )
        )


@dataclass
class EndGamePlayerStats:
    """Summarize one player's end-of-game performance metrics."""

    player_number: int
    name: str
    final_score: int
    coryat: int
    right_count: int
    wrong_count: int
    questions_buzzed_on: int
    early_buzzes: int
    race_wins: int
    race_opportunities: int

    @property
    def race_win_percentage(self) -> float | None:
        """Return the player's race-win percentage when defined."""
        if self.race_opportunities == INITIAL_SCORE:
            return None
        return (self.race_wins / self.race_opportunities) * PERCENT_MULTIPLIER


@dataclass
class EndGameSeries:
    """Describe one plotted score-history line in the summary graph."""

    player_number: int | None
    name: str
    scores: list[int]
    is_current: bool
    is_original_only: bool


@dataclass
class EndGameGameStats:
    """Summarize whole-game metrics for the summary sidebar card."""

    lead_changes: int
    combined_coryat: int
    buzzer_races: int
    triple_stumpers: int
    victory_summary: str


@dataclass
class EndGameSummary:
    """Bundle the data required to render the audience summary screen."""

    winner_player_numbers: list[int]
    is_tie: bool
    question_count: int
    current_players: list[EndGamePlayerStats]
    game_stats: EndGameGameStats
    current_series: list[EndGameSeries]
    original_series: list[EndGameSeries]


def get_current_game_state(game: object) -> object:
    """Build a serializable summary of the current game session.

    Args:
        game: Active ``Game`` instance providing the session state to capture.

    Returns:
        A dictionary containing the game id, player list, and session
        timestamps.
    """
    game_id = game.current_game_id()
    current_time = time.time()
    selected_round_indices = game.selected_round_indices()
    board_selections = game.board_selection_configs()
    return {
        "game_id": game_id,
        "players": [
            {"name": p.name, "player_number": p.player_number} for p in game.players
        ],
        "selected_round_indices": selected_round_indices,
        "board_selections": board_selections,
        "history_round_indices_original": getattr(
            game, "_history_round_indices_original", False
        ),
        "reveal_answers_after_triple_stumper": (
            game.reveal_answers_after_triple_stumper_enabled()
        ),
        "started_at": game._game_started_at or current_time,
        "last_updated": current_time,
    }


def get_history_entry_type(entry: dict) -> str:
    """Return the normalized type marker for a history record.

    Args:
        entry: Persisted JSONL history entry.

    Returns:
        The entry type, defaulting legacy clue records to ``"question"``.
    """
    if entry.get("type"):
        return entry["type"]
    if entry.get("question_index") is not None:
        return QUESTION_HISTORY_ENTRY_TYPE
    return QUESTION_HISTORY_ENTRY_TYPE


def is_question_history_entry(entry: dict) -> bool:
    """Return whether a history entry represents a clue event.

    Args:
        entry: Persisted JSONL history entry.

    Returns:
        ``True`` when the entry is a normal clue record.
    """
    return get_history_entry_type(entry) == QUESTION_HISTORY_ENTRY_TYPE


def is_manual_score_adjustment(entry: dict) -> bool:
    """Return whether a history entry is a manual score override event.

    Args:
        entry: Persisted JSONL history entry.

    Returns:
        ``True`` when the entry is a manual score adjustment.
    """
    return get_history_entry_type(entry) == MANUAL_SCORE_ADJUSTMENT_TYPE


def is_score_correction(entry: dict) -> bool:
    """Return whether a history entry is an appended score correction.

    Args:
        entry: Persisted JSONL history entry.

    Returns:
        ``True`` when the entry is a ``score_correction`` line.
    """
    return get_history_entry_type(entry) == SCORE_CORRECTION_TYPE


def is_player_renumber(entry: dict) -> bool:
    """Return whether a history entry records a resume-lobby seat change.

    Args:
        entry: Persisted JSONL history entry.

    Returns:
        ``True`` when the entry is a ``player_renumber`` line.
    """
    return get_history_entry_type(entry) == PLAYER_RENUMBER_TYPE


def _remap_player_indices(entry: dict, mapping: dict[int, int]) -> None:
    """Rewrite every player number in one history entry, in place.

    Args:
        entry: History entry to update.
        mapping: Old player number to new player number. Numbers not in the
            mapping are left unchanged.
    """

    def remap(player_index: object) -> object:
        return mapping.get(player_index, player_index)

    if "player_index" in entry:
        entry["player_index"] = remap(entry["player_index"])
    for attempt in entry.get("answer_attempts", []):
        if "player_index" in attempt:
            attempt["player_index"] = remap(attempt["player_index"])
    for phase in entry.get("buzz_phases", []):
        for buzz_attempt in phase.get("buzz_attempts", []):
            if "player_index" in buzz_attempt:
                buzz_attempt["player_index"] = remap(buzz_attempt["player_index"])
    for adjustment in entry.get("adjustments", []):
        if "player_index" in adjustment:
            adjustment["player_index"] = remap(adjustment["player_index"])
    if isinstance(entry.get("player_states"), dict):
        entry["player_states"] = {
            str(remap(int(player_index))): result
            for player_index, result in entry["player_states"].items()
        }


def _player_renumber_mapping(
    path: Path, line_number: int, entry: dict
) -> dict[int, int]:
    """Return a ``player_renumber`` line's mapping, checking it is a reordering.

    Raises:
        HistoryFileError: If the mapping is malformed or not one-to-one.
    """
    try:
        mapping = {
            int(saved): int(current)
            for saved, current in dict(entry.get("mapping", {})).items()
        }
    except (TypeError, ValueError) as exc:
        raise HistoryFileError(
            path, line_number, "player_renumber mapping is not a map of numbers"
        ) from exc
    if set(mapping) != set(mapping.values()):
        raise HistoryFileError(
            path,
            line_number,
            "player_renumber mapping is not a one-to-one reordering of the "
            "player numbers",
        )
    return mapping


def history_score_events(entry: dict) -> list[tuple]:
    """Return the score changes one history line records, in order.

    Args:
        entry: Persisted JSONL history entry.

    Returns:
        ``(player_index, score_before, score_after)`` tuples. Either score may
        be ``None`` for legacy lines that did not record it.
    """
    if is_manual_score_adjustment(entry):
        return [
            (
                entry.get("player_index"),
                entry.get("score_before"),
                entry.get("score_after", entry.get("new_score")),
            )
        ]
    if is_score_correction(entry):
        return [
            (
                adjustment.get("player_index"),
                adjustment.get("score_before"),
                adjustment.get("score_after"),
            )
            for adjustment in entry.get("adjustments", [])
        ]
    if is_question_history_entry(entry):
        return [
            (
                attempt.get("player_index"),
                attempt.get("score_before"),
                attempt.get("score_after"),
            )
            for attempt in entry.get("answer_attempts", [])
        ]
    return []


def read_history_file(
    path: object, apply_player_renumbering: bool = True
) -> list[dict]:
    """Strictly read every line of a ``question_history.jsonl`` file.

    Each ``player_renumber`` line (written when the host reorders seats in
    the resume lobby) is applied to every line before it, so all returned
    entries use the current player numbers.

    The file is a ledger: read in file order, each player's ``score_before``
    must equal the ``score_after`` of their previous score change (or ``0``
    for their first one). A break in that chain means a line is missing or
    was edited.

    Args:
        path: Path of the history file.
        apply_player_renumbering: Whether to translate player numbers through
            ``player_renumber`` lines. Pass ``False`` only to rewrite the file
            as stored; the score chain is not checked then, because it only
            holds once renumbering is applied.

    Returns:
        Decoded history entries in file order, or ``[]`` when the file does
        not exist.

    Raises:
        HistoryFileError: If a line is not valid JSON, the last line has no
            trailing newline (the file was cut off), a ``player_renumber``
            mapping is not a reordering, or the score chain breaks.
    """
    path = Path(path)
    if not path.exists():
        return []
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HistoryFileError(
            path, raw.count(b"\n", 0, exc.start) + 1, "not valid UTF-8 text"
        ) from exc
    lines = text.split("\n")
    entries = []
    for line_offset, line in enumerate(lines):
        line_number = line_offset + 1
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            message = exc.msg[:1].lower() + exc.msg[1:]
            raise HistoryFileError(
                path,
                line_number,
                f"not valid JSON ({message}, column {exc.colno})",
            ) from exc
        if not isinstance(entry, dict):
            raise HistoryFileError(path, line_number, "not a JSON object")
        if line_offset == len(lines) - 1:
            raise HistoryFileError(
                path,
                line_number,
                "no newline at the end of the line, so the file was probably "
                "cut off while it was being written",
            )
        if apply_player_renumbering and is_player_renumber(entry):
            mapping = _player_renumber_mapping(path, line_number, entry)
            for _, earlier_entry in entries:
                if not is_player_renumber(earlier_entry):
                    _remap_player_indices(earlier_entry, mapping)
        entries.append((line_number, entry))
    if apply_player_renumbering:
        _check_score_chain(path, entries)
    return [entry for _, entry in entries]


def _check_score_chain(path: Path, numbered_entries: list[tuple]) -> None:
    """Raise when a player's score does not continue from their last change.

    Args:
        path: History file path, for the error message.
        numbered_entries: ``(line_number, entry)`` pairs in file order.

    Raises:
        HistoryFileError: On the first line whose ``score_before`` does not
            match that player's previous ``score_after``. Every player starts
            at ``0``.
    """
    last_scores = {}
    for line_number, entry in numbered_entries:
        for player_index, score_before, score_after in history_score_events(entry):
            if player_index is None:
                continue
            previous = last_scores.get(player_index, INITIAL_SCORE)
            if score_before is not None and score_before != previous:
                raise HistoryFileError(
                    path,
                    line_number,
                    f"player {player_index}'s score starts at {score_before}, "
                    f"but their previous score was {previous}, so a line may "
                    "be missing or edited",
                )
            if score_after is not None:
                last_scores[player_index] = score_after


def history_score_totals(entries: list[dict]) -> dict[int, int]:
    """Return each player's current total from the history ledger.

    Args:
        entries: History entries in file order.

    Returns:
        Mapping of player index to that player's last recorded
        ``score_after``.
    """
    totals = {}
    for entry in entries:
        for player_index, _, score_after in history_score_events(entry):
            if player_index is not None and score_after is not None:
                totals[player_index] = score_after
    return totals


def clue_player_results(entry: dict) -> dict[int, str]:
    """Return each judged player's ruling for one clue entry.

    Args:
        entry: Clue history entry.

    Returns:
        Mapping of player index to ``"correct"`` or ``"incorrect"``.
    """
    player_results = {}
    for attempt in entry.get("answer_attempts", []):
        player_index = attempt.get("player_index")
        if player_index is None:
            continue
        player_results[player_index] = (
            CORRECT_RESULT if attempt.get("answer_correct") else INCORRECT_RESULT
        )
    return player_results


def clue_attempt_order(entry: dict, player_results: dict) -> list[int]:
    """Return a stable attempt order for a clue after a ruling change.

    Players keep their original attempt order; players newly ruled on are
    appended in player order.

    Args:
        entry: Clue history entry as originally recorded.
        player_results: Mapping of player index to the ruling to apply.

    Returns:
        Ordered player indices that should appear in ``answer_attempts``.
    """
    original_order = [
        attempt.get("player_index")
        for attempt in entry.get("answer_attempts", [])
        if attempt.get("player_index") is not None
    ]
    updated_order = [
        player_index
        for player_index in original_order
        if player_results.get(player_index, NO_ANSWER_RESULT) != NO_ANSWER_RESULT
    ]
    remaining_players = sorted(
        player_index
        for player_index, result in player_results.items()
        if result != NO_ANSWER_RESULT and player_index not in updated_order
    )
    return updated_order + remaining_players


def _attempt_score_change(attempt: dict, value: int) -> int:
    """Return one answer attempt's recorded score change."""
    before, after = attempt.get("score_before"), attempt.get("score_after")
    if before is not None and after is not None:
        return after - before
    return value if attempt.get("answer_correct") else -value


def clue_score_effects(entry: dict) -> dict[int, int]:
    """Return how much one clue entry changed each player's score.

    Args:
        entry: Clue history entry.

    Returns:
        Mapping of player index to the clue's net effect on that player.
    """
    value = int(entry.get("value", 0) or 0)
    effects = {}
    for attempt in entry.get("answer_attempts", []):
        player_index = attempt.get("player_index")
        if player_index is None:
            continue
        effects[player_index] = effects.get(player_index, 0) + _attempt_score_change(
            attempt, value
        )
    return effects


def ruling_score_effect(result: str, value: int) -> int:
    """Return the score change caused by ruling ``result`` on a clue worth ``value``."""
    if result == CORRECT_RESULT:
        return value
    if result == INCORRECT_RESULT:
        return -value
    return 0


def latest_score_corrections(entries: list[dict]) -> dict[int, dict]:
    """Return the most recent ``score_correction`` line for each clue.

    Args:
        entries: History entries in file order.

    Returns:
        Mapping of ``question_number`` to its latest correction line.
    """
    return {
        entry.get("question_number"): entry
        for entry in entries
        if is_score_correction(entry)
    }


def corrected_history_entries(entries: list[dict]) -> list[dict]:
    """Return the history as it should have been, with corrections applied.

    Each clue takes the ruling (and, for Daily Doubles, the value) from its
    latest ``score_correction`` line, the correction lines themselves are
    dropped, and every ``score_before``/``score_after`` is recomputed in file
    order. Uncorrected clues and manual score adjustments keep their recorded
    score change, so the final totals always equal
    :func:`history_score_totals`. ``player_renumber`` lines are dropped too,
    since :func:`read_history_file` has already applied them. Nothing is
    written to disk.

    Args:
        entries: History entries in file order.

    Returns:
        New clue and manual-adjustment entries in file order.
    """
    corrections = latest_score_corrections(entries)
    scores = {}
    corrected_entries = []
    for entry in entries:
        if is_score_correction(entry) or is_player_renumber(entry):
            continue
        corrected_entry = deepcopy(entry)
        corrected_entries.append(corrected_entry)
        if is_manual_score_adjustment(corrected_entry):
            player_index = corrected_entry.get("player_index")
            if player_index is None:
                continue
            score_before = scores.get(player_index, INITIAL_SCORE)
            recorded_after = corrected_entry.get(
                "score_after", corrected_entry.get("new_score", score_before)
            )
            recorded_before = corrected_entry.get("score_before", score_before)
            score_after = score_before + recorded_after - recorded_before
            corrected_entry["score_before"] = score_before
            corrected_entry["score_after"] = score_after
            corrected_entry["new_score"] = score_after
            scores[player_index] = score_after
            continue
        if not is_question_history_entry(corrected_entry):
            continue
        value = int(corrected_entry.get("value", 0) or 0)
        correction = corrections.get(corrected_entry.get("question_number"))
        if correction is None:
            for attempt in corrected_entry.get("answer_attempts", []):
                player_index = attempt.get("player_index")
                if player_index is None:
                    continue
                score_before = scores.get(player_index, INITIAL_SCORE)
                score_after = score_before + _attempt_score_change(attempt, value)
                attempt["score_before"] = score_before
                attempt["score_after"] = score_after
                scores[player_index] = score_after
            continue
        if corrected_entry.get("is_daily_double") and "value" in correction:
            value = int(correction["value"])
            corrected_entry["value"] = value
        player_results = {
            int(player_index): result
            for player_index, result in correction.get("player_states", {}).items()
        }
        attempts_by_player = {
            attempt.get("player_index"): attempt
            for attempt in entry.get("answer_attempts", [])
            if attempt.get("player_index") is not None
        }
        rebuilt_attempts = []
        for player_index in clue_attempt_order(entry, player_results):
            original_attempt = attempts_by_player.get(player_index, {})
            score_before = scores.get(player_index, INITIAL_SCORE)
            score_after = score_before + ruling_score_effect(
                player_results[player_index], value
            )
            rebuilt_attempts.append(
                {
                    **deepcopy(original_attempt),
                    "player_index": player_index,
                    "answer_correct": player_results[player_index] == CORRECT_RESULT,
                    "timestamp": original_attempt.get(
                        "timestamp", correction.get("timestamp")
                    ),
                    "score_before": score_before,
                    "score_after": score_after,
                }
            )
            scores[player_index] = score_after
        corrected_entry["answer_attempts"] = rebuilt_attempts
    return corrected_entries


def save_general_state(game: object) -> None:
    """Write the current high-level game session metadata to disk.

    Args:
        game: Active ``Game`` instance whose metadata should be persisted.

    Returns:
        ``None``.
    """
    if not game._game_state_dir:
        game._initialize_game_state_dir()
    if not game._game_state_dir:
        return
    state = get_current_game_state(game)
    general_file = game._game_state_dir / "general.json"
    try:
        with Path(general_file).open("w") as file_obj:
            json.dump(state, file_obj, indent=JSON_INDENT_SPACES)
    except Exception as exc:
        logging.error("Error saving general state: %s", exc)


def classify_buzz_phases(game: object) -> object:
    """Group recorded buzz attempts into main and rebound response windows.

    Args:
        game: Active ``Game`` instance containing recorded buzz timing data for
            the current clue.

    Returns:
        A list of dictionaries describing each buzz phase and the attempts that
        occurred within it.
    """
    if not game._all_buzz_attempts:
        return []
    if not game._open_responses_times:
        logging.error("No open responses times found after question completed.")
        return []
    current_time = time.time()
    phase_start_times = [game._question_start_time] + game._open_responses_times[
        FIRST_REBOUND_RESPONSE_INDEX:
    ]
    phase_boundaries = []
    for phase_start_time, successful_buzz_time in zip_longest(
        phase_start_times, game._successful_buzz_times, fillvalue=current_time
    ):
        phase_boundaries.append(
            (
                max(phase_start_time - 1, game._question_start_time),
                min(
                    successful_buzz_time + PHASE_TIME_PADDING_SECONDS,
                    current_time,
                ),
            )
        )
    phases = []
    for phase_start_time, phase_end_time in phase_boundaries:
        phases.append(
            {
                "phase_type": "main"
                if phase_start_time == game._question_start_time
                else "rebound",
                "start_time": phase_start_time,
                "end_time": phase_end_time,
                "buzz_attempts": [
                    asdict(buzz)
                    for buzz in game._all_buzz_attempts
                    if phase_start_time <= buzz.timestamp < phase_end_time
                ],
            }
        )
    return phases


def load_question_history(game: object) -> object:
    """Load the saved per-question history entries for a game session.

    Args:
        game: Active or resumed ``Game`` instance with a state directory.

    Returns:
        A list of decoded JSON history entries ordered as stored on disk,
        including any ``score_correction`` lines. Returns ``[]`` only when
        there is no state directory or no history file yet.

    Raises:
        HistoryFileError: If the history file cannot be read; see
            :func:`read_history_file`.
    """
    if not game._game_state_dir:
        return []
    return read_history_file(Path(game._game_state_dir) / QUESTION_HISTORY_FILE_NAME)


def load_corrected_question_history(game: object) -> list[dict]:
    """Load the session history with score corrections applied.

    Args:
        game: Active or resumed ``Game`` instance with a state directory.

    Returns:
        Clue and manual-adjustment entries as they should have been; see
        :func:`corrected_history_entries`.

    Raises:
        HistoryFileError: If the history file cannot be read.
    """
    return corrected_history_entries(load_question_history(game))


def reconstruct_score_history(game: object) -> object:
    """Rebuild cumulative score progressions from question history records.

    Args:
        game: Active or resumed ``Game`` instance whose history should be read.

    Returns:
        A mapping from player index to a list of scores by question number,
        reflecting any score corrections ("as it should have been").

    Raises:
        HistoryFileError: If the history file cannot be read.
    """
    entries = load_corrected_question_history(game)
    if not entries:
        return {}
    all_players = set()
    score_history = {}
    scores = {}
    event_count = 0

    def ensure_player(player_index: int) -> None:
        if player_index in score_history:
            return
        all_players.add(player_index)
        scores[player_index] = INITIAL_SCORE
        score_history[player_index] = [INITIAL_SCORE] * (event_count + 1)

    for entry in entries:
        if is_manual_score_adjustment(entry):
            player_index = entry.get("player_index")
            if player_index is not None:
                ensure_player(player_index)
        for attempt in entry.get("answer_attempts", []):
            player_index = attempt.get("player_index")
            if player_index is not None:
                ensure_player(player_index)

        if is_manual_score_adjustment(entry):
            player_index = entry.get("player_index")
            if player_index is not None:
                scores[player_index] = entry.get(
                    "score_after",
                    entry.get("new_score", scores.get(player_index, INITIAL_SCORE)),
                )
        else:
            for attempt in entry.get("answer_attempts", []):
                player_index = attempt.get("player_index")
                if player_index is not None:
                    scores[player_index] = attempt.get(
                        "score_after", scores.get(player_index, INITIAL_SCORE)
                    )

        event_count += 1
        for player_index in all_players:
            score_history[player_index].append(scores.get(player_index, INITIAL_SCORE))
    return score_history


def load_general_state(game: object) -> object:
    """Load the saved high-level metadata for a game session.

    Args:
        game: Active or resumed ``Game`` instance with a state directory.

    Returns:
        A dictionary of saved general state data, or an empty dictionary when no
        metadata file is available.
    """
    if not game._game_state_dir:
        return {}
    general_file = game._game_state_dir / "general.json"
    if not general_file.exists():
        return {}
    try:
        with Path(general_file).open() as file_obj:
            return json.load(file_obj)
    except Exception as exc:
        logging.error("Error loading general state: %s", exc)
        return {}


def _question_for_history_entry(game: object, entry: object) -> object:
    """Resolve the archived clue referenced by a saved question-history entry.

    Args:
        game: Active or completed ``Game`` instance with loaded rounds.
        entry: Persisted per-question history dictionary.

    Returns:
        The matching ``Question`` object, or ``None`` when the clue cannot be
        located in the currently loaded game data.
    """
    round_index = entry.get("round_index")
    question_index = entry.get("question_index")
    if (
        round_index is None
        or question_index is None
        or len(question_index) < QUESTION_INDEX_TOP_LEVEL_PART_COUNT
        or round_index < 0
        or round_index >= len(getattr(game.data, "rounds", []))
    ):
        return None
    question_coords = question_index[1]
    if (
        not isinstance(question_coords, list | tuple)
        or len(question_coords) != QUESTION_COORD_PART_COUNT
    ):
        return None
    round_data = game.data.rounds[round_index]
    try:
        return round_data.get_question(*question_coords)
    except AttributeError:
        return None


def reconstruct_original_score_history(game: object) -> dict[str, list[int]]:
    """Rebuild archive-contestant score history in actual played clue order.

    Args:
        game: Active or completed ``Game`` instance whose loaded game data and
            saved history should be used.

    Returns:
        Mapping from original contestant name to cumulative scores by played
        question number.

    Raises:
        HistoryFileError: If the history file cannot be read.
    """
    entries = load_corrected_question_history(game)
    if not entries:
        return {}
    entries.sort(key=lambda entry: entry.get("question_number", 0))
    score_history: dict[str, list[int]] = {}
    for entry in entries:
        question_number = int(
            entry.get("question_number", INITIAL_SCORE) or INITIAL_SCORE
        )
        if question_number <= INITIAL_SCORE:
            continue
        clue = _question_for_history_entry(game, entry)
        actual_results = (
            getattr(clue, "actual_results", None) if clue is not None else None
        )
        question_deltas: dict[str, int] = {}
        if isinstance(actual_results, list):
            for result in actual_results:
                if (
                    not isinstance(result, list | tuple)
                    or len(result) != RESULT_ENTRY_PART_COUNT
                ):
                    continue
                player_name, score_delta = result
                if not player_name:
                    continue
                player_name = str(player_name)
                score_history.setdefault(player_name, [INITIAL_SCORE])
                while len(score_history[player_name]) < question_number:
                    score_history[player_name].append(score_history[player_name][-1])
                question_deltas[player_name] = question_deltas.get(
                    player_name, INITIAL_SCORE
                ) + int(score_delta or INITIAL_SCORE)
        for player_name, scores in score_history.items():
            while len(scores) < question_number:
                scores.append(scores[-1])
            scores.append(scores[-1] + question_deltas.get(player_name, INITIAL_SCORE))
    return score_history


def _lead_change_count(
    score_history: dict[int, list[int]], player_numbers: list[int], question_count: int
) -> int:
    """Count how many times the current-game lead changed hands.

    Args:
        score_history: Current-player score history keyed by player number.
        player_numbers: Ordered player numbers participating in the summary.
        question_count: Number of played questions.

    Returns:
        Count of distinct leader-set changes across played questions.
    """
    previous_leaders: set[int] | None = None
    lead_changes = 0
    for question_index in range(1, question_count + 1):
        scores_at_point = {
            player_number: score_history.get(player_number, [0])[
                min(question_index, len(score_history.get(player_number, [0])) - 1)
            ]
            for player_number in player_numbers
        }
        if not scores_at_point:
            continue
        top_score = max(scores_at_point.values())
        leaders = {
            player_number
            for player_number, score in scores_at_point.items()
            if score == top_score
        }
        if previous_leaders is not None and leaders != previous_leaders:
            lead_changes += 1
        previous_leaders = leaders
    return lead_changes


def _victory_summary(
    score_history: dict[int, list[int]],
    winner_player_numbers: list[int],
    question_count: int,
) -> str:
    """Summarize whether the winner came from behind or led wire to wire."""
    if len(winner_player_numbers) != SINGLE_WINNER_COUNT:
        return "Tied finish"
    winner_player_number = winner_player_numbers[INITIAL_SCORE]
    winner_scores = score_history.get(winner_player_number, [INITIAL_SCORE])
    max_trail = INITIAL_SCORE
    wire_to_wire = True
    for question_index in range(1, question_count + 1):
        scores_at_point = []
        for scores in score_history.values():
            scores_at_point.append(scores[min(question_index, len(scores) - 1)])
        if not scores_at_point:
            continue
        winner_score = winner_scores[min(question_index, len(winner_scores) - 1)]
        top_score = max(scores_at_point)
        max_trail = max(max_trail, top_score - winner_score)
        if winner_score != top_score:
            wire_to_wire = False
    if wire_to_wire:
        return "Wire-to-wire victory"
    return f"${max_trail:,} come-from-behind victory"


def build_end_game_summary(game: object) -> EndGameSummary:
    """Compute score and buzzer summary data for the end-game screen.

    Args:
        game: Active or completed ``Game`` instance with persisted history.

    Returns:
        Structured end-game summary data for the audience display.

    Raises:
        HistoryFileError: If the history file cannot be read.
    """
    entries = load_corrected_question_history(game)
    entries.sort(key=lambda entry: entry.get("question_number", 0))
    score_history = reconstruct_score_history(game)
    original_score_history = reconstruct_original_score_history(game)
    current_player_map = {player.player_number: player.name for player in game.players}
    all_player_numbers = sorted(current_player_map)

    questions_buzzed_on = {player_number: set() for player_number in all_player_numbers}
    early_buzz_questions = {
        player_number: set() for player_number in all_player_numbers
    }
    race_wins = {player_number: 0 for player_number in all_player_numbers}
    race_opportunities = {player_number: 0 for player_number in all_player_numbers}
    right_count = {player_number: 0 for player_number in all_player_numbers}
    wrong_count = {player_number: 0 for player_number in all_player_numbers}
    coryat = {player_number: 0 for player_number in all_player_numbers}
    buzzer_races = 0
    triple_stumpers = 0

    for entry in entries:
        question_number = entry.get("question_number")
        buzz_phases = entry.get("buzz_phases", [])
        for phase in buzz_phases:
            for buzz_attempt in phase.get("buzz_attempts", []):
                player_number = buzz_attempt.get("player_index")
                if player_number is None:
                    continue
                questions_buzzed_on.setdefault(player_number, set()).add(
                    question_number
                )
                if buzz_attempt.get("is_early"):
                    early_buzz_questions.setdefault(player_number, set()).add(
                        question_number
                    )

        answer_attempts = entry.get("answer_attempts", [])
        for phase_index, phase in enumerate(buzz_phases):
            if phase_index >= len(answer_attempts):
                break
            race_buzzers = {
                buzz_attempt.get("player_index")
                for buzz_attempt in phase.get("buzz_attempts", [])
                if buzz_attempt.get("player_index") is not None
                and not buzz_attempt.get("in_timeout")
            }
            if len(race_buzzers) < MIN_RACE_BUZZERS:
                continue
            buzzer_races += 1
            for player_number in race_buzzers:
                race_opportunities[player_number] = (
                    race_opportunities.get(player_number, 0) + 1
                )
            winner_player_number = answer_attempts[phase_index].get("player_index")
            if winner_player_number in race_buzzers:
                race_wins[winner_player_number] = (
                    race_wins.get(winner_player_number, 0) + 1
                )
        if (
            entry.get("round_index") is not None
            and entry.get("round_index") < len(getattr(game.data, "rounds", [])) - 1
            and not entry.get("is_daily_double")
            and not any(attempt.get("answer_correct") for attempt in answer_attempts)
        ):
            triple_stumpers += 1

        for attempt in answer_attempts:
            player_number = attempt.get("player_index")
            if player_number is None:
                continue
            if attempt.get("answer_correct"):
                right_count[player_number] = right_count.get(player_number, 0) + 1
            else:
                wrong_count[player_number] = wrong_count.get(player_number, 0) + 1
            if (
                not entry.get("is_daily_double")
                and entry.get("round_index") is not None
                and entry.get("round_index") >= 0
                and entry.get("round_index") < len(getattr(game.data, "rounds", [])) - 1
            ):
                clue_value = int(entry.get("value", 0) or 0)
                if attempt.get("answer_correct"):
                    coryat[player_number] = coryat.get(player_number, 0) + clue_value
                else:
                    coryat[player_number] = coryat.get(player_number, 0) - clue_value

    current_players = []
    for player in game.players:
        player_number = player.player_number
        current_players.append(
            EndGamePlayerStats(
                player_number=player_number,
                name=player.name,
                final_score=player.score,
                coryat=coryat.get(player_number, 0),
                right_count=right_count.get(player_number, 0),
                wrong_count=wrong_count.get(player_number, 0),
                questions_buzzed_on=len(questions_buzzed_on.get(player_number, set())),
                early_buzzes=len(early_buzz_questions.get(player_number, set())),
                race_wins=race_wins.get(player_number, 0),
                race_opportunities=race_opportunities.get(player_number, 0),
            )
        )

    current_series = []
    for player_number in all_player_numbers:
        scores = list(score_history.get(player_number, [0]))
        if not scores:
            scores = [0]
        current_name = current_player_map.get(player_number)
        if current_name is not None:
            current_series.append(
                EndGameSeries(
                    player_number=player_number,
                    name=current_name,
                    scores=scores,
                    is_current=True,
                    is_original_only=False,
                )
            )
    original_series = [
        EndGameSeries(
            player_number=None,
            name=player_name,
            scores=list(scores) if scores else [INITIAL_SCORE],
            is_current=False,
            is_original_only=True,
        )
        for player_name, scores in original_score_history.items()
    ]

    top_score = max((player.score for player in game.players), default=INITIAL_SCORE)
    winner_player_numbers = [
        player.player_number for player in game.players if player.score == top_score
    ]
    question_count = max(
        (entry.get("question_number", INITIAL_SCORE) for entry in entries),
        default=INITIAL_SCORE,
    )
    return EndGameSummary(
        winner_player_numbers=winner_player_numbers,
        is_tie=len(winner_player_numbers) != SINGLE_WINNER_COUNT,
        question_count=question_count,
        current_players=current_players,
        game_stats=EndGameGameStats(
            lead_changes=_lead_change_count(
                score_history, all_player_numbers, question_count
            ),
            combined_coryat=sum(player.coryat for player in current_players),
            buzzer_races=buzzer_races,
            triple_stumpers=triple_stumpers,
            victory_summary=_victory_summary(
                score_history, winner_player_numbers, question_count
            ),
        ),
        current_series=current_series,
        original_series=original_series,
    )
