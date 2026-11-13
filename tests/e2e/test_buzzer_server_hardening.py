"""Test the buzzer server rejects bad input and hides Final answers (#62).

These tests drive a real ``BuzzerController`` through Tornado's test client.
The game is a small stand-in that records wagers and answers.
"""

import json
from types import SimpleNamespace

import pytest
from tornado import gen
from tornado.testing import AsyncHTTPTestCase as TornadoAsyncHTTPTestCase
from tornado.testing import gen_test
from tornado.websocket import websocket_connect

from jparty.app.config import MAXPLAYERS
from jparty.domain.models import Player
from jparty.web import controller as controller_module
from jparty.web.controller import BuzzerController

pytestmark = pytest.mark.e2e
TornadoAsyncHTTPTestCase.__test__ = False


class RecordingGame(SimpleNamespace):
    """Stand-in game that records wagers and answers sent by phones."""

    def __init__(self) -> None:
        """Start with no players and nothing recorded."""
        self.wagers = []
        self.answers = []
        super().__init__(
            players=[],
            wager_trigger=SimpleNamespace(
                emit=lambda i_player, amount: self.wagers.append((i_player, amount))
            ),
            new_player_trigger=SimpleNamespace(emit=lambda: None),
        )

    def answer(self, player: Player, guess: str) -> None:
        """Record a Final answer."""
        self.answers.append((player.name, guess))


class FakeWaiter:
    """Stand-in socket for players who are not connected in the test."""

    def send(self, msg: str, text: str = "") -> None:
        """Ignore outgoing messages."""

    def close(self) -> None:
        """Ignore close requests."""


