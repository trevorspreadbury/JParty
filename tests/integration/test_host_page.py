"""Test the host's ``/host`` phone page, served by the buzzer server."""

from types import SimpleNamespace

import pytest
from tornado.testing import AsyncHTTPTestCase

from jparty.domain.models import Player
from jparty.domain.roster import PlayerSlot, SignUp
from jparty.domain.tournament_play import TournamentGameRef
from jparty.domain.tournament_store import TournamentSettings, save_tournament
from jparty.web.controller import BuzzerController

pytestmark = pytest.mark.integration
AsyncHTTPTestCase.__test__ = False


class HostPageTest(AsyncHTTPTestCase):
    """Fetch ``/host`` from a real controller around a stub game."""

    __test__ = True

    def runTest(self) -> None:
        """Satisfy ``unittest`` when the case is built without a method name."""

    def setUp(self) -> None:
        """Save a tournament whose sign-ups include markup."""
        import tempfile
        from pathlib import Path

        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        slots = [
            PlayerSlot(
                "Ziggy",
                SignUp(
                    "t",
                    "Jane Smith",
                    "teacher",
                    "Chicago",
                    ("<script>alert(1)</script>", "Plays the oboe"),
                ),
                player_id="p0",
            ),
            PlayerSlot("Bob", player_id="p1"),
        ]
        self.folder = save_tournament(self.root, TournamentSettings("Fun"), slots)
        self.game = SimpleNamespace(players=[], tournament_game=None)
        super().setUp()

    def tearDown(self) -> None:
        """Remove the tournament."""
        super().tearDown()
        self._temp.cleanup()

    def get_app(self) -> object:
        """Build the app around a controller that finds tournaments in ``root``."""
        self.controller = BuzzerController(self.game)
        self.controller.tournaments_dir = self.root
        return self.controller.app

    def test_no_tournament_says_how_to_start_one(self) -> None:
        """Outside tournament mode the page explains what to do."""
        response = self.fetch("/host")
        assert response.code == 200
        assert b"No tournament is being played." in response.body
        assert response.headers["Cache-Control"] == "no-store"

    def test_tournament_players_show_with_their_prompts_escaped(self) -> None:
        """Sign-up answers are shown as text, never run as markup."""
        self.controller.host_tournament = self.folder
        body = self.fetch("/host").body.decode()
        assert "<h1>Fun</h1>" in body
        assert "A teacher from Chicago, Jane Smith (Ziggy)" in body
        assert "Plays the oboe" in body
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
        assert "No sign-up answers." in body  # Bob

    def test_resumed_tournament_game_shows_its_players_on_stage(self) -> None:
        """With no tournament chosen, the game in progress's tournament is used."""
        player = Player("bob", None, 0)
        player.tournament_player = ("p1", "Bob")
        self.game.players = [player]
        self.game.tournament_game = TournamentGameRef("Fun", "Semifinals: SF 1")
        body = self.fetch("/host").body.decode()
        assert "Playing now" in body
        assert body.index("Bob") < body.index("Ziggy")
        assert "Everyone else" in body
