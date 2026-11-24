"""Tests for the robot host's answer loop: listen, rule, move on.

The game fixture fakes the voice (``FakeSpeaker``); ``robot_game`` (in
conftest) also fakes speech-to-text with ``FakeListener`` and holds delayed
steps until run.
"""

import json

import pytest
from PyQt6.QtCore import Qt

from jparty.domain.judging import Ruling
from jparty.domain.robot_host import STUMPED_PAUSE_MS
from tests.conftest import FakeListener

pytestmark = pytest.mark.integration


def _clue(game: object, answer: str = "Abraham Lincoln") -> object:
    """Return a fresh clue from the first board with ``answer``."""
    question = game.current_round.get_question(0, 0)
    question.answer = answer
    return question


def _show_and_open(game: object, question: object) -> None:
    """Show ``question`` and let the voice finish reading it."""
    game.load_question(question)
    game.clue_reader.speaker.finish()
    assert game.accepting_responses is True


def _active(game: object, ident: str) -> bool:
    """Return whether keystroke event ``ident`` is waiting for its key."""
    return game.keystroke_manager.is_active(ident)


def _history(game: object) -> list[dict]:
    """Return the saved question history lines."""
    path = game._game_state_dir / "question_history.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_robot_host_needs_a_listener(game_with_players: object) -> None:
    """Without speech-to-text the robot host stays off."""
    game = game_with_players
    assert game.set_robot_host(True) is False
    assert game.robot_host_enabled() is False
    assert game.read_clues_aloud_enabled() is False


def test_turning_the_robot_host_on_reads_clues_aloud(robot_game: object) -> None:
    """The robot host relies on the clue reader to open responses."""
    assert robot_game.read_clues_aloud_enabled() is True
    robot_game.set_robot_host(False)
    assert robot_game.read_clues_aloud_enabled() is True


def test_correct_response_scores_and_returns_to_the_board(robot_game: object) -> None:
    """The full loop: read, open, buzz, listen, rule correct, back to board."""
    game = robot_game
    question = _clue(game)
    _show_and_open(game, question)

    game.buzz(0)
    assert game.listener.listening
    game.listener.hear("Who is Abraham Lincoln?")

    assert game.players[0].score == question.value
    assert game.active_question is None
    assert question.complete is True
    assert game.clue_reader.speaker.said[-1] == "Correct."
    attempt = _history(game)[-1]["answer_attempts"][0]
    assert attempt["answer_correct"] is True
    assert attempt["transcript"] == "Who is Abraham Lincoln?"
    assert attempt["ruled_by"] == "robot"


def test_wrong_response_reopens_for_the_others(robot_game: object) -> None:
    """A wrong response costs the clue's value and reopens the buzzers."""
    game = robot_game
    game.robot_host.judge = lambda question, heard: Ruling.INCORRECT
    question = _clue(game)
    _show_and_open(game, question)

    game.buzz(0)
    game.listener.hear("Who is Washington?")

    assert game.players[0].score == -question.value
    assert game.accepting_responses is True
    assert game.clue_reader.speaker.said[-1] == "No."
    game.buzz(0)  # Already answered.
    assert game.answering_player is None
    game.buzz(1)
    assert game.answering_player is game.players[1]
    assert game.listener.listening


def test_saying_nothing_in_time_is_wrong(robot_game: object) -> None:
    """No transcript is ruled wrong without asking the judge."""
    game = robot_game
    game.robot_host.judge = lambda question, heard: pytest.fail("judge called")
    question = _clue(game)
    _show_and_open(game, question)

    game.buzz(0)
    game.listener.hear(None)

    assert game.players[0].score == -question.value
    assert game._answer_attempts[-1]["transcript"] == ""
    assert game._answer_attempts[-1]["ruled_by"] == "robot"


def test_unsure_ruling_is_left_to_the_host(robot_game: object) -> None:
    """When the judge can't tell, the host's arrow key rules."""
    game = robot_game
    question = _clue(game)
    _show_and_open(game, question)
    game.buzz(0)

    game.listener.hear("Lincoln")

    assert game.answering_player is game.players[0]
    assert game.players[0].score == 0
    assert _active(game, "CORRECT_ANSWER")
    game.keystroke_manager.call(Qt.Key.Key_Left)
    assert game.players[0].score == question.value
    attempt = _history(game)[-1]["answer_attempts"][0]
    assert attempt["transcript"] == "Lincoln"
    assert "ruled_by" not in attempt


def test_host_ruling_while_listening_stops_the_robot(robot_game: object) -> None:
    """An arrow key rules at once; a response heard afterwards is dropped."""
    game = robot_game
    question = _clue(game)
    _show_and_open(game, question)
    game.buzz(0)
    late = game.listener.on_heard

    game.keystroke_manager.call(Qt.Key.Key_Right)

    assert not game.listener.listening
    assert game.players[0].score == -question.value
    late("Who is Abraham Lincoln?")
    assert game.players[0].score == -question.value
    assert "ruled_by" not in game._answer_attempts[-1]


def test_response_for_an_earlier_buzz_is_dropped(robot_game: object) -> None:
    """After a rebound, the first player's late response can't rule."""
    game = robot_game
    game.robot_host.judge = lambda question, heard: Ruling.INCORRECT
    question = _clue(game)
    _show_and_open(game, question)
    game.buzz(0)
    first = game.listener.on_heard
    game.listener.hear("Who is Washington?")
    game.buzz(1)

    first("Who is Abraham Lincoln?")

    assert game.answering_player is game.players[1]
    assert game.players[1].score == 0


