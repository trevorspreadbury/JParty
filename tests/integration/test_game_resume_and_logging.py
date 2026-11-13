"""Test game resume and logging module."""

import json
from copy import deepcopy

import pytest
from PyQt6.QtCore import Qt

from jparty import __version__
from jparty.domain.models import FinalBoard, Player
from jparty.domain.state import HISTORY_FORMAT

pytestmark = pytest.mark.integration


class DummyWaiter:
    """Test helper for dummywaiter."""

    def send(self, message: object, text: object = "") -> None:
        """Test send."""
        return None

    def close(self) -> None:
        """Test close."""
        return None


def test_question_history_logging_writes_buzz_phases_and_attempts(
    game_with_players: object, time_controller: object
) -> None:
    """Test test question history logging writes buzz phases and attempts."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    time_controller.advance(1.0)
    game.buzz(0)
    game.open_responses()
    time_controller.advance(0.1)
    game.buzz(1)
    time_controller.advance(0.2)
    game.correct_answer()
    history_file = game._game_state_dir / "question_history.jsonl"
    entry = json.loads(history_file.read_text().splitlines()[0])
    assert entry["question_number"] == 1
    assert entry["answer_attempts"][0]["player_index"] == 1
    assert entry["buzz_phases"]
    assert entry["buzz_phases"][0]["buzz_attempts"][0]["player_index"] == 0


def test_final_jeopardy_logging_writes_question_history_entry(
    game_with_players: object,
) -> None:
    """Test Final Jeopardy judgments are written to question history."""
    game = game_with_players
    game.current_round = game.data.rounds[2]
    game.active_question = game.current_round.question
    game.players[0].score = 1000
    game.players[1].score = 800
    game.players[2].score = 600
    game.players[0].wager = 200
    game.players[1].wager = 300
    game.players[2].wager = 100
    game.players[0].finalanswer = "Paris"
    game.players[1].finalanswer = "London"
    game.players[2].finalanswer = "Rome"
    game.final_open_responses()
    for expected_player, is_correct in [
        (game.players[2], False),
        (game.players[1], True),
        (game.players[0], False),
    ]:
        game.final_next_player()
        assert game.answering_player is expected_player
        game.final_show_answer()
        if is_correct:
            game.final_correct_answer()
        else:
            game.final_incorrect_answer()
    game.final_next_player()
    history_file = game._game_state_dir / "question_history.jsonl"
    entry = json.loads(history_file.read_text().splitlines()[-1])
    assert entry["round_index"] == 2
    assert entry["answer_attempts"]
    assert [attempt["player_index"] for attempt in entry["answer_attempts"]] == [
        2,
        1,
        0,
    ]


def test_prepare_and_resume_saved_game_restores_round_scores_and_questions(
    game: object, monkeypatch: object, sample_saved_game_dir: object
) -> None:
    """Test test prepare and resume saved game restores round scores and questions."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(sample_saved_game_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()
    assert game.current_round is game.data.rounds[0]
    assert not isinstance(game.current_round, FinalBoard)
    assert game.question_number == 4
    assert game.players[0].score == 0
    assert game.players[1].score == 400
    assert game.current_round.get_question(0, 0).complete is True
    assert game.current_round.get_question(1, 0).complete is True
    assert game.current_round.get_question(2, 0).complete is True
    assert game.current_round.get_question(3, 0).complete is False


def _resume_and_read_general_state(game: object, saved_dir: object) -> dict:
    """Resume ``saved_dir`` and return the ``general.json`` it writes back."""
    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()
    return json.loads((saved_dir / "general.json").read_text())


def test_new_game_records_history_format_and_version(
    game: object, players: object, monkeypatch: object
) -> None:
    """Test a new session stamps general.json with the format and app version."""
    from jparty.services import archive_client

    monkeypatch.setattr(archive_client, "save_game_html", lambda game_id: None)
    game.set_session_game_id("4453")
    game.start_game()

    saved = json.loads((game._game_state_dir / "general.json").read_text())
    assert saved["history_format"] == HISTORY_FORMAT
    assert saved["jparty_version"] == __version__


