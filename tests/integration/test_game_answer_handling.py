"""Test game answer handling module."""

import json

import pytest

pytestmark = pytest.mark.integration


def test_incorrect_answer_subtracts_logs_and_reopens_for_other_players(
    game_with_players: object,
) -> None:
    """Test test incorrect answer subtracts logs and reopens for other players."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.open_responses()
    game.buzz(0)
    game.incorrect_answer()
    assert game.players[0].score == -question.value
    assert game.answering_player is None
    assert game.accepting_responses is True
    assert game._answer_attempts[-1]["answer_correct"] is False
    assert game._answer_attempts[-1]["score_after"] == -question.value
    game.buzz(1)
    assert game.answering_player is game.players[1]


def test_correct_answer_returns_to_board_logs_and_adds_score(
    game_with_players: object,
) -> None:
    """Test test correct answer returns to board logs and adds score."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.open_responses()
    game.buzz(0)
    game.correct_answer()
    assert game.players[0].score == question.value
    assert game.active_question is None
    assert question.complete is True
    assert game.question_number == 2
    history_file = game._game_state_dir / "question_history.jsonl"
    lines = [json.loads(line) for line in history_file.read_text().splitlines()]
    assert len(lines) == 1
    assert lines[0]["answer_attempts"][0]["score_after"] == question.value


def test_stumped_closes_responses_and_enables_return_to_board(
    game_with_players: object,
) -> None:
    """Test test stumped closes responses and enables return to board."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.open_responses()
    game.stumped()
    assert game.accepting_responses is False
    assert game.dc.borders.flash_calls == 1
    assert (
        game.keystroke_manager._KeystrokeManager__events["BACK_TO_BOARD"].active is True
    )


def test_set_score_updates_widget_and_lectern_state(game_with_players: object) -> None:
    """Test test set score updates widget and lectern state."""
    game = game_with_players
    player = game.players[0]
    game.set_score(player, 600)
    assert player.score == 600
    assert game.dc.player_widget(player).update_score_calls == 1
    assert game.buzzer_controller.broadcasts[-1][0] == player.player_number