def test_listening_cuts_off_the_voice(robot_game: object) -> None:
    """The robot doesn't talk over a player, or record itself."""
    game = robot_game
    game.robot_host.judge = lambda question, heard: Ruling.INCORRECT
    _show_and_open(game, _clue(game))
    game.buzz(0)
    game.listener.hear("Who is Washington?")  # The voice says "No."
    stops = game.clue_reader.speaker.stop_calls

    game.buzz(1)

    assert game.clue_reader.speaker.stop_calls > stops


def test_clue_nobody_gets_returns_to_the_board_after_a_pause(
    robot_game: object,
) -> None:
    """Without the reveal option, the board returns after a short pause."""
    game = robot_game
    question = _clue(game)
    _show_and_open(game, question)

    game.stumped()

    assert game.active_question is question
    [(delay_ms, callback)] = game.delayed
    assert delay_ms == STUMPED_PAUSE_MS
    callback()
    assert game.active_question is None
    assert question.complete is True


def test_pause_that_ends_after_the_host_moved_on_does_nothing(
    robot_game: object,
) -> None:
    """A host who presses Space during the pause isn't overridden later."""
    game = robot_game
    _show_and_open(game, _clue(game))
    game.stumped()
    game.keystroke_manager.call(Qt.Key.Key_Space)
    question_number = game.question_number
    next_clue = game.current_round.get_question(1, 0)
    game.load_question(next_clue)

    game.delayed[0][1]()

    assert game.active_question is next_clue
    assert game.question_number == question_number


def test_revealed_answer_is_read_then_the_board_returns(robot_game: object) -> None:
    """With the reveal option, the answer is shown, read, then the board."""
    game = robot_game
    game.set_reveal_answers_after_triple_stumper(True)
    question = _clue(game, "(Abraham) Lincoln")
    _show_and_open(game, question)

    game.stumped()

    assert game.dc.question_widget.reveal_answer_calls == 1
    assert game.clue_reader.speaker.said[-1] == (
        "The correct response is Abraham Lincoln."
    )
    assert game.active_question is question
    game.clue_reader.speaker.finish()
    assert game.active_question is None


def test_daily_double_is_ruled_after_the_clue_is_read(
    robot_game: object, monkeypatch: object
) -> None:
    """The Daily Double player is listened to once their clue has been read."""
    game = robot_game
    question = _clue(game)
    question.dd = True
    game.players[0].score = 1000
    monkeypatch.setattr(
        "jparty.domain.game_engine.QInputDialog.getInt",
        lambda *args, **kwargs: (800, True),
    )
    game.load_question(question)
    game.get_dd_wager(game.players[0])
    assert not game.listener.listening

    game.clue_reader.speaker.finish()
    assert game.listener.listening
    game.listener.hear("What is Abraham Lincoln")

    assert game.players[0].score == 1800
    assert game.active_question is None


def test_turning_the_robot_host_off_stops_listening(robot_game: object) -> None:
    """A response heard after the robot host is off doesn't rule."""
    game = robot_game
    _show_and_open(game, _clue(game))
    game.buzz(0)
    late = game.listener.on_heard

    game.set_robot_host(False)

    assert not game.listener.listening
    late("Who is Abraham Lincoln?")
    assert game.answering_player is game.players[0]
    assert game.players[0].score == 0


def test_listener_gets_the_answer_as_a_hint(robot_game: object) -> None:
    """Whisper is told the correct response so it spells names that way."""
    game = robot_game
    _show_and_open(game, _clue(game, "(Pyotr) <i>Tchaikovsky</i>"))
    game.buzz(0)
    assert game.listener.hint == "Pyotr Tchaikovsky"


def test_turning_the_robot_host_on_readies_the_listener(robot_game: object) -> None:
    """The speech model starts loading before the first buzz."""
    assert robot_game.listener.prepare_calls == 1


def test_robot_host_creates_its_listener_when_first_turned_on(
    game_with_players: object,
) -> None:
    """The microphone listener is made on demand, not at startup."""
    game = game_with_players
    made = []
    game.create_listener = lambda: made.append(FakeListener()) or made[-1]
    assert game.robot_host_unavailable_reason() == "No microphone in tests."

    assert game.set_robot_host(True) is True
    game.set_robot_host(False)
    game.set_robot_host(True)

    assert len(made) == 1
    assert game.robot_host.listener is made[0]
    assert game.robot_host_unavailable_reason() is None


def test_turning_reading_off_turns_the_robot_host_off(robot_game: object) -> None:
    """The robot host can't run without the clue reader."""
    robot_game.set_read_clues_aloud(False)
    assert robot_game.robot_host_enabled() is False


def test_robot_host_option_is_saved_and_restored(
    robot_game: object, sample_saved_game_dir: object, monkeypatch: object
) -> None:
    """general.json records the option; resume turns it back on if it can."""
    from jparty.services import game_loader

    game = robot_game
    game._save_general_state()
    saved = json.loads((game._game_state_dir / "general.json").read_text())
    assert saved["robot_host"] is True

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    general_file = sample_saved_game_dir / "general.json"
    state = json.loads(general_file.read_text())
    assert "robot_host" not in state
    game.prepare_resume_from_dir(sample_saved_game_dir)
    assert game.robot_host_enabled() is False

    state["robot_host"] = True
    general_file.write_text(json.dumps(state))
    game.prepare_resume_from_dir(sample_saved_game_dir)
    assert game.robot_host_enabled() is True
