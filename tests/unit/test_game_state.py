"""Test game state module."""

import json

import pytest
from jparty.domain.models import Board, FinalBoard, GameData, Question
from jparty.domain.state import build_end_game_summary

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
    game.set_reveal_answers_after_triple_stumper(True)
    game._save_general_state()
    general_file = game._game_state_dir / "general.json"
    assert general_file.exists()
    saved = json.loads(general_file.read_text())
    assert saved["game_id"] == "7777"
    assert len(saved["players"]) == len(players)
    assert saved["selected_round_indices"] == [0, 2]
    assert saved["reveal_answers_after_triple_stumper"] is True


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


def test_build_end_game_summary_calculates_stats(
    game: object, players: object, sample_saved_game_dir: object
) -> None:
    """Test end-game summary metrics from saved question history."""
    game._game_state_dir = sample_saved_game_dir
    summary = build_end_game_summary(game)
    player_zero = next(
        player for player in summary.current_players if player.player_number == 0
    )
    player_one = next(
        player for player in summary.current_players if player.player_number == 1
    )
    assert player_zero.coryat == 0
    assert player_zero.right_count == 1
    assert player_zero.wrong_count == 1
    assert player_one.coryat == 400
    assert player_one.right_count == 2
    assert player_one.wrong_count == 0


