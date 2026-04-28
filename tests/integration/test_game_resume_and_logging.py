"""Test game resume and logging module."""

import json
from copy import deepcopy

import pytest
from jparty.domain.models import FinalBoard, Player

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


def test_resume_normalizes_saved_subset_round_indices_to_original_game(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Subset saves should resume against the original round identities."""
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
                "question_index": [0, [0, 0]],
                "question_number": 1,
                "round_index": 0,
                "category": "Cat 0",
                "value": 400,
                "is_daily_double": False,
                "buzz_phases": [
                    {
                        "phase_type": "main",
                        "buzz_attempts": [
                            {
                                "player_index": 0,
                                "question_index": [0, [0, 0]],
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

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    rewritten_general = json.loads((saved_dir / "general.json").read_text())
    rewritten_history = [
        json.loads(line)
        for line in (saved_dir / "question_history.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(game.data.rounds) == 3
    assert game.selected_round_indices() == [1, 2]
    assert game.current_round is game.data.rounds[1]
    assert game.data.rounds[1].get_question(0, 0).complete is True
    assert game.data.rounds[0].get_question(0, 0).complete is False
    assert rewritten_general["history_round_indices_original"] is True
    assert rewritten_history[0]["round_index"] == 1
    assert rewritten_history[0]["question_index"][0] == 1
    assert (
        rewritten_history[0]["buzz_phases"][0]["buzz_attempts"][0]["question_index"][0]
        == 1
    )


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
                "question_index": [0, [0, 0]],
                "question_number": 1,
                "round_index": 0,
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

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    rewritten_general = json.loads((saved_dir / "general.json").read_text())
    rewritten_history = [
        json.loads(line)
        for line in (saved_dir / "question_history.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(game.data.rounds) == 3
    assert game.selected_round_indices() == [1, 2]
    assert game.current_round is game.data.rounds[1]
    assert game.data.rounds[1].get_question(0, 0).complete is True
    assert game.data.rounds[0].get_question(0, 0).complete is False
    assert rewritten_general["history_round_indices_original"] is True
    assert rewritten_history[0]["round_index"] == 1
    assert rewritten_history[0]["question_index"][0] == 1


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


def test_start_game_saves_html_when_play_begins(
    game: object, monkeypatch: object
) -> None:
    """Test test start game saves html when play begins."""
    from jparty.services import archive_client

    saved_game_ids = []
    monkeypatch.setattr(
        archive_client, "save_game_html", lambda game_id: saved_game_ids.append(game_id)
    )
    monkeypatch.setenv("JPARTY_GAME_ID", "4453")
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
    monkeypatch.setenv("JPARTY_GAME_ID", "4453")
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
    monkeypatch.setenv("JPARTY_GAME_ID", "4453")
    game.set_selected_round_indices([0])
    game.dc.final_window = None
    game.start_game()
    game.next_round()
    assert game.dc.loaded_final_judgement == 1
    assert game.dc.final_window.winner is not None or game.dc.final_window.tie_shown
