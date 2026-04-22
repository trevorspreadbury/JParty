"""Test game state module."""

import json

import pytest

pytestmark = pytest.mark.unit


def test_reconstruct_score_history_from_question_history(
    game: object, sample_saved_game_dir: object
) -> None:
    """Test test reconstruct score history from question history."""
    game._game_state_dir = sample_saved_game_dir
    score_history = game._reconstruct_score_history()
    assert score_history[0] == [0, 200, 200, 0]
    assert score_history[1] == [0, 0, 200, 400]


def test_load_general_state_reads_fixture(
    game: object, sample_saved_game_dir: object
) -> None:
    """Test test load general state reads fixture."""
    game._game_state_dir = sample_saved_game_dir
    state = game._load_general_state()
    assert state["game_id"] == "4453"
    assert len(state["players"]) == 2


def test_save_general_state_writes_general_json(
    game: object, players: object, monkeypatch: object
) -> None:
    """Test test save general state writes general json."""
    monkeypatch.setenv("JPARTY_GAME_ID", "7777")
    game.set_selected_round_indices([0, 2])
    game._save_general_state()
    general_file = game._game_state_dir / "general.json"
    assert general_file.exists()
    saved = json.loads(general_file.read_text())
    assert saved["game_id"] == "7777"
    assert len(saved["players"]) == len(players)
    assert saved["selected_round_indices"] == [0, 2]


def test_get_current_game_state_uses_started_at_and_players(
    game: object, players: object, monkeypatch: object, time_controller: object
) -> None:
    """Test test get current game state uses started at and players."""
    monkeypatch.setenv("JPARTY_GAME_ID", "8888")
    time_controller.set(2000.0)
    game._game_started_at = 1234.0
    state = game._get_current_game_state()
    assert state["game_id"] == "8888"
    assert state["started_at"] == 1234.0
    assert state["last_updated"] == 2000.0
    assert [player["name"] for player in state["players"]] == ["Alice", "Bob", "Cara"]


def test_initialize_game_state_dir_uses_game_id_and_local_timestamp(
    game: object, monkeypatch: object
) -> None:
    """Test test initialize game state dir uses game id and local timestamp."""
    monkeypatch.setenv("JPARTY_GAME_ID", "9999")

    class FakeNow:
        """Test helper for fakenow."""

        def astimezone(self) -> object:
            """Test astimezone."""
            return self

        def strftime(self, fmt: object) -> str:
            """Test strftime."""
            assert fmt == "%Y%m%dT%H%M"
            return "20260418T1435"

    class FixedDatetime:
        """Test helper for fixeddatetime."""

        @classmethod
        def now(cls) -> object:
            """Test now."""
            return FakeNow()

    monkeypatch.setattr("jparty.domain.game_engine.datetime", FixedDatetime)
    game._initialize_game_state_dir()
    assert game._game_state_dir.name == "9999-20260418T1435"
    assert game._game_state_dir.exists()


def test_classify_buzz_phases_splits_main_and_rebound(game: object) -> None:
    """Test test classify buzz phases splits main and rebound."""
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
