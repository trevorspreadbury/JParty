"""Test game resume and logging module."""

import json
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
