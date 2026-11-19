"""Test lecterns follow players joining, leaving and moving seats (#46)."""

import pytest

from jparty.domain.models import Player
from tests.conftest import FakeWaiter

pytestmark = pytest.mark.integration


class RecordingLectern:
    """Stand-in lectern socket that records what it is sent."""

    def __init__(self) -> None:
        """Start with nothing sent."""
        self.messages = []

    def send(self, msg: str, text: str = "") -> None:
        """Record one message."""
        self.messages.append(msg)


def connect_lecterns(game: object, count: int) -> list[RecordingLectern]:
    """Open lecterns for the first ``count`` seats."""
    lecterns = [RecordingLectern() for _ in range(count)]
    game.buzzer_controller.lectern_connections = dict(enumerate(lecterns))
    return lecterns


def updated_seats(game: object) -> list[int]:
    """Return the seats that were sent a player's state, in order."""
    return [number for number, _state in game.buzzer_controller.broadcasts]


def test_removing_a_player_clears_the_seat_left_empty(
    game_with_players: object,
) -> None:
    """The last lectern goes back to the logo when a player leaves.

    Everyone after the removed player moves up a seat, so the last seat is
    the one left empty. Its lectern used to keep the old name.
    """
    game = game_with_players
    connect_lecterns(game, 3)
    game.buzzer_controller.broadcasts.clear()

    game.remove_player(game.players[0])

    assert updated_seats(game) == [0, 1]
    assert game.buzzer_controller.cleared_lecterns == [2]


def test_new_player_updates_every_seat_and_clears_empty_ones(
    game_with_players: object,
) -> None:
    """A joining player shows up, and lecterns with no player show the logo."""
    game = game_with_players
    lecterns = connect_lecterns(game, 5)
    game.buzzer_controller.broadcasts.clear()

    dave = Player("Dave", FakeWaiter(), 3)
    game.buzzer_controller.connected_players.append(dave)
    game.new_player()

    assert updated_seats(game) == [0, 1, 2, 3]
    assert game.buzzer_controller.cleared_lecterns == [4]
    assert lecterns[4].messages == ["NO_PLAYER"]


def test_moving_a_player_keeps_every_seat_filled(game_with_players: object) -> None:
    """Swapping two seats updates both and clears nothing."""
    game = game_with_players
    connect_lecterns(game, 3)
    game.buzzer_controller.broadcasts.clear()

    game.move_player_down(game.players[0])

    assert sorted(updated_seats(game)) == [0, 1, 2]
    assert game.buzzer_controller.cleared_lecterns == []
