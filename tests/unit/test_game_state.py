"""Test game state module."""

import json
import os

import pytest

from jparty.domain.models import Board, FinalBoard, GameData, Question
from jparty.domain.state import (
    build_end_game_summary,
    load_general_state,
    load_question_history,
)

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


def test_load_general_state_without_active_dir_does_not_initialize() -> None:
    """General-state reads should not create a new game-state directory."""

    class StubGame:
        """Track whether lazy initialization was attempted during a read."""

        def __init__(self) -> None:
            """Initialize the stub with no active game-state path."""
            self._game_state_dir = None
            self.initialize_calls = 0

        def _initialize_game_state_dir(self) -> None:
            """Fail the test if read helpers try to create a directory."""
            self.initialize_calls += 1

    game = StubGame()

    state = load_general_state(game)

    assert state == {}
    assert game.initialize_calls == 0


def test_load_question_history_without_active_dir_does_not_initialize() -> None:
    """History reads should not create a new game-state directory."""

    class StubGame:
        """Track whether lazy initialization was attempted during a read."""

        def __init__(self) -> None:
            """Initialize the stub with no active game-state path."""
            self._game_state_dir = None
            self.initialize_calls = 0

        def _initialize_game_state_dir(self) -> None:
            """Fail the test if read helpers try to create a directory."""
            self.initialize_calls += 1

    game = StubGame()

    history = load_question_history(game)

    assert history == []
    assert game.initialize_calls == 0


def test_save_general_state_writes_general_json(
    game: object, players: object, monkeypatch: object
) -> None:
    """Test test save general state writes general json."""
    game.set_session_game_id("7777")
    game.set_selected_round_indices([0, 2])
    game.set_board_selection_configs(
        [
            {
                "game_id": "7777",
                "source_round_index": 0,
                "source_round_label": "Jeopardy!",
                "row_values": [200, 400, 600, 800, 1000],
            }
        ]
    )
    game.set_reveal_answers_after_triple_stumper(True)
    game._save_general_state()
    general_file = game._game_state_dir / "general.json"
    assert general_file.exists()
    saved = json.loads(general_file.read_text())
    assert saved["game_id"] == "7777"
    assert len(saved["players"]) == len(players)
    assert saved["selected_round_indices"] == [0, 2]
    assert saved["board_selections"][0]["source_round_label"] == "Jeopardy!"
    assert saved["reveal_answers_after_triple_stumper"] is True


def test_get_current_game_state_uses_started_at_and_players(
    game: object, players: object, monkeypatch: object, time_controller: object
) -> None:
    """Test test get current game state uses started at and players."""
    game.set_session_game_id("8888")
    time_controller.set(2000.0)
    game._game_started_at = 1234.0
    state = game._get_current_game_state()
    assert state["game_id"] == "8888"
    assert state["started_at"] == 1234.0
    assert state["last_updated"] == 2000.0
    assert [player["name"] for player in state["players"]] == ["Alice", "Bob", "Cara"]


def test_get_current_game_state_records_history_format_only_when_known(
    game: object, players: object
) -> None:
    """Test the format fields are omitted for sessions with no recorded format."""
    state = game._get_current_game_state()
    assert "history_format" not in state
    assert "jparty_version" not in state

    game._history_format = 2
    game._started_by_version = "9.9.9"
    state = game._get_current_game_state()
    assert state["history_format"] == 2
    assert state["jparty_version"] == "9.9.9"


def test_initialize_game_state_dir_uses_game_id_and_local_timestamp(
    game: object, monkeypatch: object
) -> None:
    """Test test initialize game state dir uses game id and local timestamp."""
    game.set_session_game_id("9999")

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


