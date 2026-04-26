"""Test special clues module."""

import pytest

pytestmark = pytest.mark.integration


def test_image_question_paths_accept_and_clear_image(game_with_players: object) -> None:
    """Test test image question paths accept and clear image."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    question.image = True
    question.image_url = "http://example.com/image.png"
    game.active_question = question
    game.accept_image()
    assert game.dc.loaded_questions[-1] is question
    question.image = True
    question.image_url = "http://example.com/image.png"
    game.active_question = question
    game.no_image_needed()
    assert question.image is False
    assert question.image_url is None
    assert game.dc.loaded_questions[-1] is question


def test_daily_double_load_and_wager_flow(
    game_with_players: object, monkeypatch: object
) -> None:
    """Test test daily double load and wager flow."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    question.dd = True
    game.players[0].score = 1200
    monkeypatch.setattr(
        "jparty.domain.game_engine.QInputDialog.getInt",
        lambda *args, **kwargs: (700, True),
    )
    game.load_question(question)
    game.get_dd_wager(game.players[0])
    assert game.soliciting_player is False
    assert question.value == 700
    assert game.dc.question_widget.show_question_calls == 1
    assert (
        game.keystroke_manager._KeystrokeManager__events["OPEN_RESPONSES"].active
        is False
    )
    assert (
        game.keystroke_manager._KeystrokeManager__events["CORRECT_ANSWER"].active
        is True
    )


def test_daily_double_incorrect_returns_to_board(game_with_players: object) -> None:
    """Test test daily double incorrect returns to board."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    question.dd = True
    game.load_question(question)
    game.answering_player = game.players[0]
    game.incorrect_answer()
    assert question.complete is True
    assert game.active_question is None


def test_start_final_opens_wagers_and_lights_players(game_with_players: object) -> None:
    """Test test start final opens wagers and lights players."""
    game = game_with_players
    game.current_round = game.data.rounds[2]
    game.start_final()
    assert game.buzzer_controller.open_wagers_calls
    for player in game.players:
        assert game.dc.player_widget(player).set_lights_values[-1] is True


def test_final_judgement_order_blank_answer_and_scoring(
    game_with_players: object,
) -> None:
    """Test test final judgement order blank answer and scoring."""
    game = game_with_players
    game.current_round = game.data.rounds[2]
    game.players[0].score = 800
    game.players[1].score = 400
    game.players[2].score = 1200
    game.players[0].wager = 200
    game.players[1].wager = 400
    game.players[2].wager = 100
    game.players[0].finalanswer = ""
    game.players[1].finalanswer = "Paris"
    game.players[2].finalanswer = "Rome"
    game.final_next_player()
    assert game.answering_player is game.players[1]
    game.final_show_answer()
    assert game.dc.final_window.guess_label.text == "Paris"
    game.final_incorrect_answer()
    assert game.players[1].score == 0
    game.final_next_player()
    assert game.answering_player is game.players[0]
    game.final_show_answer()
    assert game.dc.final_window.guess_label.text == "________"
    game.final_correct_answer()
    assert game.players[0].score == 1000


def test_end_game_handles_tie_and_single_winner(game_with_players: object) -> None:
    """Test test end game handles tie and single winner."""
    game = game_with_players
    game.players[0].score = 1000
    game.players[1].score = 1000
    game.players[2].score = 200
    game.end_game()
    assert game.dc.final_window.tie_shown is True
    game.dc.final_window.tie_shown = False
    game.players[1].score = 500
    game.end_game()
    assert game.dc.final_window.winner is game.players[0]


def test_generate_end_game_summary_loads_audience_display(
    game_with_players: object,
) -> None:
    """Test post-winner action loads the audience end-game summary."""
    game = game_with_players
    game.players[0].score = 1200
    game.players[1].score = 600
    game._save_general_state()
    game.end_game()
    game.generate_final_score_graphs()
    assert len(game.main_display.loaded_end_game_summaries) == 1
