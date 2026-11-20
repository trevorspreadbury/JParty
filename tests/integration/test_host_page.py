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
        assert "No game in progress: every player" in body

    def test_resumed_tournament_game_shows_only_its_players(self) -> None:
        """With no tournament chosen, the game in progress's tournament is used.

        This checks the page itself; the real resume flow, which restores the
        players' tournament ids, is tested in test_tournament_results.py.
        """
        player = Player("bob", None, 0)
        player.tournament_player = ("p1", "Bob")
        self.game.players = [player]
        self.game.tournament_game = TournamentGameRef("Fun", "Semifinals: SF 1")
        body = self.fetch("/host").body.decode()
        assert "This game's players, last podium first" in body
        assert "Podium 1" in body
        assert "Bob" in body
        assert "Ziggy" not in body

    def test_ticking_a_prompt_saves_it(self) -> None:
        """POST /host/prompt marks the prompt, and the page shows it ticked."""
        import json

        from jparty.domain.tournament_store import load_used_prompts

        self.controller.host_tournament = self.folder
        response = self.fetch(
            "/host/prompt",
            method="POST",
            body=json.dumps({"player_id": "p0", "prompt": 2, "used": True}),
        )
        assert response.code == 200
        assert json.loads(response.body) == {"ok": True}
        assert load_used_prompts(self.folder) == [("p0", 2, "Plays the oboe")]
        assert 'data-prompt="2" checked' in self.fetch("/host").body.decode()

        # Unticking takes it back off.
        response = self.fetch(
            "/host/prompt",
            method="POST",
            body=json.dumps({"player_id": "p0", "prompt": 2, "used": False}),
        )
        assert response.code == 200
        assert load_used_prompts(self.folder) == []
        assert 'data-prompt="2" checked' not in self.fetch("/host").body.decode()

    def test_bad_ticks_are_refused(self) -> None:
        """A malformed body, or a prompt that isn't there, gets a 400."""
        import json

        self.controller.host_tournament = self.folder
        bad = self.fetch("/host/prompt", method="POST", body="not json")
        assert bad.code == 400
        missing = self.fetch(
            "/host/prompt",
            method="POST",
            body=json.dumps({"player_id": "p1", "prompt": 1, "used": True}),
        )
        assert missing.code == 400
        assert json.loads(missing.body) == {"error": "That player has no such prompt."}

    def test_a_podium_with_no_tournament_player_keeps_seat_numbers(self) -> None:
        """The controller passes empty podiums on, so the seats stay true."""
        untracked = Player("guest", None, 0)
        bob = Player("bob", None, 1)
        bob.tournament_player = ("p1", "Bob")
        self.game.players = [untracked, bob]
        self.game.tournament_game = TournamentGameRef("Fun", "Semifinals: SF 1")
        page = self.controller.host_page()
        assert [(player.player_id, player.seat) for player in page.players] == [
            ("p1", 2)
        ]
