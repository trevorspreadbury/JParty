"""Tests for the robot host moving the game on: next round and Final Jeopardy.

``robot_game`` (in conftest) holds each delayed step in ``game.delayed``
until the test runs it.
"""

import json

import pytest
from PyQt6.QtCore import Qt

from jparty.domain.models import FinalBoard
from jparty.domain.robot_host import (
    FINAL_STEP_PAUSE_MS,
    FINAL_WAGER_TIMEOUT_MS,
    ROUND_PAUSE_MS,
)

pytestmark = pytest.mark.integration


def _run_delayed(game: object) -> list[int]:
    """Run every step waiting so far, oldest first; return their delays."""
    waiting, game.delayed = game.delayed, []
    for _delay, callback in waiting:
        callback()
    return [delay for delay, _ in waiting]


def _active(game: object, ident: str) -> bool:
    """Return whether keystroke event ``ident`` is waiting for its key."""
    return game.keystroke_manager.is_active(ident)


def _clear_all_but_one(game: object) -> object:
    """Mark every clue on the board played but one; return that one."""
    last = game.current_round.get_question(5, 4)
    for question in game.current_round.questions:
        question.complete = question is not last
    return last


def _play_last_clue(game: object) -> None:
    """Pick the board's last clue and have seat 1 get it right."""
    last = _clear_all_but_one(game)
    in_control = game.players.index(game.player_in_control)
    game.phone_pick(in_control, 5, 4)
    game.clue_reader.speaker.finish()
    game.buzz(0)
    game.listener.hear(f"What is {last.answer}?")


def test_cleared_board_moves_to_the_next_round(robot_game: object) -> None:
    """After the last clue, the end is announced and the next round starts."""
    game = robot_game
    game.start_game()
    for player, score in zip(game.players, [0, -200, 400]):
        player.score = score
    _play_last_clue(game)
    assert _active(game, "NEXT_ROUND")

    delays = _run_delayed(game)

    assert ROUND_PAUSE_MS in delays
    said = game.clue_reader.speaker.said
    assert said[-2:] == ["Correct.", "That's the end of the round."]
    assert game.current_round is game.data.rounds[1]
    # Seat 1 just scored, so Bob trails and picks first.
    assert game.buzzer_controller.picks_offered[-1][0] is game.players[1]


def test_host_moving_on_first_is_not_overridden(robot_game: object) -> None:
    """A host who presses space during the pause moves on just once."""
    game = robot_game
    game.start_game()
    _play_last_clue(game)
    game.keystroke_manager.call(Qt.Key.Key_Space)
    assert game.current_round is game.data.rounds[1]

    _run_delayed(game)

    assert game.current_round is game.data.rounds[1]


def test_turning_the_robot_host_off_cancels_the_next_step(robot_game: object) -> None:
    """A step waiting when the robot host is turned off doesn't fire."""
    game = robot_game
    game.start_game()
    _play_last_clue(game)
    game.set_robot_host(False)

    _run_delayed(game)

    assert game.current_round is game.data.rounds[0]
    assert _active(game, "NEXT_ROUND")


@pytest.fixture()
def final_game(robot_game: object) -> object:
    """Return a game that has just reached Final with Alice, Bob and Cara."""
    game = robot_game
    game.start_game()
    for player, score in zip(game.players, [1000, 600, 200]):
        player.score = score
    game.current_round = game.data.rounds[1]
    for question in game.current_round.questions:
        question.complete = True
    game.next_round()
    assert isinstance(game.current_round, FinalBoard)
    return game


def test_final_reads_the_category_and_opens_once_wagers_are_in(
    final_game: object,
) -> None:
    """Wagers come from phones; the clue opens a moment after the last one."""
    game = final_game
    assert game.clue_reader.speaker.said[-1] == (
        "The Final Jeopardy category is Final Category. Make your wagers."
    )
    for i_player, amount in enumerate([500, 600, 0]):
        game.wager(i_player, amount)
    assert game.delayed[-1][0] == FINAL_STEP_PAUSE_MS

    _run_delayed(game)

    assert game.dc.question_widget.show_question_calls == 1
    assert game.clue_reader.speaker.said[-1] == "Final clue"
    game.clue_reader.speaker.finish()
    assert game.song_player.final_calls == 1


def test_final_opens_without_a_missing_wager_in_time(final_game: object) -> None:
    """A phone that never wagers can't stall Final; its wager counts as $0."""
    game = final_game
    game.wager(0, 500)
    [(delay, timeout)] = game.delayed

    timeout()

    assert delay == FINAL_WAGER_TIMEOUT_MS
    assert [player.wager for player in game.players] == [500, 0, 0]
    assert game.dc.question_widget.show_question_calls == 1


def _play_final(game: object, answers: list[str]) -> None:
    """Wager, read the clue, run the music out and fill in typed answers."""
    for i_player, amount in enumerate([500, 600, 200]):
        game.wager(i_player, amount)
    _run_delayed(game)
    game.clue_reader.speaker.finish()
    for player, answer in zip(game.players, answers):
        player.finalanswer = answer
    game.final_finished_song()


def test_final_answers_are_revealed_and_ruled_in_turn(final_game: object) -> None:
    """Lowest score first, each typed answer is shown and ruled."""
    game = final_game
    _play_final(game, ["What is Final response?", "Who is Nobody?", ""])

    # Each run reveals the next answer, then moves to the next player.
    for _ in range(7):
        _run_delayed(game)

    assert [player.score for player in game.players] == [1500, 0, 0]
    assert _active(game, "GENERATE_GRAPHS")
    assert game.delayed and game.delayed[-1][0] == FINAL_STEP_PAUSE_MS
    history_file = game._game_state_dir / "question_history.jsonl"
    final_entry = json.loads(history_file.read_text().splitlines()[-1])
    rulings = [a["ruled_by"] for a in final_entry["answer_attempts"]]
    assert rulings == ["robot", "robot", "robot"]


def test_unsure_final_answer_waits_for_the_host(final_game: object) -> None:
    """When the judge can't tell, the host's arrow key rules."""
    game = final_game
    _play_final(game, ["What is Final?", "What is Final response?", ""])
    _run_delayed(game)  # To the first player: Cara, lowest score.
    _run_delayed(game)  # Cara's blank answer is wrong.
    _run_delayed(game)  # To Bob.
    _run_delayed(game)  # Bob is right.
    _run_delayed(game)  # To Alice.
    _run_delayed(game)  # Alice's "Final" is unsure.

    assert _active(game, "FINAL_CORRECT_ANSWER")
    assert game.delayed == []
    game.keystroke_manager.call(Qt.Key.Key_Left)
    assert game.players[0].score == 1500
    assert "ruled_by" not in game._answer_attempts[-1]