def test_resume_keeps_the_recorded_format_and_version(
    game: object, monkeypatch: object, sample_saved_game_dir: object
) -> None:
    """Test resume keeps the version that started the save, not the current one."""
    from jparty.services import game_loader

    monkeypatch.setattr(game_loader, "get_game", lambda game_id: game.data)
    general_file = sample_saved_game_dir / "general.json"
    general_state = json.loads(general_file.read_text())
    general_state["history_format"] = 2
    general_state["jparty_version"] = "0.0.1-test"
    general_file.write_text(json.dumps(general_state))

    saved = _resume_and_read_general_state(game, sample_saved_game_dir)

    assert saved["history_format"] == 2
    assert saved["jparty_version"] == "0.0.1-test"


def test_resume_leaves_a_save_without_a_format_unmarked(
    game: object, monkeypatch: object, sample_saved_game_dir: object
) -> None:
    """Test resuming a save from before the fields existed doesn't add them."""
    from jparty.services import game_loader

    monkeypatch.setattr(game_loader, "get_game", lambda game_id: game.data)
    general_state = json.loads((sample_saved_game_dir / "general.json").read_text())
    assert "history_format" not in general_state

    saved = _resume_and_read_general_state(game, sample_saved_game_dir)

    assert "history_format" not in saved
    assert "jparty_version" not in saved


def test_resume_into_final_starts_final_flow(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Test test resume into final starts final flow."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as f:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "started_at": 1700000000.0,
                "last_updated": 1700000300.0,
            },
            f,
        )
    history_entries = []
    question_number = 1
    for round_index, round_data in enumerate(restored_data.rounds[:2]):
        for question in round_data.questions:
            history_entries.append(
                {
                    "question_index": [round_index, list(question.index)],
                    "question_number": question_number,
                    "round_index": round_index,
                    "category": question.category,
                    "value": question.value,
                    "is_daily_double": question.dd,
                    "buzz_phases": [],
                    "answer_attempts": [],
                    "completed_at": 1700000000.0 + question_number,
                }
            )
            question_number += 1
    with (saved_dir / "question_history.jsonl").open("w") as f:
        for entry in history_entries:
            json.dump(entry, f)
            f.write("\n")
    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()
    assert isinstance(game.current_round, FinalBoard)
    assert game.active_question is game.current_round.question
    assert game.buzzer_controller.open_wagers_calls


def test_resume_finished_board_without_final_can_end_game(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Resuming a fully played board with no Final should let Space end the game."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved-finished-no-final"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as f:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "selected_round_indices": [0],
            },
            f,
        )
    with (saved_dir / "question_history.jsonl").open("w") as f:
        for question_number, question in enumerate(
            restored_data.rounds[0].questions, start=1
        ):
            json.dump(
                {
                    "question_index": [0, list(question.index)],
                    "question_number": question_number,
                    "round_index": 0,
                    "category": question.category,
                    "value": question.value,
                    "is_daily_double": question.dd,
                    "buzz_phases": [],
                    "answer_attempts": [],
                    "completed_at": 1700000000.0 + question_number,
                },
                f,
            )
            f.write("\n")

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    assert game.current_round is game.data.rounds[0]
    events = game.keystroke_manager._KeystrokeManager__events
    assert events["NEXT_ROUND"].active is True
    game.keystroke_manager.call(Qt.Key.Key_Space)
    assert events["GENERATE_GRAPHS"].active is True


