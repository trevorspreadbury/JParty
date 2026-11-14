"""Test buzzer races module."""

import json

import pytest

from jparty.domain.state import build_end_game_summary

pytestmark = pytest.mark.integration


def test_early_buzz_adds_player_to_penalty(game_with_players: object) -> None:
    """Test test early buzz adds player to penalty."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.buzz(0)
    assert 0 in game.early_buzzes
    assert game._all_buzz_attempts[-1].is_early is True
    assert game.answering_player is None


def test_penalized_player_is_ignored_during_timeout_but_other_player_can_win(
    game_with_players: object, time_controller: object
) -> None:
    """Test test penalized player is ignored during timeout but other player can win."""
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


def test_previous_answerer_cannot_buzz_again_same_clue(
    game_with_players: object,
) -> None:
    """Test test previous answerer cannot buzz again same clue."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.open_responses()
    game.buzz(0)
    attempts = len(game._all_buzz_attempts)
    game.buzz(0)
    assert len(game._all_buzz_attempts) == attempts
    assert game.answering_player is game.players[0]


def test_winning_buzz_updates_lectern_state(game_with_players: object) -> None:
    """Test test winning buzz updates lectern state."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.open_responses()
    game.buzz(1)
    (player_number, state) = game.buzzer_controller.broadcasts[-1]
    assert player_number == 1
    assert state["buzzed"] is True
    assert state["active"] is True


def test_invalid_player_index_buzz_is_ignored(game_with_players: object) -> None:
    """Test out-of-range buzz indexes do not crash the game."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.open_responses()

    game.buzz(len(game.players))

    assert game.answering_player is None
    assert game.accepting_responses is True
    assert game._all_buzz_attempts == []


def test_early_buzz_penalty_does_not_carry_into_rebound(
    game_with_players: object, time_controller: object
) -> None:
    """A player who buzzed early can buzz at once when a rebound opens."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.buzz(0)
    game.open_responses()
    time_controller.advance(1.0)
    game.buzz(1)
    game.incorrect_answer()

    game.buzz(0)

    assert game.answering_player is game.players[0]
    assert game._all_buzz_attempts[-1].in_timeout is False


def _player_stats(game: object) -> dict:
    """Return the end-of-game stats for each player, keyed by player number."""
    summary = build_end_game_summary(game)
    return summary, {player.player_number: player for player in summary.current_players}


def test_buzz_after_the_clue_times_out_is_not_an_early_buzz(
    game_with_players: object, time_controller: object
) -> None:
    """A buzz after time runs out is late, so the stats must not call it early."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.open_responses()
    time_controller.advance(5.0)
    game.stumped()
    time_controller.advance(0.5)

    game.buzz(1)

    assert 1 not in game.early_buzzes
    assert not any(attempt.is_early for attempt in game._all_buzz_attempts)
    game.back_to_board()
    _, stats = _player_stats(game)
    assert stats[1].early_buzzes == 0
    assert stats[1].questions_buzzed_on == 0


def test_early_buzz_before_responses_open_still_counts(
    game_with_players: object, time_controller: object
) -> None:
    """Buzzing before responses open is still an early buzz in the stats."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    game.buzz(1)
    time_controller.advance(1.0)
    game.open_responses()
    time_controller.advance(5.0)
    game.stumped()
    game.back_to_board()

    _, stats = _player_stats(game)

    assert stats[1].early_buzzes == 1
    assert stats[1].questions_buzzed_on == 1


def test_quick_ruling_does_not_overlap_main_and_rebound_windows(
    game_with_players: object, time_controller: object
) -> None:
    """A ruling 0.6 s after the buzz keeps each buzz in exactly one window.

    The player who answered wrong is locked out of the rebound, so they get
    no rebound race, and the clue has exactly two buzzer races.
    """
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    time_controller.advance(1.0)
    game.open_responses()
    time_controller.advance(0.5)
    game.buzz(0)
    time_controller.advance(0.1)
    game.buzz(1)
    time_controller.advance(0.5)
    game.incorrect_answer()
    time_controller.advance(0.2)
    game.buzz(1)
    time_controller.advance(0.1)
    game.buzz(2)
    time_controller.advance(3.0)
    game.correct_answer()

    phases = json.loads(
        (game._game_state_dir / "question_history.jsonl").read_text().splitlines()[0]
    )["buzz_phases"]
    summary, stats = _player_stats(game)

    assert [
        [attempt["player_index"] for attempt in phase["buzz_attempts"]]
        for phase in phases
    ] == [[0, 1], [1, 2]]
    assert phases[0]["end_time"] <= phases[1]["start_time"]
    assert summary.game_stats.buzzer_races == 2
    assert stats[0].race_opportunities == 1
    assert stats[1].race_opportunities == 2
    assert stats[2].race_opportunities == 1


def test_race_winner_survives_a_correction_to_no_answer(
    game_with_players: object, time_controller: object
) -> None:
    """Who won a buzzer race doesn't change when the host corrects the ruling.

    Player 0 wins the main race and answers wrong; player 1 wins the rebound
    race. Changing player 0 to "no answer" must not hand the main race to
    player 1.
    """
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    time_controller.advance(1.0)
    game.open_responses()
    time_controller.advance(0.5)
    game.buzz(0)
    time_controller.advance(0.1)
    game.buzz(1)
    time_controller.advance(3.0)
    game.incorrect_answer()
    time_controller.advance(0.5)
    game.buzz(1)
    time_controller.advance(0.1)
    game.buzz(2)
    time_controller.advance(3.0)
    game.correct_answer()

    game.apply_question_history_corrections(
        [
            {
                "question_number": 1,
                "player_states": {0: "no answer", 1: "correct", 2: "no answer"},
                "value": question.value,
            }
        ]
    )
    _, stats = _player_stats(game)

    assert stats[0].race_wins == 1
    assert stats[1].race_wins == 1
    assert stats[1].race_opportunities == 2
