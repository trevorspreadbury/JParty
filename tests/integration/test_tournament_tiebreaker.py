"""A tournament tiebreaker played outside any game, between tied players."""

import pytest
from PyQt6.QtCore import Qt

from jparty.domain.models import Question
from jparty.domain.tournament.advancement import (
    TIE_WILDCARD,
    Tiebreak,
    TiebreakerSession,
    TieForSpot,
)
from jparty.domain.tournament.store import TournamentFileError, load_tiebreaks
from tests.integration.test_tournament_results import _seat_phones, folders  # noqa: F401

pytestmark = pytest.mark.integration

TIE = TieForSpot("Quarterfinals", TIE_WILDCARD, ("eve-id", "fay-id"), 400, 1)
SESSION = TiebreakerSession("Fun", TIE, (("eve-id", "Eve"), ("fay-id", "Fay")))


def _space(game: object) -> None:
    """Press Space on the host keyboard."""
    game.keystroke_manager.call(Qt.Key.Key_Space)


@pytest.fixture()
def session_game(game: object, folders: object, monkeypatch: object) -> object:  # noqa: F811
    """Return a game with Eve's and Fay's phones, clues loading inline."""
    clues = [
        Question(
            index=(number, 4),
            text=f"Tiebreaker clue {number}",
            answer=f"Answer {number}",
            category=f"Category {number}",
            value=2000,
        )
        for number in range(2)
    ]
    game.host_warnings = []
    game.prompts = []
    monkeypatch.setattr(
        game, "show_host_warning", lambda title, text: game.host_warnings.append(text)
    )
    monkeypatch.setattr(
        game, "load_tiebreaker_clues", lambda game_id, is_cancelled: (game_id, clues)
    )
    monkeypatch.setattr(game, "run_in_background", lambda work: work())
    monkeypatch.setattr(game, "prompt_tiebreaker_game_id", lambda: "1234")
    closed = []
    real_close = game.close_game
    monkeypatch.setattr(
        game, "close_game", lambda: (closed.append(True), real_close())[1]
    )
    game.closed = closed
    # A game id left over from an earlier game, so saving a game folder
    # would work if the session tried to; it mustn't.
    game.set_session_game_id("4453")
    _seat_phones(game, ["Eve's phone", "Fay's phone"])
    return game


def test_tiebreaker_session_saves_the_winner(
    session_game: object,
    folders: object,  # noqa: F811
) -> None:
    """The tied players play tossups, and the winner is saved for the tie."""
    game = session_game
    game.start_tiebreaker_session(SESSION)
    assert game.dc.final_window.tie_shown is True
    assert game.keystroke_manager._events["START_TIEBREAKER"].active
    assert game.tiebreaker_flow.contenders == game.players

    _space(game)  # Pick the game and load its clues.
    _space(game)  # Show the clue after its category.
    _space(game)  # Open buzzing.
    game.buzz(1)
    game.correct_answer()

    assert load_tiebreaks(folders) == [
        Tiebreak("Quarterfinals", frozenset({"eve-id", "fay-id"}), "fay-id")
    ]
    assert load_tiebreaks(folders)[0].winner_name == "Fay"
    # No saved game: the session can't show up under Load Saved.
    assert game._game_state_dir is None
    assert not (folders.parent.parent / "game_states").exists()
    assert game.keystroke_manager._events["CLOSE_GAME"].active
    assert not game.keystroke_manager._events["GENERATE_GRAPHS"].active

    _space(game)  # Back to the lobby.
    assert game.tiebreaker_session is None
    assert game.players == []


def test_stumped_clue_moves_on_without_a_saved_game(session_game: object) -> None:
    """A clue nobody gets goes to the next one, still without saving a game."""
    game = session_game
    game.start_tiebreaker_session(SESSION)
    _space(game)
    _space(game)
    _space(game)
    game.buzz(0)
    game.incorrect_answer()
    game.buzz(1)
    game.incorrect_answer()
    assert game._game_state_dir is None
    assert game.question_number == 2


def test_cancelling_the_prompt_goes_back_without_saving(
    session_game: object,
    folders: object,  # noqa: F811
    monkeypatch: object,
) -> None:
    """Cancel leaves the tie unsettled and returns to the lobby."""
    game = session_game
    monkeypatch.setattr(game, "prompt_tiebreaker_game_id", lambda: None)
    game.start_tiebreaker_session(SESSION)
    _space(game)
    assert game.closed == [True]
    assert load_tiebreaks(folders) == []


def test_session_needs_one_phone_per_tied_player(session_game: object) -> None:
    """Two tied players and three phones can't be paired up."""
    game = session_game
    _seat_phones(game, ["A", "B", "C"])
    with pytest.raises(ValueError, match="one phone per tied player"):
        game.start_tiebreaker_session(SESSION)
    assert game.tiebreaker_session is None


def test_unsaved_tiebreaker_warns_the_host(
    session_game: object, monkeypatch: object
) -> None:
    """A tiebreaks.csv that can't be written is reported, not swallowed."""
    from jparty.domain import game_engine

    def fail(_folder: object, _tiebreak: object) -> None:
        raise TournamentFileError("disk full")

    monkeypatch.setattr(game_engine, "record_tiebreak", fail)
    game = session_game
    game.start_tiebreaker_session(SESSION)
    _space(game)
    _space(game)
    _space(game)
    game.buzz(0)
    game.correct_answer()
    assert any("disk full" in warning for warning in game.host_warnings)
