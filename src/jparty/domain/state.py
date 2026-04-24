"""Persist and reconstruct game-state snapshots and analytics data.

This module contains the domain-level helpers used to serialize high-level game
state, append per-question history, and rebuild score or buzz-phase summaries
from saved sessions. The game engine delegates persistence work here to keep
state-shaping logic separate from live gameplay orchestration.
"""

import json
import logging
import time
from dataclasses import asdict
from itertools import zip_longest
from pathlib import Path

QUESTION_HISTORY_ENTRY_TYPE = "question"
MANUAL_SCORE_ADJUSTMENT_TYPE = "manual_score_adjustment"


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
    all_players = set()
    score_history = {}
    scores = {}
    event_count = 0

    def ensure_player(player_index: int) -> None:
        if player_index in score_history:
            return
        all_players.add(player_index)
        scores[player_index] = 0
        score_history[player_index] = [0] * (event_count + 1)

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
                    entry.get("new_score", scores.get(player_index, 0)),
                )
        else:
            for attempt in entry.get("answer_attempts", []):
                player_index = attempt.get("player_index")
                if player_index is not None:
                    scores[player_index] = attempt.get(
                        "score_after", scores.get(player_index, 0)
                    )

        event_count += 1
        for player_index in all_players:
            score_history[player_index].append(scores.get(player_index, 0))
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
