import json
import logging
import time
from dataclasses import asdict
from itertools import zip_longest


def get_current_game_state(game):
    game_id = game.current_game_id()
    current_time = time.time()
    return {
        "game_id": game_id,
        "players": [{"name": p.name, "player_number": p.player_number} for p in game.players],
        "started_at": game._game_started_at or current_time,
        "last_updated": current_time,
    }


def save_general_state(game):
    if not game._game_state_dir:
        game._initialize_game_state_dir()
    if not game._game_state_dir:
        return

    state = get_current_game_state(game)
    general_file = game._game_state_dir / "general.json"
    try:
        with open(general_file, "w") as file_obj:
            json.dump(state, file_obj, indent=2)
    except Exception as exc:
        logging.error("Error saving general state: %s", exc)


def classify_buzz_phases(game):
    if not game._all_buzz_attempts:
        return []
    if not game._open_responses_times:
        logging.error("No open responses times found after question completed.")
        return []

    current_time = time.time()
    phase_start_times = [game._question_start_time] + game._open_responses_times[1:]
    phase_boundaries = []
    for phase_start_time, successful_buzz_time in zip_longest(
        phase_start_times,
        game._successful_buzz_times,
        fillvalue=current_time,
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
                "phase_type": "main" if phase_start_time == game._question_start_time else "rebound",
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


def load_question_history(game):
    if not game._game_state_dir:
        game._initialize_game_state_dir()
    if not game._game_state_dir:
        return []

    history_file = game._game_state_dir / "question_history.jsonl"
    if not history_file.exists():
        return []

    entries = []
    try:
        with open(history_file, "r") as file_obj:
            for line in file_obj:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as exc:
        logging.error("Error loading question history: %s", exc)
        return []
    return entries


def reconstruct_score_history(game):
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


def load_general_state(game):
    if not game._game_state_dir:
        game._initialize_game_state_dir()
    if not game._game_state_dir:
        return {}

    general_file = game._game_state_dir / "general.json"
    if not general_file.exists():
        return {}
    try:
        with open(general_file, "r") as file_obj:
            return json.load(file_obj)
    except Exception as exc:
        logging.error("Error loading general state: %s", exc)
        return {}