class BuzzerServerHardeningTest(TornadoAsyncHTTPTestCase):
    """Drive the real controller through the buzzer and lectern endpoints."""

    __test__ = True

    def runTest(self) -> None:
        """Satisfy ``unittest`` when the case is built without a method name."""

    def get_app(self) -> object:
        """Build the app around a real controller and a recording game."""
        original = controller_module.tornado.options.parse_command_line
        controller_module.tornado.options.parse_command_line = lambda: None
        try:
            self.game = RecordingGame()
            self.controller = BuzzerController(self.game)
        finally:
            controller_module.tornado.options.parse_command_line = original
        return self.controller.app

    def ws_url(self, path: str) -> str:
        """Return the websocket URL for ``path``."""
        return self.get_url(path).replace("http", "ws")

    async def join(self, name: str) -> tuple[object, Player]:
        """Connect a phone, join as ``name``, and return its socket and player."""
        ws = await websocket_connect(self.ws_url("/buzzersocket"))
        ws.write_message(json.dumps({"message": "NAME", "text": name}))
        reply = json.loads(await ws.read_message())
        assert reply["message"] == "TOKEN"
        player = self.controller.connected_players[-1]
        self.game.players.append(player)
        return ws, player

    async def round_trip(self, ws: object) -> None:
        """Wait until the server has handled every message sent on ``ws``."""
        ws.write_message(json.dumps({"message": "CHECK_IF_EXISTS", "text": "none"}))
        assert json.loads(await ws.read_message())["message"] == "NEW"

    @gen_test
    async def test_lectern_socket_gets_no_final_answer_before_reveal(self) -> None:
        """A lectern that connects during Final must not see the answer."""
        player = Player("Alice", FakeWaiter(), 0)
        player.finalanswer = "Who is Lincoln?"
        self.game.players.append(player)

        lectern = await websocket_connect(self.ws_url("/lecternsocket?player=0"))
        message = json.loads(await lectern.read_message())

        assert message["message"] == "PLAYER_STATE"
        state = json.loads(message["text"])
        assert state["name"] == "Alice"
        assert state["finalanswer"] is None
        lectern.close()

    @gen_test
    async def test_wagers_are_clamped_and_only_accepted_once(self) -> None:
        """Wagers below zero or above the score are clamped; extras are ignored."""
        ws_low, low = await self.join("Low")
        ws_high, high = await self.join("High")
        ws_broke, broke = await self.join("Broke")
        low.score, high.score, broke.score = 1000, 1000, -400
        self.controller.open_wagers()
        for ws in (ws_low, ws_high, ws_broke):
            assert json.loads(await ws.read_message())["message"] == "PROMPTWAGER"

        ws_low.write_message(json.dumps({"message": "WAGER", "text": "-5000"}))
        ws_high.write_message(json.dumps({"message": "WAGER", "text": "99999"}))
        ws_broke.write_message(json.dumps({"message": "WAGER", "text": "abc"}))
        ws_broke.write_message(json.dumps({"message": "WAGER", "text": "300"}))
        # A second wager from the same phone is ignored.
        ws_low.write_message(json.dumps({"message": "WAGER", "text": "500"}))
        for ws in (ws_low, ws_high, ws_broke):
            await self.round_trip(ws)

        assert self.game.wagers == [(0, 0), (1, 1000), (2, 0)]
        assert low.page == high.page == broke.page == "null"

    @gen_test
    async def test_answer_is_ignored_outside_the_answer_phase(self) -> None:
        """Answers before the prompt, or after time runs out, are ignored."""
        ws, player = await self.join("Alice")

        ws.write_message(json.dumps({"message": "ANSWER", "text": "too early"}))
        await self.round_trip(ws)
        assert self.game.answers == []

        self.controller.prompt_answers()
        assert json.loads(await ws.read_message())["message"] == "PROMPTANSWER"
        self.controller.toolate()
        assert json.loads(await ws.read_message())["message"] == "TOOLATE"
        assert player.page == "null"

        # The phone resubmits its answer box when time runs out. That one
        # answer is kept.
        ws.write_message(json.dumps({"message": "ANSWER", "text": "Lincoln"}))
        await self.round_trip(ws)
        assert self.game.answers == [("Alice", "Lincoln")]

        # A phone that reconnects late cannot answer again.
        reconnect = await websocket_connect(self.ws_url("/buzzersocket"))
        reconnect.write_message(
            json.dumps({"message": "CHECK_IF_EXISTS", "text": player.token.hex()})
        )
        exists = json.loads(await reconnect.read_message())
        assert exists["message"] == "EXISTS"
        assert json.loads(exists["text"])["page"] == "null"
        reconnect.write_message(json.dumps({"message": "ANSWER", "text": "Grant"}))
        await self.round_trip(reconnect)

        assert self.game.answers == [("Alice", "Lincoln")]
        ws.close()
        reconnect.close()

    @gen_test
    async def test_player_who_answered_gets_no_extra_answer_after_time_runs_out(
        self,
    ) -> None:
        """A player who already answered gets no extra answer after time runs out."""
        ws, _player = await self.join("Alice")
        self.controller.prompt_answers()
        assert json.loads(await ws.read_message())["message"] == "PROMPTANSWER"
        ws.write_message(json.dumps({"message": "ANSWER", "text": "Lincoln"}))
        await self.round_trip(ws)

        self.controller.toolate()
        assert json.loads(await ws.read_message())["message"] == "TOOLATE"
        ws.write_message(json.dumps({"message": "ANSWER", "text": "Grant"}))
        await self.round_trip(ws)

        assert self.game.answers == [("Alice", "Lincoln")]
        ws.close()

    async def reconnect(self, player: Player) -> object:
        """Reconnect ``player`` on a new socket and return it."""
        ws = await websocket_connect(self.ws_url("/buzzersocket"))
        ws.write_message(
            json.dumps({"message": "CHECK_IF_EXISTS", "text": player.token.hex()})
        )
        exists = json.loads(await ws.read_message())
        assert exists["message"] == "EXISTS"
        assert json.loads(exists["text"])["page"] == "null"
        return ws

    @gen_test
    async def test_phone_disconnected_when_time_runs_out_cannot_answer_later(
        self,
    ) -> None:
        """A phone offline at ``TOOLATE`` can't reconnect and answer (#62)."""
        ws, player = await self.join("Alice")
        self.controller.prompt_answers()
        assert json.loads(await ws.read_message())["message"] == "PROMPTANSWER"
        ws.close()
        for _ in range(100):
            if not player.connected:
                break
            await gen.sleep(0.01)
        assert player.connected is False

        self.controller.toolate()
        reconnect = await self.reconnect(player)
        reconnect.write_message(json.dumps({"message": "ANSWER", "text": "Grant"}))
        await self.round_trip(reconnect)

        assert self.game.answers == []
        reconnect.close()

    @gen_test
    async def test_late_answer_only_comes_from_the_socket_open_at_time_up(
        self,
    ) -> None:
        """After ``TOOLATE``, a new socket for the same player can't answer (#62)."""
        ws, player = await self.join("Alice")
        self.controller.prompt_answers()
        assert json.loads(await ws.read_message())["message"] == "PROMPTANSWER"
        self.controller.toolate()
        assert json.loads(await ws.read_message())["message"] == "TOOLATE"

        reconnect = await self.reconnect(player)
        reconnect.write_message(json.dumps({"message": "ANSWER", "text": "Grant"}))
        await self.round_trip(reconnect)

        assert self.game.answers == []
        ws.close()
        reconnect.close()

    @gen_test
    async def test_late_answer_is_ignored_after_the_grace_period(self) -> None:
        """A phone that ignores ``TOOLATE`` can't answer once judging starts (#62)."""
        original = controller_module.LATE_ANSWER_GRACE_SECONDS
        controller_module.LATE_ANSWER_GRACE_SECONDS = -1.0
        try:
            ws, _player = await self.join("Alice")
            self.controller.prompt_answers()
            assert json.loads(await ws.read_message())["message"] == "PROMPTANSWER"
            self.controller.toolate()
            assert json.loads(await ws.read_message())["message"] == "TOOLATE"

            ws.write_message(json.dumps({"message": "ANSWER", "text": "Grant"}))
            await self.round_trip(ws)
        finally:
            controller_module.LATE_ANSWER_GRACE_SECONDS = original

        assert self.game.answers == []
        ws.close()

    def test_lectern_page_rejects_bad_player_numbers(self) -> None:
        """The lectern page returns 400 unless ``player`` is a valid slot."""
        for bad in ("0;alert(1)//", "abc", "-1", str(MAXPLAYERS), ""):
            response = self.fetch(f"/lectern?player={bad}")
            assert response.code == 400, bad
            assert b"alert(1)" not in response.body

    def test_lectern_page_renders_player_number(self) -> None:
        """A valid ``player`` value renders the lectern page."""
        response = self.fetch("/lectern?player=3")
        assert response.code == 200
        assert b"var playerNumber = 3;" in response.body

    @gen_test
    async def test_full_game_sends_message_the_phone_handles(self) -> None:
        """A phone joining a full game gets the ``GAMEFULL`` message."""
        # Only the count matters here. Stand-ins are used because buzzer keys
        # exist for fewer seats than MAXPLAYERS.
        self.controller.connected_players = [
            SimpleNamespace(name=f"P{i}") for i in range(MAXPLAYERS)
        ]
        ws = await websocket_connect(self.ws_url("/buzzersocket"))
        ws.write_message(json.dumps({"message": "NAME", "text": "Late"}))

        assert json.loads(await ws.read_message())["message"] == "GAMEFULL"
        ws.close()
