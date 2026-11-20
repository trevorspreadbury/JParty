"""The /host QR code shown to the host after a tournament game's first board."""

import pytest
from PyQt6.QtCore import Qt

from jparty.domain.tournament.play import TournamentGameRef

pytestmark = pytest.mark.integration


@pytest.fixture()
def finished_first_board(game: object) -> object:
    """Return a game whose first board is done, with a host display to watch."""
    game.host_display.codes = []
    game.host_display.load_host_code = game.host_display.codes.append
    game.host_display.hide_host_code = lambda: game.host_display.codes.append(None)
    game.buzzer_controller.host = lambda: "192.168.1.20:8080"
    for question in game.current_round.questions:
        question.complete = True
    game.keystroke_manager.activate("NEXT_ROUND")
    return game


def _space(game: object) -> None:
    """Press Space on the host keyboard."""
    game.keystroke_manager.call(Qt.Key.Key_Space)


def test_tournament_game_shows_the_host_code_before_the_next_board(
    finished_first_board: object,
) -> None:
    """Space shows the code; Space again goes on to the next round."""
    game = finished_first_board
    game.tournament_game = TournamentGameRef("Fun", "Semifinals: SF 1")
    first, second = game.data.rounds[0], game.data.rounds[1]

    _space(game)
    assert game.host_display.codes == ["192.168.1.20:8080"]
    assert game.current_round is first
    assert game.keystroke_manager._events["NEXT_ROUND"].active

    _space(game)
    assert game.host_display.codes == ["192.168.1.20:8080", None]
    assert game.current_round is second


def test_host_code_is_shown_only_once_a_game(finished_first_board: object) -> None:
    """Going back to the first round's end later doesn't show it again."""
    game = finished_first_board
    game.tournament_game = TournamentGameRef("Fun", "Semifinals: SF 1")
    _space(game)
    _space(game)
    game.current_round = game.data.rounds[0]
    game.keystroke_manager.activate("NEXT_ROUND")
    _space(game)
    assert game.host_display.codes == ["192.168.1.20:8080", None]
    assert game.current_round is game.data.rounds[1]


def test_regular_game_goes_straight_to_the_next_board(
    finished_first_board: object,
) -> None:
    """Outside a tournament there's no host page, so no code."""
    game = finished_first_board
    _space(game)
    assert game.host_display.codes == []
    assert game.current_round is game.data.rounds[1]


def test_no_network_address_skips_the_code(finished_first_board: object) -> None:
    """If the address can't be found, Space just goes on."""
    game = finished_first_board
    game.tournament_game = TournamentGameRef("Fun", "Semifinals: SF 1")

    def no_address() -> str:
        raise OSError("network unreachable")

    game.buzzer_controller.host = no_address
    _space(game)
    assert game.host_display.codes == []
    assert game.current_round is game.data.rounds[1]


def test_host_code_shows_only_after_the_first_board(
    finished_first_board: object,
) -> None:
    """Finishing a later board goes straight on, even if no code was shown."""
    game = finished_first_board
    game.tournament_game = TournamentGameRef("Fun", "Semifinals: SF 1")
    game.current_round = game.data.rounds[1]
    for question in game.current_round.questions:
        question.complete = True
    assert not game._show_host_code()
    assert game.host_display.codes == []


def test_host_code_needs_a_later_round(
    finished_first_board: object, monkeypatch: object
) -> None:
    """A first board with nothing after it doesn't show the code."""
    game = finished_first_board
    game.tournament_game = TournamentGameRef("Fun", "Semifinals: SF 1")
    monkeypatch.setattr(game, "has_later_round", lambda: False)
    assert not game._show_host_code()
    assert game.host_display.codes == []


@pytest.mark.parametrize("reset", ["clear_resume_state", "close_game"])
def test_next_game_can_show_the_host_code_again(
    finished_first_board: object, reset: str
) -> None:
    """Leaving a game clears the shown-once flag, so the next game shows it."""
    game = finished_first_board
    game.tournament_game = TournamentGameRef("Fun", "Semifinals: SF 1")
    _space(game)
    assert (game.host_code_done, game.host_code_shown) == (True, True)
    getattr(game, reset)()
    assert (game.host_code_done, game.host_code_shown) == (False, False)
