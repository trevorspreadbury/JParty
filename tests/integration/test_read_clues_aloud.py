"""Tests for the read-clues-aloud option, the first step toward host-less games.

The game fixture swaps in ``FakeSpeaker``; ``finish()`` stands in for the
voice reaching the end of the text.
"""

import json

import pytest
from PyQt6.QtCore import Qt

pytestmark = pytest.mark.integration


def _active(game: object, ident: str) -> bool:
    """Return whether keystroke event ``ident`` is waiting for its key."""
    return game.keystroke_manager.is_active(ident)


def _space(game: object) -> None:
    """Press Space on the host keyboard."""
    game.keystroke_manager.call(Qt.Key.Key_Space)


@pytest.fixture()
def reading_game(game_with_players: object) -> object:
    """Return a game with reading aloud turned on."""
    game_with_players.set_read_clues_aloud(True)
    return game_with_players


def test_clues_are_not_read_when_the_option_is_off(game_with_players: object) -> None:
    """By default the host reads the clue and presses Space."""
    game = game_with_players
    game.load_question(game.current_round.get_question(0, 0))
    assert game.clue_reader.speaker.said == []
    assert _active(game, "OPEN_RESPONSES")


def test_turning_the_option_on_starts_the_voice(game_with_players: object) -> None:
    """The voice is ready before the first clue, not created on it."""
    game = game_with_players
    game.set_read_clues_aloud(True)
    assert game.clue_reader.speaker.prepare_calls == 1


def test_responses_open_once_the_clue_has_been_read(reading_game: object) -> None:
    """The buzzers open by themselves when the reading ends."""
    game = reading_game
    question = game.current_round.get_question(0, 0)
    question.text = "This <i>Dane</i> said ____"

    game.load_question(question)

    assert game.clue_reader.speaker.said == ["This Dane said blank"]
    assert game.accepting_responses is False
    game.clue_reader.speaker.finish()
    assert game.accepting_responses is True
    assert not _active(game, "OPEN_RESPONSES")
    assert len(game._open_responses_times) == 1
    game.buzz(0)
    assert game.answering_player is game.players[0]


def test_space_while_reading_opens_early_and_stops_the_voice(
    reading_game: object,
) -> None:
    """The host can cut the reading short; it then opens nothing twice."""
    game = reading_game
    game.load_question(game.current_round.get_question(0, 0))
    stops = game.clue_reader.speaker.stop_calls

    _space(game)

    assert game.accepting_responses is True
    assert game.clue_reader.speaker.stop_calls > stops
    game.clue_reader.speaker.finish()
    assert len(game._open_responses_times) == 1


def test_early_buzz_during_reading_is_still_penalised(reading_game: object) -> None:
    """Buzzing before the voice finishes counts as an early buzz."""
    game = reading_game
    game.load_question(game.current_round.get_question(0, 0))
    game.buzz(0)
    assert 0 in game.early_buzzes
    game.clue_reader.speaker.finish()
    assert game.accepting_responses is True


def test_reading_that_ends_after_leaving_the_clue_does_nothing(
    reading_game: object,
) -> None:
    """A late finish must not open responses on a later clue."""
    game = reading_game
    first = game.current_round.get_question(0, 0)
    game.load_question(first)
    callback = game.clue_reader.speaker._on_finished
    game.open_responses()
    game.buzz(0)
    game.correct_answer()
    game.load_question(game.current_round.get_question(1, 0))

    callback()

    assert game.accepting_responses is False
    assert _active(game, "OPEN_RESPONSES")


def test_daily_double_is_read_after_the_wager(
    reading_game: object, monkeypatch: object
) -> None:
    """Nothing is read over the Daily Double screen; the clue is read after."""
    game = reading_game
    question = game.current_round.get_question(0, 0)
    question.dd = True
    monkeypatch.setattr(
        "jparty.domain.game_engine.QInputDialog.getInt",
        lambda *args, **kwargs: (500, True),
    )

    game.load_question(question)
    assert game.clue_reader.speaker.said == []

    game.get_dd_wager(game.players[0])
    assert game.clue_reader.speaker.said == [question.text]
    game.clue_reader.speaker.finish()
    # Only the player who found it answers: no buzzers, host still rules.
    assert game.accepting_responses is False
    assert _active(game, "CORRECT_ANSWER")


def test_final_clue_is_read_then_the_music_starts(reading_game: object) -> None:
    """The think music starts once the Final clue has been read."""
    game = reading_game
    game.current_round = game.data.rounds[2]
    game.active_question = game.current_round.question
    game.start_final()
    for i_player in range(len(game.players)):
        game.wager(i_player, 0)

    _space(game)  # Show the Final clue.

    assert game.clue_reader.speaker.said == [game.active_question.text]
    assert game.song_player.final_calls == 0
    game.clue_reader.speaker.finish()
    assert game.song_player.final_calls == 1
    assert not _active(game, "FINAL_OPEN_RESPONSES")


def test_revealed_answer_is_read(reading_game: object) -> None:
    """With the reveal option on, the correct response is read out."""
    game = reading_game
    game.set_reveal_answers_after_triple_stumper(True)
    question = game.current_round.get_question(0, 0)
    question.answer = "(Abraham) Lincoln"
    game.load_question(question)
    game.clue_reader.speaker.finish()
    game.stumped()

    _space(game)

    assert game.clue_reader.speaker.said[-1] == (
        "The correct response is Abraham Lincoln."
    )
    stops = game.clue_reader.speaker.stop_calls
    _space(game)  # Back to the board cuts the reading off.
    assert game.clue_reader.speaker.stop_calls > stops


def test_turning_the_option_off_stops_reading(reading_game: object) -> None:
    """Turning it off mid-clue leaves the host to open responses."""
    game = reading_game
    game.load_question(game.current_round.get_question(0, 0))
    game.set_read_clues_aloud(False)
    game.clue_reader.speaker.finish()
    assert game.accepting_responses is False
    assert _active(game, "OPEN_RESPONSES")


def _skip_game_download(game: object, monkeypatch: object) -> None:
    """Resume from the fixture's game data instead of J-Archive."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)


def test_option_is_saved_and_restored(
    game: object, players: object, sample_saved_game_dir: object, monkeypatch: object
) -> None:
    """general.json records the option, and resume turns it back on."""
    _skip_game_download(game, monkeypatch)
    game.set_read_clues_aloud(True)
    game._save_general_state()
    saved = json.loads((game._game_state_dir / "general.json").read_text())
    assert saved["read_clues_aloud"] is True

    game.set_read_clues_aloud(False)
    general_file = sample_saved_game_dir / "general.json"
    state = json.loads(general_file.read_text())
    state["read_clues_aloud"] = True
    general_file.write_text(json.dumps(state))
    game.prepare_resume_from_dir(sample_saved_game_dir)
    assert game.read_clues_aloud_enabled() is True


def test_older_saves_resume_with_the_option_off(
    game: object, sample_saved_game_dir: object, monkeypatch: object
) -> None:
    """A save from before the option existed reads as off."""
    _skip_game_download(game, monkeypatch)
    general_file = sample_saved_game_dir / "general.json"
    assert "read_clues_aloud" not in json.loads(general_file.read_text())
    game.set_read_clues_aloud(True)
    game.prepare_resume_from_dir(sample_saved_game_dir)
    assert game.read_clues_aloud_enabled() is False