def test_build_end_game_summary_uses_played_order_for_original_series(
    game: object, temp_dir: object
) -> None:
    """Test original gray traces follow played clue order, not board order."""
    game._game_state_dir = temp_dir / "saved"
    game._game_state_dir.mkdir()
    game.data = GameData(
        rounds=[
            Board(
                categories=["Cat"],
                questions=[
                    Question(
                        (0, 0),
                        "Q1",
                        "A1",
                        "Cat",
                        value=200,
                        actual_results=[["Original Bob", 200]],
                    ),
                    Question(
                        (0, 1),
                        "Q2",
                        "A2",
                        "Cat",
                        value=400,
                        actual_results=[["Original Alice", 400]],
                    ),
                ],
            ),
            FinalBoard(
                "Final Cat",
                Question((0, 0), "FJ", "FA", "Final Cat", actual_results=[]),
            ),
        ],
        date="today",
        comments="",
    )
    (game._game_state_dir / "general.json").write_text(
        json.dumps({"game_id": "1234", "players": []}),
        encoding="utf-8",
    )
    (game._game_state_dir / "question_history.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_index": [0, [0, 1]],
                        "question_number": 1,
                        "round_index": 0,
                        "answer_attempts": [],
                    }
                ),
                json.dumps(
                    {
                        "question_index": [0, [0, 0]],
                        "question_number": 2,
                        "round_index": 0,
                        "answer_attempts": [],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    summary = build_end_game_summary(game)
    original_by_name = {series.name: series for series in summary.original_series}
    assert original_by_name["Original Alice"].scores == [0, 400, 400]
    assert original_by_name["Original Bob"].scores == [0, 0, 200]


def test_build_end_game_summary_limits_original_series_to_filtered_rounds(
    game: object, temp_dir: object
) -> None:
    """Test original gray traces only include played clues from filtered data."""
    game._game_state_dir = temp_dir / "saved-filtered"
    game._game_state_dir.mkdir()
    game.data = GameData(
        rounds=[
            Board(
                categories=["Filtered"],
                questions=[
                    Question(
                        (0, 0),
                        "Only played clue",
                        "Answer",
                        "Filtered",
                        value=400,
                        actual_results=[["Filtered Player", 400]],
                    )
                ],
            ),
            FinalBoard(
                "Final Cat",
                Question((0, 0), "FJ", "FA", "Final Cat", actual_results=[]),
            ),
        ],
        date="today",
        comments="",
    )
    (game._game_state_dir / "general.json").write_text(
        json.dumps({"game_id": "1234", "players": [], "selected_round_indices": [1]}),
        encoding="utf-8",
    )
    (game._game_state_dir / "question_history.jsonl").write_text(
        json.dumps(
            {
                "question_index": [0, [0, 0]],
                "question_number": 1,
                "round_index": 0,
                "answer_attempts": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    summary = build_end_game_summary(game)
    assert len(summary.original_series) == 1
    assert summary.original_series[0].name == "Filtered Player"
    assert summary.original_series[0].scores == [0, 400]


def test_build_end_game_summary_includes_final_jeopardy_in_original_series(
    game: object, temp_dir: object
) -> None:
    """Test original gray traces include Final Jeopardy when it was played."""
    game._game_state_dir = temp_dir / "saved-final"
    game._game_state_dir.mkdir()
    game.data = GameData(
        rounds=[
            Board(
                categories=["Cat"],
                questions=[
                    Question(
                        (0, 0),
                        "Q1",
                        "A1",
                        "Cat",
                        value=200,
                        actual_results=[["Original Alice", 200]],
                    )
                ],
            ),
            FinalBoard(
                "Final Cat",
                Question(
                    (0, 0),
                    "FJ",
                    "FA",
                    "Final Cat",
                    actual_results=[["Original Alice", -1000], ["Original Bob", 1000]],
                ),
            ),
        ],
        date="today",
        comments="",
    )
    (game._game_state_dir / "general.json").write_text(
        json.dumps({"game_id": "1234", "players": []}),
        encoding="utf-8",
    )
    (game._game_state_dir / "question_history.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_index": [0, [0, 0]],
                        "question_number": 1,
                        "round_index": 0,
                        "answer_attempts": [],
                    }
                ),
                json.dumps(
                    {
                        "question_index": [1, [0, 0]],
                        "question_number": 2,
                        "round_index": 1,
                        "answer_attempts": [],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    summary = build_end_game_summary(game)
    original_by_name = {series.name: series for series in summary.original_series}
    assert original_by_name["Original Alice"].scores == [0, 200, -800]
    assert original_by_name["Original Bob"].scores == [0, 0, 1000]


def test_build_end_game_summary_computes_game_stats(
    game: object, players: object, temp_dir: object
) -> None:
    """Test game-level summary stats and comeback text."""
    game._game_state_dir = temp_dir / "saved-game-stats"
    game._game_state_dir.mkdir()
    players[0].score = 400
    players[1].score = 1200
    players[2].score = 0
    game.data = GameData(
        rounds=[
            Board(
                categories=["Cat"],
                questions=[
                    Question((0, 0), "Q1", "A1", "Cat", value=200),
                    Question((0, 1), "Q2", "A2", "Cat", value=400),
                    Question((0, 2), "Q3", "A3", "Cat", value=800),
                ],
            ),
            FinalBoard("Final", Question((0, 0), "FJ", "FA", "Final")),
        ],
        date="today",
        comments="",
    )
    (game._game_state_dir / "general.json").write_text(
        json.dumps({"game_id": "1234", "players": []}),
        encoding="utf-8",
    )
    (game._game_state_dir / "question_history.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_index": [0, [0, 0]],
                        "question_number": 1,
                        "round_index": 0,
                        "is_daily_double": False,
                        "buzz_phases": [
                            {
                                "phase_type": "main",
                                "buzz_attempts": [
                                    {"player_index": 0, "in_timeout": False},
                                    {"player_index": 1, "in_timeout": False},
                                ],
                            }
                        ],
                        "answer_attempts": [
                            {
                                "player_index": 0,
                                "answer_correct": True,
                                "score_after": 200,
                            }
                        ],
                    }
                ),
                json.dumps(
                    {
                        "question_index": [0, [0, 1]],
                        "question_number": 2,
                        "round_index": 0,
                        "is_daily_double": False,
                        "buzz_phases": [],
                        "answer_attempts": [],
                    }
                ),
                json.dumps(
                    {
                        "question_index": [0, [0, 2]],
                        "question_number": 3,
                        "round_index": 0,
                        "is_daily_double": False,
                        "buzz_phases": [
                            {
                                "phase_type": "main",
                                "buzz_attempts": [
                                    {"player_index": 0, "in_timeout": False},
                                    {"player_index": 1, "in_timeout": False},
                                ],
                            }
                        ],
                        "answer_attempts": [
                            {
                                "player_index": 1,
                                "answer_correct": True,
                                "score_after": 1200,
                            }
                        ],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    summary = build_end_game_summary(game)
    assert summary.game_stats.lead_changes == 1
    assert summary.game_stats.combined_coryat == 1000
    assert summary.game_stats.buzzer_races == 2
    assert summary.game_stats.triple_stumpers == 1
    assert summary.game_stats.victory_summary == "$200 come-from-behind victory"


def test_reconstruct_score_history_includes_manual_adjustments(
    game: object, temp_dir: object
) -> None:
    """Test manual score adjustment entries participate in replay."""
    game._game_state_dir = temp_dir / "saved"
    game._game_state_dir.mkdir()
    history_file = game._game_state_dir / "question_history.jsonl"
    history_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_index": [0, [0, 0]],
                        "question_number": 1,
                        "round_index": 0,
                        "category": "Cat 0",
                        "value": 200,
                        "is_daily_double": False,
                        "buzz_phases": [],
                        "answer_attempts": [
                            {
                                "player_index": 0,
                                "answer_correct": True,
                                "timestamp": 1000.0,
                                "score_before": 0,
                                "score_after": 200,
                            }
                        ],
                        "completed_at": 1001.0,
                    }
                ),
                json.dumps(
                    {
                        "type": "manual_score_adjustment",
                        "player_index": 0,
                        "timestamp": 1002.0,
                        "score_before": 200,
                        "score_after": 900,
                        "new_score": 900,
                    }
                ),
            ]
        )
        + "\n"
    )
    score_history = game._reconstruct_score_history()
    assert score_history[0] == [0, 200, 900]


def test_build_end_game_summary_counts_races_in_any_phase(
    game: object, players: object, temp_dir: object
) -> None:
    """Test race stats count any phase with multiple buzzers."""
    game._game_state_dir = temp_dir / "saved-races"
    game._game_state_dir.mkdir()
    (game._game_state_dir / "general.json").write_text(
        json.dumps(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                    {"name": "Cara", "player_number": 2},
                ],
            }
        ),
        encoding="utf-8",
    )
    (game._game_state_dir / "question_history.jsonl").write_text(
        json.dumps(
            {
                "question_index": [0, [0, 0]],
                "question_number": 1,
                "round_index": 0,
                "category": "Cat 0",
                "value": 200,
                "is_daily_double": False,
                "buzz_phases": [
                    {
                        "phase_type": "main",
                        "start_time": 1.0,
                        "end_time": 2.0,
                        "buzz_attempts": [
                            {
                                "player_index": 0,
                                "question_index": [0, [0, 0]],
                                "timestamp": 1.1,
                                "is_early": False,
                                "is_success": True,
                                "is_rebound": False,
                                "in_timeout": False,
                            },
                            {
                                "player_index": 1,
                                "question_index": [0, [0, 0]],
                                "timestamp": 1.2,
                                "is_early": False,
                                "is_success": False,
                                "is_rebound": False,
                                "in_timeout": False,
                            },
                        ],
                    },
                    {
                        "phase_type": "rebound",
                        "start_time": 3.0,
                        "end_time": 4.0,
                        "buzz_attempts": [
                            {
                                "player_index": 1,
                                "question_index": [0, [0, 0]],
                                "timestamp": 3.1,
                                "is_early": False,
                                "is_success": True,
                                "is_rebound": True,
                                "in_timeout": False,
                            },
                            {
                                "player_index": 2,
                                "question_index": [0, [0, 0]],
                                "timestamp": 3.2,
                                "is_early": False,
                                "is_success": False,
                                "is_rebound": True,
                                "in_timeout": False,
                            },
                        ],
                    },
                ],
                "answer_attempts": [
                    {
                        "player_index": 0,
                        "answer_correct": False,
                        "timestamp": 2.5,
                        "score_before": 0,
                        "score_after": -200,
                    },
                    {
                        "player_index": 1,
                        "answer_correct": True,
                        "timestamp": 4.5,
                        "score_before": 0,
                        "score_after": 200,
                    },
                ],
                "completed_at": 5.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    summary = build_end_game_summary(game)
    stats_by_player = {
        player.player_number: player for player in summary.current_players
    }
    assert stats_by_player[0].race_wins == 1
    assert stats_by_player[0].race_opportunities == 1
    assert stats_by_player[1].race_wins == 1
    assert stats_by_player[1].race_opportunities == 2
    assert stats_by_player[2].race_wins == 0
    assert stats_by_player[2].race_opportunities == 1
