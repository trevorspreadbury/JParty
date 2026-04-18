import json
import os

import pytest


pytestmark = pytest.mark.unit


def test_reconstruct_score_history_from_question_history(game, sample_saved_game_dir):
    game._game_state_dir = sample_saved_game_dir

    score_history = game._reconstruct_score_history()

    assert score_history[0] == [0, 200, 200, 0]
    assert score_history[1] == [0, 0, 200, 400]


def test_load_general_state_reads_fixture(game, sample_saved_game_dir):
    game._game_state_dir = sample_saved_game_dir

    state = game._load_general_state()

    assert state["game_id"] == "4453"
    assert len(state["players"]) == 2


def test_save_general_state_writes_general_json(game, players, monkeypatch):
    monkeypatch.setenv("JPARTY_GAME_ID", "7777")

    game._save_general_state()

    general_file = game._game_state_dir / "general.json"
    assert general_file.exists()
    saved = json.loads(general_file.read_text())
    assert saved["game_id"] == "7777"
    assert len(saved["players"]) == len(players)


def test_get_current_game_state_uses_started_at_and_players(game, players, monkeypatch, time_controller):
    monkeypatch.setenv("JPARTY_GAME_ID", "8888")
    time_controller.set(2000.0)
    game._game_started_at = 1234.0

    state = game._get_current_game_state()

    assert state["game_id"] == "8888"
    assert state["started_at"] == 1234.0
    assert state["last_updated"] == 2000.0
    assert [player["name"] for player in state["players"]] == ["Alice", "Bob", "Cara"]


def test_classify_buzz_phases_splits_main_and_rebound(game):
    from jparty.domain.models import BuzzAttempt

    game._question_start_time = 100.0
    game._open_responses_times = [105.0, 112.0]
    game._successful_buzz_times = [110.0]
    game._all_buzz_attempts = [
        BuzzAttempt(0, (0, (0, 0)), 106.0, False, True, False, False),
        BuzzAttempt(1, (0, (0, 0)), 113.0, False, True, False, False),
    ]

    phases = game._classify_buzz_phases()

    assert [phase["phase_type"] for phase in phases] == ["main", "rebound"]
    assert phases[0]["buzz_attempts"][0]["player_index"] == 0
    assert phases[1]["buzz_attempts"][0]["player_index"] == 1
