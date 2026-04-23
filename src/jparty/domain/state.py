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
        if self.race_opportunities == 0:
            return None
        return (self.race_wins / self.race_opportunities) * 100


@dataclass
class EndGameSeries:
    """Describe one plotted score-history line in the summary graph."""

    player_number: int
    name: str
    scores: list[int]
    is_current: bool
    is_original_only: bool


@dataclass
class EndGameSummary:
    """Bundle the data required to render the audience summary screen."""

    winner_player_numbers: list[int]
    is_tie: bool
    question_count: int
    current_players: list[EndGamePlayerStats]
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
            json.dump(state, file_obj, indent=2)
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
    phase_start_times = [game._question_start_time] + game._open_responses_times[1:]
    phase_boundaries = []
    for phase_start_time, successful_buzz_time in zip_longest(
        phase_start_times, game._successful_buzz_times, fillvalue=current_time
    ):
        phase_boundaries.append(
            (
                max(phase_start_time - 1, game._question_start_time),
                min(successful_buzz_time + 1, current_time),
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
    entries.sort(key=lambda entry: entry.get("question_number", 0))
    all_players = set()
    score_history = {}
    for entry in entries:
        for attempt in entry.get("answer_attempts", []):
            player_index = attempt.get("player_index")
            if player_index is not None:
                all_players.add(player_index)
                score_history.setdefault(player_index, [0])
    for entry in entries:
        question_num = entry.get("question_number", 0)
        if question_num == 0:
            continue
        question_scores = {}
        for attempt in entry.get("answer_attempts", []):
            player_index = attempt.get("player_index")
            score_after = attempt.get("score_after", 0)
            if player_index is not None:
                question_scores[player_index] = score_after
        for player_index in all_players:
            while len(score_history[player_index]) < question_num:
                score_history[player_index].append(score_history[player_index][-1])
            if player_index in question_scores:
                score_after = question_scores[player_index]
                if len(score_history[player_index]) == question_num:
                    score_history[player_index].append(score_after)
                else:
                    score_history[player_index][question_num] = score_after
            else:
                last_score = score_history[player_index][-1]
                if len(score_history[player_index]) == question_num:
                    score_history[player_index].append(last_score)
                else:
                    score_history[player_index][question_num] = last_score
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


def build_end_game_summary(game: object) -> EndGameSummary:
    """Compute score and buzzer summary data for the end-game screen.

    Args:
        game: Active or completed ``Game`` instance with persisted history.

    Returns:
        Structured end-game summary data for the audience display.
    """
    entries = load_question_history(game)
    entries.sort(key=lambda entry: entry.get("question_number", 0))
    general_state = load_general_state(game)
    score_history = reconstruct_score_history(game)

    original_player_map = {
        int(player.get("player_number")): player.get(
            "name", f"Player {player.get('player_number')}"
        )
        for player in general_state.get("players", [])
        if player.get("player_number") is not None
    }
    current_player_map = {player.player_number: player.name for player in game.players}
    all_player_numbers = sorted(set(original_player_map) | set(current_player_map))

    questions_buzzed_on = {player_number: set() for player_number in all_player_numbers}
    early_buzzes = {player_number: 0 for player_number in all_player_numbers}
    race_wins = {player_number: 0 for player_number in all_player_numbers}
    race_opportunities = {player_number: 0 for player_number in all_player_numbers}
    right_count = {player_number: 0 for player_number in all_player_numbers}
    wrong_count = {player_number: 0 for player_number in all_player_numbers}
    coryat = {player_number: 0 for player_number in all_player_numbers}

    for entry in entries:
        question_number = entry.get("question_number")
        buzz_phases = entry.get("buzz_phases", [])
        for phase in buzz_phases:
            for buzz_attempt in phase.get("buzz_attempts", []):
                player_number = buzz_attempt.get("player_index")
                if player_number is None:
                    continue
                questions_buzzed_on.setdefault(player_number, set()).add(question_number)
                if buzz_attempt.get("is_early"):
                    early_buzzes[player_number] = early_buzzes.get(player_number, 0) + 1

        main_phase = next(
            (phase for phase in buzz_phases if phase.get("phase_type") == "main"),
            None,
        )
        answer_attempts = entry.get("answer_attempts", [])
        if main_phase and answer_attempts:
            race_buzzers = {
                buzz_attempt.get("player_index")
                for buzz_attempt in main_phase.get("buzz_attempts", [])
                if buzz_attempt.get("player_index") is not None
                and not buzz_attempt.get("is_early")
                and not buzz_attempt.get("in_timeout")
            }
            if len(race_buzzers) >= 2:
                for player_number in race_buzzers:
                    race_opportunities[player_number] = (
                        race_opportunities.get(player_number, 0) + 1
                    )
                first_response = min(
                    answer_attempts,
                    key=lambda attempt: attempt.get("timestamp", float("inf")),
                )
                winner_player_number = first_response.get("player_index")
                if winner_player_number in race_buzzers:
                    race_wins[winner_player_number] = (
                        race_wins.get(winner_player_number, 0) + 1
                    )

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
    original_series = []
    for player_number in all_player_numbers:
        scores = list(score_history.get(player_number, [0]))
        if not scores:
            scores = [0]
        current_name = current_player_map.get(player_number)
        original_name = original_player_map.get(player_number)
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
        if original_name is not None and original_name != current_name:
            original_series.append(
                EndGameSeries(
                    player_number=player_number,
                    name=original_name,
                    scores=scores,
                    is_current=False,
                    is_original_only=True,
                )
            )

    top_score = max((player.score for player in game.players), default=0)
    winner_player_numbers = [
        player.player_number for player in game.players if player.score == top_score
    ]
    return EndGameSummary(
        winner_player_numbers=winner_player_numbers,
        is_tie=len(winner_player_numbers) != 1,
        question_count=max((entry.get("question_number", 0) for entry in entries), default=0),
        current_players=current_players,
        current_series=current_series,
        original_series=original_series,
    )
