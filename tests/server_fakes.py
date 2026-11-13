"""Shared controller for tests that run the real Tornado handlers.

``FakeServerController`` is the real ``BuzzerController`` attached to a small
game stand-in, so joining, token login, and saved-player claims all use the
production logic. Only buzzes are recorded instead of reaching a game.
"""

from types import SimpleNamespace

from jparty.domain.models import Player
from jparty.web.controller import BuzzerController


def _ignore(*args: object) -> None:
    """Accept and ignore any arguments."""


class FakeServerController(BuzzerController):
    """Real ``BuzzerController`` with a stand-in game."""

    def __init__(self) -> None:
        """Build the controller around a stand-in game."""
        game = SimpleNamespace(
            players=[],
            buzz_trigger=SimpleNamespace(emit=_ignore),
            wager_trigger=SimpleNamespace(emit=_ignore),
            new_player_trigger=SimpleNamespace(emit=_ignore),
            answer=_ignore,
        )
        super().__init__(game)
        self.buzzed_players = []

    def new_player(self, player: Player) -> None:
        """Register the player and seat them in the game, as starting would."""
        super().new_player(player)
        self.game.players.append(player)

    def buzz(self, player: Player) -> None:
        """Record the name of the player who buzzed."""
        self.buzzed_players.append(player.name)