def test_resume_after_final_goes_to_end_of_game(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Resuming a save whose Final was judged must not reopen wagering."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved-after-final"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as f:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
            },
            f,
        )
    history_entries = []
    for round_index, round_data in enumerate(restored_data.rounds):
        for question in round_data.questions:
            history_entries.append(
                {
                    "question_index": [round_index, list(question.index)],
                    "question_number": len(history_entries) + 1,
                    "round_index": round_index,
                    "category": question.category,
                    "value": question.value,
                    "is_daily_double": question.dd,
                    "buzz_phases": [],
                    "answer_attempts": [],
                    "completed_at": 1700000000.0 + len(history_entries),
                }
            )
    # Bob wagered 300 on Final and got it right.
    history_entries[-1]["answer_attempts"] = [
        {
            "player_index": 1,
            "answer_correct": True,
            "score_before": 0,
            "score_after": 300,
        }
    ]
    with (saved_dir / "question_history.jsonl").open("w") as f:
        for entry in history_entries:
            json.dump(entry, f)
            f.write("\n")

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    assert isinstance(game.current_round, FinalBoard)
    assert not game.buzzer_controller.open_wagers_calls
    assert game.dc.loaded_final_judgement == 1
    assert game.dc.final_window.winner is players[1]
    events = game.keystroke_manager._KeystrokeManager__events
    assert events["GENERATE_GRAPHS"].active is True
    history_lines = (saved_dir / "question_history.jsonl").read_text().splitlines()
    assert len(history_lines) == len(history_entries)


def test_resume_skips_deselected_rounds_when_advancing(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Resumed standard games should honor saved round selections."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved-selected-rounds"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as f:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "selected_round_indices": [0, 2],
            },
            f,
        )
    with (saved_dir / "question_history.jsonl").open("w") as f:
        f.write("")

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    assert game.current_round is game.data.rounds[0]
    game.next_round()
    assert isinstance(game.current_round, FinalBoard)


def test_resume_subset_save_uses_original_round_indices(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Subset saves should resume against original round indices, read-only."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved-double-and-final"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as f:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "selected_round_indices": [1, 2],
            },
            f,
        )
    with (saved_dir / "question_history.jsonl").open("w") as f:
        json.dump(
            {
                "question_index": [1, [0, 0]],
                "question_number": 1,
                "round_index": 1,
                "category": "Cat 0",
                "value": 400,
                "is_daily_double": False,
                "buzz_phases": [
                    {
                        "phase_type": "main",
                        "buzz_attempts": [
                            {
                                "player_index": 0,
                                "question_index": [1, [0, 0]],
                                "timestamp": 1.0,
                                "is_early": False,
                                "is_success": True,
                                "is_rebound": False,
                                "in_timeout": False,
                            }
                        ],
                    }
                ],
                "answer_attempts": [],
                "completed_at": 2.0,
            },
            f,
        )
        f.write("\n")

    history_file = saved_dir / "question_history.jsonl"
    history_before = history_file.read_bytes()
    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    assert len(game.data.rounds) == 3
    assert game.selected_round_indices() == [1, 2]
    assert game.current_round is game.data.rounds[1]
    assert game.data.rounds[1].get_question(0, 0).complete is True
    assert game.data.rounds[0].get_question(0, 0).complete is False
    assert history_file.read_bytes() == history_before


