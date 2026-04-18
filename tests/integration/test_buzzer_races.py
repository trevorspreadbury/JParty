import pytest


pytestmark = pytest.mark.integration


def test_early_buzz_adds_player_to_penalty(game_with_players):
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)

    game.buzz(0)

    assert 0 in game.early_buzzes
    assert game._all_buzz_attempts[-1].is_early is True
    assert game.answering_player is None


def test_penalized_player_is_ignored_during_timeout_but_other_player_can_win(game_with_players, time_controller):
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.buzz(0)
    game.open_responses()

    game.buzz(0)

    assert game.answering_player is None
    assert game._all_buzz_attempts[-1].in_timeout is True

    game.buzz(1)

    assert game.answering_player is game.players[1]
    assert game.accepting_responses is False


def test_previous_answerer_cannot_buzz_again_same_clue(game_with_players):
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.open_responses()
    game.buzz(0)
    attempts = len(game._all_buzz_attempts)

    game.buzz(0)

    assert len(game._all_buzz_attempts) == attempts
    assert game.answering_player is game.players[0]


def test_winning_buzz_updates_lectern_state(game_with_players):
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.open_responses()

    game.buzz(1)

    player_number, state = game.buzzer_controller.broadcasts[-1]
    assert player_number == 1
    assert state["buzzed"] is True
    assert state["active"] is True
