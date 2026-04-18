import asyncio
import json
from types import SimpleNamespace

import pytest
from tornado.testing import AsyncHTTPTestCase as TornadoAsyncHTTPTestCase, gen_test
from tornado.websocket import websocket_connect

from jparty.web.app import Application


pytestmark = pytest.mark.e2e
TornadoAsyncHTTPTestCase.__test__ = False


class FakeController:
    def __init__(self):
        self.connected_players = []
        self.accepting_players = True
        self.lectern_connections = {}
        self.game = SimpleNamespace(
            players=[],
            buzz_trigger=SimpleNamespace(emit=lambda value: None),
            wager_trigger=SimpleNamespace(emit=lambda player, amount: None),
            new_player_trigger=SimpleNamespace(emit=lambda: None),
        )

    def new_player(self, player):
        self.connected_players.append(player)
        self.game.players.append(player)

    def buzz(self, player):
        return None

    def wager(self, player, amount):
        return None

    def answer(self, player, guess):
        return None

    def player_with_token(self, token):
        for player in self.connected_players:
            if player.token.hex() == token:
                return player
        return None

    def get_player_by_number(self, player_number):
        if player_number < len(self.game.players):
            return self.game.players[player_number]
        return None

    def get_player_state_dict(self, player):
        return {
            "name": player.name,
            "score": player.score,
            "player_number": player.player_number,
            "active": False,
            "buzzed": False,
            "finalanswer": player.finalanswer,
        }

    def broadcast_to_lecterns(self, player_number, state_dict):
        return None


class TestBuzzerSocketSystem(TornadoAsyncHTTPTestCase):
    __test__ = True

    def runTest(self):
        return None

    def get_app(self):
        self.controller = FakeController()
        return Application(self.controller)

    @gen_test
    async def test_player_can_join_and_reconnect_by_token(self):
        ws = await websocket_connect(self.get_url("/buzzersocket").replace("http", "ws"))
        ws.write_message(json.dumps({"message": "NAME", "text": "Alice"}))
        first_message = json.loads(await ws.read_message())
        assert first_message["message"] == "TOKEN"
        token = first_message["text"]
        ws.close()

        ws2 = await websocket_connect(self.get_url("/buzzersocket").replace("http", "ws"))
        ws2.write_message(json.dumps({"message": "CHECK_IF_EXISTS", "text": token}))
        reconnect_message = json.loads(await ws2.read_message())
        assert reconnect_message["message"] == "EXISTS"
        ws2.close()

    @gen_test
    async def test_lectern_socket_receives_initial_player_state(self):
        ws = await websocket_connect(self.get_url("/buzzersocket").replace("http", "ws"))
        ws.write_message(json.dumps({"message": "NAME", "text": "Alice"}))
        await ws.read_message()

        lectern = await websocket_connect(self.get_url("/lecternsocket?player=0").replace("http", "ws"))
        lectern_message = json.loads(await lectern.read_message())
        assert lectern_message["message"] == "PLAYER_STATE"
        payload = json.loads(lectern_message["text"])
        assert payload["name"] == "Alice"
        lectern.close()
        ws.close()