def test_build_end_game_summary_counts_early_buzzes_per_question(
    game: object, players: object, temp_dir: object
) -> None:
    """Repeated early buzzes on one clue should count once in the summary."""
    game._game_state_dir = temp_dir / "saved-early-buzzes"
    game._game_state_dir.mkdir()
    game.data = GameData(
        rounds=[
            Board(
                categories=["Cat"],
                questions=[
                    Question((0, 0), "Q1", "A1", "Cat", value=200),
                    Question((0, 1), "Q2", "A2", "Cat", value=400),
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
                        "value": 200,
                        "buzz_phases": [
                            {
                                "phase_type": "main",
                                "buzz_attempts": [
                                    {
                                        "player_index": 0,
                                        "is_early": True,
                                        "in_timeout": False,
                                    },
                                    {
                                        "player_index": 0,
                                        "is_early": True,
                                        "in_timeout": False,
                                    },
                                    {
                                        "player_index": 0,
                                        "is_early": True,
                                        "in_timeout": True,
                                    },
                                ],
                            }
                        ],
                        "answer_attempts": [],
                    }
                ),
                json.dumps(
                    {
                        "question_index": [0, [0, 1]],
                        "question_number": 2,
                        "round_index": 0,
                        "is_daily_double": False,
                        "buzz_phases": [
                            {
                                "phase_type": "main",
                                "buzz_attempts": [
                                    {
                                        "player_index": 0,
                                        "is_early": True,
                                        "in_timeout": False,
                                    }
                                ],
                            }
                        ],
                        "answer_attempts": [],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_end_game_summary(game)
    player_zero = next(
        player for player in summary.current_players if player.player_number == 0
    )

    assert player_zero.early_buzzes == 2


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
                        "value": 200,
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
                        "value": 400,
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
                        "value": 800,
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


def _write_history(game_state_dir: object, entries: list[dict]) -> None:
    """Write ``entries`` as a question history file in ``game_state_dir``."""
    (game_state_dir / "question_history.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries),
        encoding="utf-8",
    )


def test_build_end_game_summary_counts_last_board_without_final(
    game: object, players: object, temp_dir: object
) -> None:
    """Coryat and triple stumpers include the last board when no Final is loaded."""
    game._game_state_dir = temp_dir / "saved-no-final"
    game._game_state_dir.mkdir()
    players[0].score = 400
    game.data = GameData(
        rounds=[
            Board(
                categories=["Cat"],
                questions=[
                    Question((0, 0), "Q1", "A1", "Cat", value=400),
                    Question((0, 1), "Q2", "A2", "Cat", value=800),
                ],
            ),
        ],
        date="today",
        comments="",
    )
    _write_history(
        game._game_state_dir,
        [
            {
                "question_index": [0, [0, 0]],
                "question_number": 1,
                "round_index": 0,
                "is_daily_double": False,
                "value": 400,
                "answer_attempts": [
                    {"player_index": 0, "answer_correct": True, "score_after": 400}
                ],
            },
            {
                "question_index": [0, [0, 1]],
                "question_number": 2,
                "round_index": 0,
                "is_daily_double": False,
                "value": 800,
                "answer_attempts": [],
            },
        ],
    )
    summary = build_end_game_summary(game)
    player_zero = next(
        player for player in summary.current_players if player.player_number == 0
    )
    assert player_zero.coryat == 400
    assert summary.game_stats.combined_coryat == 400
    assert summary.game_stats.triple_stumpers == 1


def test_build_end_game_summary_skips_final_board_by_type(
    game: object, players: object, temp_dir: object
) -> None:
    """Final Jeopardy clues never count toward Coryat or triple stumpers."""
    game._game_state_dir = temp_dir / "saved-final-first"
    game._game_state_dir.mkdir()
    players[0].score = 1000
    players[1].score = -200
    game.data = GameData(
        rounds=[
            FinalBoard("Final", Question((0, 0), "FJ", "FA", "Final")),
            Board(
                categories=["Cat"],
                questions=[Question((0, 0), "Q1", "A1", "Cat", value=200)],
            ),
        ],
        date="today",
        comments="",
    )
    _write_history(
        game._game_state_dir,
        [
            {
                "question_index": [0, [0, 0]],
                "question_number": 1,
                "round_index": 0,
                "is_daily_double": False,
                "value": 0,
                "answer_attempts": [
                    {"player_index": 0, "answer_correct": True, "score_after": 1000}
                ],
            },
            {
                "question_index": [1, [0, 0]],
                "question_number": 2,
                "round_index": 1,
                "is_daily_double": False,
                "value": 200,
                "answer_attempts": [
                    {"player_index": 1, "answer_correct": False, "score_after": -200}
                ],
            },
        ],
    )
    summary = build_end_game_summary(game)
    coryat = {player.player_number: player.coryat for player in summary.current_players}
    assert coryat[0] == 0
    assert coryat[1] == -200
    assert summary.game_stats.triple_stumpers == 1


def test_build_end_game_summary_lead_changes_with_manual_adjustment_and_final(
    game: object, players: object, temp_dir: object
) -> None:
    """A manual score change must not hide a lead change in Final Jeopardy."""
    game._game_state_dir = temp_dir / "saved-manual-final"
    game._game_state_dir.mkdir()
    players[0].score = 200
    players[1].score = 1100
    players[2].score = 0
    game.data = GameData(
        rounds=[
            Board(
                categories=["Cat"],
                questions=[Question((0, 0), "Q1", "A1", "Cat", value=200)],
            ),
            FinalBoard("Final", Question((0, 0), "FJ", "FA", "Final")),
        ],
        date="today",
        comments="",
    )
    _write_history(
        game._game_state_dir,
        [
            {
                "question_index": [0, [0, 0]],
                "question_number": 1,
                "round_index": 0,
                "is_daily_double": False,
                "value": 200,
                "answer_attempts": [
                    {"player_index": 0, "answer_correct": True, "score_after": 200}
                ],
            },
            {
                "type": "manual_score_adjustment",
                "player_index": 1,
                "timestamp": 5.0,
                "score_before": 0,
                "score_after": 100,
                "new_score": 100,
            },
            {
                "question_index": [1, [0, 0]],
                "question_number": 2,
                "round_index": 1,
                "is_daily_double": False,
                "value": 0,
                "answer_attempts": [
                    {
                        "player_index": 1,
                        "answer_correct": True,
                        "score_before": 100,
                        "score_after": 1100,
                    }
                ],
            },
        ],
    )
    summary = build_end_game_summary(game)
    assert summary.question_count == 2
    assert summary.game_stats.lead_changes == 1
    assert summary.game_stats.victory_summary == "$200 come-from-behind victory"


def _three_clue_board() -> GameData:
    """Return a one-category board with three clues and no Final."""
    return GameData(
        rounds=[
            Board(
                categories=["Cat"],
                questions=[
                    Question((0, row), f"Q{row}", f"A{row}", "Cat", value=200)
                    for row in range(3)
                ],
            )
        ],
        date="today",
        comments="",
    )


def _clue(question_number: int, value: int, attempts: list[dict], **extra) -> dict:
    """Return one clue history line for the three-clue board."""
    return {
        "question_index": [0, [0, question_number - 1]],
        "question_number": question_number,
        "round_index": 0,
        "is_daily_double": False,
        "value": value,
        "answer_attempts": attempts,
        **extra,
    }


def _attempt(player_index: int, correct: bool, before: int, after: int) -> dict:
    """Return one recorded answer attempt with its score change."""
    return {
        "player_index": player_index,
        "answer_correct": correct,
        "score_before": before,
        "score_after": after,
    }


def _series_by_player(summary: object) -> dict[int, list[int]]:
    """Return each current player's graph series keyed by player number."""
    return {series.player_number: series.scores for series in summary.current_series}


def test_build_end_game_summary_applies_ruling_corrections_from_the_start(
    game: object, players: object, temp_dir: object
) -> None:
    """A corrected ruling counts as if the clue had been judged right at the time.

    Player 0 was wrongly marked incorrect on clue 2, which (as recorded) handed
    the lead to the others and then tied it. The host later changed it to no
    answer. As it should have been, player 0 led the whole game, so there are
    no lead changes and the correction adds no point to the graph.
    """
    game._game_state_dir = temp_dir / "saved-ruling-correction"
    game._game_state_dir.mkdir()
    players[0].score = 400
    players[1].score = 0
    players[2].score = 0
    game.data = _three_clue_board()
    _write_history(
        game._game_state_dir,
        [
            _clue(1, 200, [_attempt(0, True, 0, 200)]),
            _clue(2, 400, [_attempt(0, False, 200, -200)]),
            _clue(3, 200, [_attempt(0, True, -200, 0)]),
            {
                "type": "score_correction",
                "question_number": 2,
                "timestamp": 10.0,
                "player_states": {"0": "no answer", "1": "no answer", "2": "no answer"},
                "adjustments": [
                    {"player_index": 0, "score_before": 0, "score_after": 400}
                ],
            },
        ],
    )

    summary = build_end_game_summary(game)

    assert summary.game_stats.lead_changes == 0
    assert _series_by_player(summary)[0] == [0, 200, 200, 400]


def test_build_end_game_summary_applies_wager_corrections_from_the_start(
    game: object, players: object, temp_dir: object
) -> None:
    """A corrected Daily Double wager changes the score at the Daily Double.

    The lead change happens at the Daily Double itself, not at the later
    correction, so the graph has no extra point for the correction.
    """
    game._game_state_dir = temp_dir / "saved-wager-correction"
    game._game_state_dir.mkdir()
    players[0].score = 1000
    players[1].score = 200
    players[2].score = 0
    game.data = _three_clue_board()
    _write_history(
        game._game_state_dir,
        [
            _clue(1, 200, [_attempt(1, True, 0, 200)]),
            _clue(2, 100, [_attempt(0, True, 0, 100)], is_daily_double=True),
            {
                "type": "score_correction",
                "question_number": 2,
                "timestamp": 10.0,
                "value": 1000,
                "player_states": {"0": "correct", "1": "no answer", "2": "no answer"},
                "adjustments": [
                    {"player_index": 0, "score_before": 100, "score_after": 1000}
                ],
            },
        ],
    )

    summary = build_end_game_summary(game)

    assert summary.game_stats.lead_changes == 1
    assert _series_by_player(summary)[0] == [0, 0, 1000]
    assert _series_by_player(summary)[1] == [0, 200, 200]


def test_build_end_game_summary_counts_manual_adjustment_as_its_own_event(
    game: object, players: object, temp_dir: object
) -> None:
    """A manual score change is a separate event where it happened.

    The host's reason for a manual change isn't recorded, so it can't be
    moved to an earlier clue. If it changes the leader, that is a lead change.
    """
    game._game_state_dir = temp_dir / "saved-manual-lead"
    game._game_state_dir.mkdir()
    players[0].score = 200
    players[1].score = 500
    players[2].score = 0
    game.data = _three_clue_board()
    _write_history(
        game._game_state_dir,
        [
            _clue(1, 200, [_attempt(0, True, 0, 200)]),
            {
                "type": "manual_score_adjustment",
                "player_index": 1,
                "timestamp": 5.0,
                "score_before": 0,
                "score_after": 500,
                "new_score": 500,
            },
        ],
    )

    summary = build_end_game_summary(game)

    assert summary.game_stats.lead_changes == 1
    assert _series_by_player(summary)[1] == [0, 0, 500]


def test_score_graph_uses_composed_session_game_id(
    game: object,
    players: object,
    monkeypatch: object,
    sample_saved_game_dir: object,
    temp_dir: object,
) -> None:
    """A Frankenstein game's graph is titled and named with its session id.

    Loading source games used to leave the last one's id in the process
    environment, and the graph read it from there.
    """
    import matplotlib.axes

    import jparty.domain.game_engine as game_module

    monkeypatch.setenv("JPARTY_GAME_ID", "5000")
    monkeypatch.setattr(game_module, "GAME_SCORES_DIR", temp_dir / "scores")
    titles = []
    original_set_title = matplotlib.axes.Axes.set_title

    def record_title(
        self: object, label: str, *args: object, **kwargs: object
    ) -> object:
        titles.append(label)
        return original_set_title(self, label, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "set_title", record_title)
    game._game_state_dir = sample_saved_game_dir
    game.set_session_game_id("frankenstein-4453-5000")

    game.generate_final_score_graph("original")

    assert titles == ["Game frankenstein-4453-5000: Player Scores"]
    assert (temp_dir / "scores" / "frankenstein-4453-5000-original.jpg").exists()


def test_get_game_does_not_write_the_game_id_to_the_environment(
    monkeypatch: object,
) -> None:
    """Loading a game must not change process-wide state.

    Source games load on worker threads, so a shared variable would hold
    whichever game finished last.
    """
    from jparty.services import archive_client

    monkeypatch.delenv("JPARTY_GAME_ID", raising=False)
    monkeypatch.setattr(archive_client, "_get_archive_game", lambda game_id: None)

    archive_client.get_game("4453")

    assert "JPARTY_GAME_ID" not in os.environ


def _game_with_distinct_rounds() -> GameData:
    """Return Jeopardy, Double Jeopardy and Final boards with different categories."""
    rounds = []
    for multiplier, prefix in ((1, "J"), (2, "DJ")):
        categories = [f"{prefix} {col}" for col in range(6)]
        questions = [
            Question(
                (col, row),
                "clue",
                "response",
                categories[col],
                (row + 1) * 200 * multiplier,
            )
            for col in range(6)
            for row in range(5)
        ]
        rounds.append(Board(categories, questions, dj=multiplier == 2))
    final = FinalBoard("Final", Question((0, 0), "clue", "response", "Final"))
    return GameData([*rounds, final], "January 1, 2026", "Fixture game")


DJ_AND_FINAL_SELECTIONS = [
    {
        "game_id": "4453",
        "source_round_index": 1,
        "source_round_label": "Double Jeopardy!",
        "board_type": "standard",
        "row_values": [400, 800, 1200, 1600, 2000],
        "daily_double_count": 0,
        "daily_double_indices": [],
    },
    {
        "game_id": "4453",
        "source_round_index": 2,
        "source_round_label": "Final Jeopardy!",
        "board_type": "final",
        "row_values": [],
    },
]


@pytest.mark.parametrize(
    ("general_state", "expected_rounds", "expected_selected"),
    [
        ({"selected_round_indices": [0, 1]}, ["J 0", "DJ 0", "Final"], [0, 1]),
        ({"selected_round_indices": [1, 2]}, ["J 0", "DJ 0", "Final"], [1, 2]),
        (
            {
                "selected_round_indices": [0, 1],
                "board_selections": DJ_AND_FINAL_SELECTIONS,
            },
            ["DJ 0", "Final"],
            [0, 1],
        ),
    ],
    ids=[
        "no-selections-prefix",
        "no-selections-skipped-round",
        "regular-subset",
    ],
)
def test_load_saved_game_data_layouts(
    monkeypatch: object,
    general_state: dict,
    expected_rounds: list,
    expected_selected: list,
) -> None:
    """Each save layout loads the boards its history numbers point at (#93)."""
    from jparty.domain.state import load_saved_game_data
    from jparty.services import game_loader

    monkeypatch.setattr(
        game_loader, "get_game", lambda game_id: _game_with_distinct_rounds()
    )

    saved = load_saved_game_data({"game_id": "4453", **general_state})

    assert [
        round_data.categories[0] for round_data in saved.data.rounds
    ] == expected_rounds
    assert saved.selected_round_indices == expected_selected
