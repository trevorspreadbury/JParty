"""Persist and reconstruct game-state snapshots and analytics data.

This module contains the domain-level helpers used to serialize high-level game
state, append per-question history, and rebuild score or buzz-phase summaries
from saved sessions. The game engine delegates persistence work here to keep
state-shaping logic separate from live gameplay orchestration.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass
from itertools import zip_longest
from pathlib import Path

QUESTION_HISTORY_ENTRY_TYPE = "question"
MANUAL_SCORE_ADJUSTMENT_TYPE = "manual_score_adjustment"
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
    return {
        "game_id": game_id,
        "players": [
            {"name": p.name, "player_number": p.player_number} for p in game.players
        ],
        "selected_round_indices": selected_round_indices,
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
        A list of decoded JSON history entries ordered as stored on disk.
    """
    if not game._game_state_dir:
        game._initialize_game_state_dir()
    if not game._game_state_dir:
        return []
    history_file = game._game_state_dir / "question_history.jsonl"
    if not history_file.exists():
        return []
    entries = []
    try:
        with Path(history_file).open() as file_obj:
            for line in file_obj:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as exc:
        logging.error("Error loading question history: %s", exc)
        return []
    return entries


def reconstruct_score_history(game: object) -> object:
    """Rebuild cumulative score progressions from question history records.

    Args:
        game: Active or resumed ``Game`` instance whose history should be read.

    Returns:
        A mapping from player index to a list of scores by question number.
    """
    entries = load_question_history(game)
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
        game._initialize_game_state_dir()
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
    """
    entries = load_question_history(game)
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
    """
    entries = load_question_history(game)
    entries.sort(key=lambda entry: entry.get("question_number", 0))
    score_history = reconstruct_score_history(game)
    original_score_history = reconstruct_original_score_history(game)
    current_player_map = {player.player_number: player.name for player in game.players}
    all_player_numbers = sorted(current_player_map)

    questions_buzzed_on = {player_number: set() for player_number in all_player_numbers}
    early_buzzes = {player_number: 0 for player_number in all_player_numbers}
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
                    early_buzzes[player_number] = early_buzzes.get(player_number, 0) + 1

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
                early_buzzes=early_buzzes.get(player_number, 0),
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
