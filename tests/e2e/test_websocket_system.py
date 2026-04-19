"""Test websocket system module."""

import json
from types import SimpleNamespace

import pytest
from jparty.web.app import Application
from tornado.testing import AsyncHTTPTestCase as TornadoAsyncHTTPTestCase
from tornado.testing import gen_test
from tornado.websocket import websocket_connect

pytestmark = pytest.mark.e2e
TornadoAsyncHTTPTestCase.__test__ = False


class FakeController:
    """Test helper for fakecontroller."""

    def __init__(self) -> None:
        """Test init."""
        self.connected_players = []
        self.accepting_players = True
        self.lectern_connections = {}
        self.game = SimpleNamespace(
            players=[],
            buzz_trigger=SimpleNamespace(emit=lambda value: None),
            wager_trigger=SimpleNamespace(emit=lambda player, amount: None),
            new_player_trigger=SimpleNamespace(emit=lambda: None),
        )

    def new_player(self, player: object) -> None:
        """Test new player."""
        self.connected_players.append(player)
        self.game.players.append(player)

    def buzz(self, player: object) -> None:
        """Test buzz."""
        return None

    def wager(self, player: object, amount: object) -> None:
        """Test wager."""
        return None

    def answer(self, player: object, guess: object) -> None:
        """Test answer."""
        return None

    def player_with_token(self, token: object) -> object:
        """Test player with token."""
        for player in self.connected_players:
            if player.token.hex() == token:
                return player
        return None

    def get_player_by_number(self, player_number: object) -> object:
        """Test get player by number."""
        if player_number < len(self.game.players):
            return self.game.players[player_number]
        return None

    def get_player_state_dict(self, player: object) -> object:
        """Test get player state dict."""
        return {
            "name": player.name,
            "score": player.score,
            "player_number": player.player_number,
            "active": False,
            "buzzed": False,
            "finalanswer": player.finalanswer,
        }

    def broadcast_to_lecterns(self, player_number: object, state_dict: object) -> None:
        """Test broadcast to lecterns."""
        return None


class TestBuzzerSocketSystem(TornadoAsyncHTTPTestCase):
    """Test helper for testbuzzersocketsystem."""

    __test__ = True

    def runTest(self) -> None:
        """Test runTest."""
        return None

    def get_app(self) -> object:
        """Test get app."""
        self.controller = FakeController()
        return Application(self.controller)

    @gen_test
    async def test_player_can_join_and_reconnect_by_token(self) -> None:
        """Test test player can join and reconnect by token."""
        ws = await websocket_connect(
            self.get_url("/buzzersocket").replace("http", "ws")
        )
        ws.write_message(json.dumps({"message": "NAME", "text": "Alice"}))
        first_message = json.loads(await ws.read_message())
        assert first_message["message"] == "TOKEN"
        token = first_message["text"]
        ws.close()
        ws2 = await websocket_connect(
            self.get_url("/buzzersocket").replace("http", "ws")
        )
        ws2.write_message(json.dumps({"message": "CHECK_IF_EXISTS", "text": token}))
        reconnect_message = json.loads(await ws2.read_message())
        assert reconnect_message["message"] == "EXISTS"
        ws2.close()

    @gen_test
    async def test_lectern_socket_receives_initial_player_state(self) -> None:
        """Test test lectern socket receives initial player state."""
        ws = await websocket_connect(
            self.get_url("/buzzersocket").replace("http", "ws")
        )
        ws.write_message(json.dumps({"message": "NAME", "text": "Alice"}))
        await ws.read_message()
        lectern = await websocket_connect(
            self.get_url("/lecternsocket?player=0").replace("http", "ws")
        )
        lectern_message = json.loads(await lectern.read_message())
        assert lectern_message["message"] == "PLAYER_STATE"
        payload = json.loads(lectern_message["text"])
        assert payload["name"] == "Alice"
        lectern.close()
        ws.close()