def test_resume_same_game_subset_board_selections_keep_original_round_list(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Same-game subset saves should resume against the full original round list."""
    from jparty.services import game_loader

    restored_data = deepcopy(game.data)
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved-board-subset"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as file_obj:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "selected_round_indices": [1, 2],
                "board_selections": [
                    {
                        "game_id": "4453",
                        "source_round_index": 1,
                        "source_round_label": "Double Jeopardy!",
                        "board_type": "standard",
                        "row_values": [400, 800, 1200, 1600, 2000],
                    },
                    {
                        "game_id": "4453",
                        "source_round_index": 2,
                        "source_round_label": "Final Jeopardy!",
                        "board_type": "final",
                        "row_values": [],
                    },
                ],
                "history_round_indices_original": False,
            },
            file_obj,
        )
    with (saved_dir / "question_history.jsonl").open("w") as file_obj:
        json.dump(
            {
                "question_index": [1, [0, 0]],
                "question_number": 1,
                "round_index": 1,
                "category": restored_data.rounds[1].questions[0].category,
                "value": 400,
                "is_daily_double": False,
                "buzz_phases": [],
                "answer_attempts": [],
                "completed_at": 2.0,
            },
            file_obj,
        )
        file_obj.write("\n")

    history_file = saved_dir / "question_history.jsonl"
    history_before = history_file.read_bytes()
    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    assert len(game.data.rounds) == 3
    assert game.selected_round_indices() == [1, 2]
    assert game.current_round is game.data.rounds[1]
    assert game.data.rounds[1].get_question(0, 0).complete is True
    assert game.data.rounds[0].get_question(0, 0).complete is False
    assert history_file.read_bytes() == history_before


def test_resume_preserves_frankenstein_board_selections_and_round_sources(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Resuming a mixed-source game should not collapse it to one source board."""
    from jparty.services import game_loader

    source_a = deepcopy(game.data)
    source_b = deepcopy(game.data)
    source_a.date = "January 1, 2026"
    source_b.date = "January 2, 2026"
    source_a.comments = "Source A"
    source_b.comments = "Source B"
    source_a.rounds[0].categories[0] = "A Category"
    source_a.rounds[0].questions[0].text = "A Jeopardy clue"
    source_a.rounds[2].category = "A Final Category"
    source_b.rounds[1].categories[0] = "B Category"
    source_b.rounds[1].questions[0].text = "B Double Jeopardy clue"
    monkeypatch.setattr(
        game_loader,
        "get_game",
        lambda game_id: {"111": source_a, "222": source_b}[game_id],
    )

    board_selections = [
        {
            "game_id": "111",
            "source_round_index": 0,
            "source_round_label": "Jeopardy!",
            "board_type": "standard",
            "row_values": [200, 400, 600, 800, 1000],
        },
        {
            "game_id": "222",
            "source_round_index": 1,
            "source_round_label": "Double Jeopardy!",
            "board_type": "standard",
            "row_values": [400, 800, 1200, 1600, 2000],
        },
        {
            "game_id": "111",
            "source_round_index": 2,
            "source_round_label": "Final Jeopardy!",
            "board_type": "final",
            "row_values": [],
        },
    ]
    saved_dir = temp_dir / "mixed_saved"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as file_obj:
        json.dump(
            {
                "game_id": "frankenstein-111-222-111",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "selected_round_indices": [0, 1, 2],
                "board_selections": board_selections,
                "started_at": 1700000000.0,
                "last_updated": 1700000300.0,
            },
            file_obj,
        )
    with (saved_dir / "question_history.jsonl").open("w") as file_obj:
        json.dump(
            {
                "question_index": [0, [0, 0]],
                "question_number": 1,
                "round_index": 0,
                "category": "A Category",
                "value": 200,
                "is_daily_double": False,
                "buzz_phases": [],
                "answer_attempts": [],
                "completed_at": 1700000001.0,
            },
            file_obj,
        )
        file_obj.write("\n")

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    rewritten_general = json.loads((saved_dir / "general.json").read_text())
    assert [
        selection["game_id"] for selection in rewritten_general["board_selections"]
    ] == [
        "111",
        "222",
        "111",
    ]
    assert game.data.rounds[0].questions[0].text == "A Jeopardy clue"
    assert game.data.rounds[1].questions[0].text == "B Double Jeopardy clue"
    assert game.data.rounds[2].category == "A Final Category"
    assert game.current_round is game.data.rounds[0]


def test_resume_rebuilds_saved_daily_double_locations(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Saved advanced boards should restore their exact Daily Double coords."""
    from jparty.services import game_loader

    restored_data = deepcopy(game.data)
    for question in restored_data.rounds[0].questions:
        question.dd = False
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)

    saved_dir = temp_dir / "saved-daily-doubles"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as file_obj:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "selected_round_indices": [0],
                "board_selections": [
                    {
                        "game_id": "4453",
                        "source_round_index": 0,
                        "source_round_label": "Jeopardy!",
                        "board_type": "standard",
                        "row_values": [200, 400, 600, 800, 1000],
                        "daily_double_count": 2,
                        "daily_double_indices": [[0, 1], [4, 3]],
                    }
                ],
            },
            file_obj,
        )
    with (saved_dir / "question_history.jsonl").open("w") as file_obj:
        file_obj.write("")

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    restored_indices = sorted(
        [
            list(question.index)
            for question in game.data.rounds[0].questions
            if question.dd
        ]
    )
    assert restored_indices == [[0, 1], [4, 3]]


def test_start_game_ignores_a_resume_prepared_for_another_game(
    game: object, monkeypatch: object, sample_saved_game_dir: object
) -> None:
    """A resume for game 4453 must not run, or write, when another game starts."""
    from jparty.services import game_loader

    source = deepcopy(game.data)
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: deepcopy(source))
    monkeypatch.setattr(game, "_save_played_game_html", lambda: None)
    general_before = (sample_saved_game_dir / "general.json").read_bytes()
    history_before = (sample_saved_game_dir / "question_history.jsonl").read_bytes()
    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(sample_saved_game_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    # What advanced mode does after Load Saved: swap in a different board.
    game.set_board_selection_configs(
        [
            {
                "game_id": "9999",
                "source_round_index": 0,
                "source_round_label": "Jeopardy!",
                "board_type": "standard",
                "row_values": [200, 400, 600, 800, 1000],
            }
        ]
    )
    game.set_session_game_id("frankenstein-9999")

    game.start_game()

    assert game._resume_state is None
    assert game._game_state_dir != sample_saved_game_dir
    saved = json.loads((game._game_state_dir / "general.json").read_text())
    assert saved["game_id"] == "frankenstein-9999"
    assert (sample_saved_game_dir / "general.json").read_bytes() == general_before
    assert (
        sample_saved_game_dir / "question_history.jsonl"
    ).read_bytes() == history_before
    assert game.question_number == 1
    assert [player.score for player in game.players] == [0, 0]
    assert not any(question.complete for question in game.data.rounds[0].questions)


def test_close_game_resets_state(game_with_players: object) -> None:
    """Test test close game resets state."""
    game = game_with_players
    game.active_question = game.current_round.get_question(0, 0)
    game.answering_player = game.players[0]
    game.early_buzzes.add(0)
    game.close_game()
    assert game.players == []
    assert game.active_question is None
    assert game.current_round is None
    assert game.question_number == 1
    assert game.buzzer_controller.restart_calls == 1
    assert game.dc.restart_calls == 1


class _RecordingTimer:
    """Stand-in clue timer that records cancels."""

    def __init__(self) -> None:
        """Start with no cancels."""
        self.cancel_calls = 0

    def cancel(self) -> None:
        """Record a cancel."""
        self.cancel_calls += 1


def test_close_game_cancels_timer_and_closes_responses(
    game_with_players: object,
) -> None:
    """Closing mid-clue stops the clue timer instead of leaving it running."""
    game = game_with_players
    timer = _RecordingTimer()
    game.timer = timer
    game.accepting_responses = True

    game.close_game()

    assert timer.cancel_calls == 1
    assert game.timer is None
    assert not game.accepting_responses


def test_stumped_timeout_after_close_game_is_ignored(
    game_with_players: object, monkeypatch: object
) -> None:
    """A clue timeout already on its way when the game closes does nothing."""
    game = game_with_players
    stumped_calls = []
    monkeypatch.setattr(game.clue_flow, "stumped", lambda: stumped_calls.append(1))
    game.accepting_responses = True

    game.close_game()
    game.stumped()

    assert stumped_calls == []


def test_final_timeout_after_close_game_is_ignored(
    game_with_players: object, monkeypatch: object
) -> None:
    """A Final Jeopardy timeout arriving after the game closes does nothing."""
    game = game_with_players
    finished_calls = []
    monkeypatch.setattr(
        game.final_jeopardy_flow, "finished_song", lambda: finished_calls.append(1)
    )
    game.current_round = game.data.rounds[-1]

    game.close_game()
    game.final_finished_song()

    assert finished_calls == []


def test_final_timeout_during_final_jeopardy_still_runs(
    game_with_players: object, monkeypatch: object
) -> None:
    """The Final Jeopardy timeout guard lets the real timeout through."""
    game = game_with_players
    finished_calls = []
    monkeypatch.setattr(
        game.final_jeopardy_flow, "finished_song", lambda: finished_calls.append(1)
    )
    game.current_round = game.data.rounds[-1]

    game.final_finished_song()

    assert finished_calls == [1]


def test_start_game_saves_html_when_play_begins(
    game: object, monkeypatch: object
) -> None:
    """Test test start game saves html when play begins."""
    from jparty.services import archive_client

    saved_game_ids = []
    monkeypatch.setattr(
        archive_client, "save_game_html", lambda game_id: saved_game_ids.append(game_id)
    )
    game.set_session_game_id("4453")
    game.start_game()
    assert saved_game_ids == ["4453"]
    assert game.current_round is game.data.rounds[0]
    assert game.dc.hidden_welcome == 1


def test_start_game_filters_rounds_to_selected_indices(
    game: object, monkeypatch: object
) -> None:
    """Test test start game filters rounds to selected indices."""
    from jparty.services import archive_client

    monkeypatch.setattr(archive_client, "save_game_html", lambda game_id: None)
    game.set_session_game_id("4453")
    game.set_selected_round_indices([0, 2])
    original_final_round = game.data.rounds[2]
    game.start_game()
    assert len(game.data.rounds) == 2
    assert game.data.rounds[1] is original_final_round


def test_next_round_ends_game_when_no_later_round_is_selected(
    game_with_players: object, monkeypatch: object
) -> None:
    """Test test next round ends game when no later round is selected."""
    from jparty.services import archive_client

    game = game_with_players
    monkeypatch.setattr(archive_client, "save_game_html", lambda game_id: None)
    game.set_session_game_id("4453")
    game.set_selected_round_indices([0])
    game.dc.final_window = None
    game.start_game()
    game.next_round()
    assert game.dc.loaded_final_judgement == 1
    assert game.dc.final_window.winner is not None or game.dc.final_window.tie_shown


SUBSET_BOARD_SELECTIONS = [
    {
        "game_id": "4453",
        "source_round_index": 1,
        "source_round_label": "Double Jeopardy!",
        "board_type": "standard",
        "row_values": [400, 800, 1200, 1600, 2000],
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
    "board_selections",
    [None, SUBSET_BOARD_SELECTIONS],
    ids=["regular-mode", "advanced-same-game-subset"],
)
def test_cli_summary_matches_in_app_summary_for_round_subset(
    game: object, monkeypatch: object, temp_dir: object, board_selections: object
) -> None:
    """``jparty summary`` and the app agree on stats for a round-subset save."""
    from jparty.app import bootstrap
    from jparty.domain.state import build_end_game_summary
    from jparty.services import game_loader

    restored_data = deepcopy(game.data)
    monkeypatch.setattr(
        game_loader, "get_game", lambda game_id: deepcopy(restored_data)
    )
    saved_dir = temp_dir / "saved-summary-subset"
    saved_dir.mkdir()
    general_state = {
        "game_id": "4453",
        "players": [
            {"name": "Alice", "player_number": 0},
            {"name": "Bob", "player_number": 1},
        ],
        "selected_round_indices": [1, 2],
    }
    if board_selections is not None:
        general_state["board_selections"] = board_selections
    (saved_dir / "general.json").write_text(json.dumps(general_state))
    (saved_dir / "question_history.jsonl").write_text(
        json.dumps(
            {
                "question_index": [1, [0, 0]],
                "question_number": 1,
                "round_index": 1,
                "category": restored_data.rounds[1].questions[0].category,
                "value": 400,
                "is_daily_double": False,
                "buzz_phases": [],
                "answer_attempts": [
                    {
                        "player_index": 0,
                        "answer_correct": True,
                        "score_before": 0,
                        "score_after": 400,
                    }
                ],
                "completed_at": 2.0,
            }
        )
        + "\n"
    )

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()
    app_summary = build_end_game_summary(game)
    cli_summary = bootstrap.load_summary_from_game_state_directory(saved_dir)

    def player_stats(summary: object) -> dict:
        return {
            player.name: (player.final_score, player.coryat, player.right_count)
            for player in summary.current_players
        }

    assert player_stats(app_summary) == {"Alice": (400, 400, 1), "Bob": (0, 0, 0)}
    assert player_stats(cli_summary) == player_stats(app_summary)
    assert cli_summary.game_stats == app_summary.game_stats
    assert cli_summary.question_count == app_summary.question_count


class _InlineThread:
    """Stand-in for ``threading.Thread`` that runs its target on ``start``."""

    def __init__(self, target: object, daemon: bool = False) -> None:
        """Store the target to run."""
        self._target = target

    def start(self) -> None:
        """Run the target immediately on the calling thread."""
        self._target()


def _source_selection(game_id: str, round_index: int = 0) -> dict:
    """Return one advanced-mode board selection drawing from ``game_id``."""
    return {
        "game_id": game_id,
        "source_round_index": round_index,
        "source_round_label": "Jeopardy!",
        "board_type": "standard",
        "row_values": [200, 400, 600, 800, 1000],
    }


def _start_composed_game(
    game: object, monkeypatch: object, game_ids: list, save_game_html: object
) -> None:
    """Start an advanced-mode game built from ``game_ids`` with saving inlined.

    The composed board is cached up front, so nothing is fetched to build it,
    and ``Thread`` runs inline, so the save step finishes before this returns.
    """
    from jparty.domain import game_engine
    from jparty.services import archive_client

    monkeypatch.setattr(game_engine, "Thread", _InlineThread)
    monkeypatch.setattr(archive_client, "save_game_html", save_game_html)
    configs = [
        _source_selection(game_id, index) for index, game_id in enumerate(game_ids)
    ]
    game.set_board_selection_configs(configs)
    game.set_composed_game_data(configs, deepcopy(game.data))
    game.set_session_game_id("frankenstein-test")
    game.start_game()


def test_start_game_saves_each_selected_source_game(
    game: object, monkeypatch: object
) -> None:
    """Every J-Archive game used by a composed board should be cached."""
    saved = []
    _start_composed_game(game, monkeypatch, ["4453", "5000", "6001"], saved.append)
    assert sorted(saved) == ["4453", "5000", "6001"]


def test_start_game_saves_a_repeated_source_game_once(
    game: object, monkeypatch: object
) -> None:
    """Two boards from the same source game should cache it only once."""
    saved = []
    _start_composed_game(game, monkeypatch, ["4453", "4453", "5000"], saved.append)
    assert sorted(saved) == ["4453", "5000"]


def test_start_game_skips_google_sheet_source_games(
    game: object, monkeypatch: object
) -> None:
    """Google Sheets sources have no J-Archive HTML and are not cached."""
    saved = []
    _start_composed_game(
        game, monkeypatch, ["4453", "1AbCdEfGhIjK", "5000"], saved.append
    )
    assert sorted(saved) == ["4453", "5000"]


def test_start_game_keeps_saving_after_one_source_fails(
    game: object, monkeypatch: object
) -> None:
    """One failed save should not stop the remaining games from being cached."""
    attempted = []
    saved = []

    def flaky_save(game_id: str) -> None:
        """Fail for one game and record the rest."""
        attempted.append(game_id)
        if game_id == "5000":
            raise ConnectionError("offline")
        saved.append(game_id)

    _start_composed_game(game, monkeypatch, ["4453", "5000", "6001"], flaky_save)
    assert sorted(attempted) == ["4453", "5000", "6001"]
    assert sorted(saved) == ["4453", "6001"]
    assert game.current_round is game.data.rounds[0]
