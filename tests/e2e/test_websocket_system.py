"""Test websocket system module."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from tornado.testing import AsyncHTTPTestCase as TornadoAsyncHTTPTestCase
from tornado.testing import gen_test
from tornado.websocket import websocket_connect

from jparty.app.config import MAXPLAYERS
from jparty.domain.models import Player
from jparty.web.app import Application

pytestmark = pytest.mark.e2e
TornadoAsyncHTTPTestCase.__test__ = False


class FakeController:
    """Test helper for fakecontroller."""

    def __init__(self) -> None:
        """Test init."""
        self.connected_players = []
        self.accepting_players = True
        self.lectern_connections = {}
        self.active_buzzer_sockets = set()
        self.saved_player_profiles = {}
        self.resume_mode_active = False
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

    def register_socket(self, socket_handler: object) -> None:
        """Test register socket."""
        self.active_buzzer_sockets.add(socket_handler)

    def unregister_socket(self, socket_handler: object) -> None:
        """Test unregister socket."""
        self.active_buzzer_sockets.discard(socket_handler)

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
        for profile in self.saved_player_profiles.values():
            if profile.get("token") == token:
                return profile.get("player")
        for player in self.connected_players:
            if player.token.hex() == token:
                return player
        return None

    def in_saved_player_reclaim_mode(self) -> bool:
        """Test reclaim mode."""
        return self.resume_mode_active

    def saved_player_claims_complete(self) -> bool:
        """Test claim completion."""
        return bool(self.saved_player_profiles) and all(
            profile.get("player") is not None
            for profile in self.saved_player_profiles.values()
        )

    def saved_player_choices_payload(self) -> object:
        """Test chooser payload."""
        players = []
        for player_number, profile in sorted(self.saved_player_profiles.items()):
            players.append(
                {
                    "name": profile["name"],
                    "player_number": player_number,
                    "claimed": profile.get("player") is not None,
                }
            )
        return {
            "players": players,
            "claimed_count": sum(
                1
                for profile in self.saved_player_profiles.values()
                if profile.get("player") is not None
            ),
            "total_count": len(self.saved_player_profiles),
        }

    def claim_saved_player(self, socket_handler: object, player_number: int) -> object:
        """Test claim saved player."""
        profile = self.saved_player_profiles.get(player_number)
        if profile is None:
            return None
        if (
            profile.get("player") is not None
            and profile["player"].waiter is not socket_handler
        ):
            socket_handler.send("PLAYER_TAKEN")
            return None
        player = profile.get("player")
        if player is None:
            player = Player(profile["name"], socket_handler, player_number)
            profile["player"] = player
            profile["token"] = player.token.hex()
            self.connected_players.append(player)
            self.game.players.append(player)
        player.waiter = socket_handler
        player.connected = True
        return player

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

    @gen_test(timeout=10)
    async def test_players_can_join_up_to_maxplayers(self) -> None:
        """Every seat up to MAXPLAYERS joins, and the next phone is told it's full."""
        sockets = []
        for player_index in range(MAXPLAYERS):
            ws = await websocket_connect(
                self.get_url("/buzzersocket").replace("http", "ws")
            )
            sockets.append(ws)
            ws.write_message(
                json.dumps({"message": "NAME", "text": f"Player {player_index}"})
            )
            message = json.loads(await ws.read_message())
            assert message["message"] == "TOKEN"
        assert [player.player_number for player in self.controller.game.players] == (
            list(range(MAXPLAYERS))
        )
        extra = await websocket_connect(
            self.get_url("/buzzersocket").replace("http", "ws")
        )
        sockets.append(extra)
        extra.write_message(json.dumps({"message": "NAME", "text": "One too many"}))
        message = json.loads(await extra.read_message())
        assert message["message"] == "FULL"
        for ws in sockets:
            ws.close()

    @gen_test(timeout=10)
    async def test_server_keeps_socket_open_when_pongs_are_late(self) -> None:
        """A phone that answers pings late must not be disconnected.

        Tornado 6.5+ closes a websocket when a pong is later than the ping
        timeout, which defaults to the ping interval (190 ms here). On Wi-Fi
        that closed phone sockets and made the buzzer page reload in a loop.
        This client never sends pongs, which is the worst case.
        """
        ws = await websocket_connect(
            self.get_url("/buzzersocket").replace("http", "ws")
        )
        protocol = ws.protocol
        original_write_frame = protocol._write_frame
        pong_opcode = 0xA

        def drop_pongs(fin: bool, opcode: int, data: bytes, flags: int = 0) -> object:
            if opcode == pong_opcode:
                skipped = asyncio.get_running_loop().create_future()
                skipped.set_result(None)
                return skipped
            return original_write_frame(fin, opcode, data, flags)

        protocol._write_frame = drop_pongs
        ping_interval = Application(self.controller).settings["websocket_ping_interval"]

        await asyncio.sleep(ping_interval * 5)

        assert ws.close_code is None
        ws.write_message(json.dumps({"message": "NAME", "text": "Alice"}))
        assert json.loads(await ws.read_message())["message"] == "TOKEN"
        ws.close()

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

    @gen_test
    async def test_resume_mode_sends_saved_player_chooser_and_claims_profile(
        self,
    ) -> None:
        """Test reclaim chooser and successful saved-player claim."""
        self.controller.resume_mode_active = True
        self.controller.saved_player_profiles = {
            0: {"name": "Alice", "player": None, "token": None},
            1: {"name": "data:image/png;base64,stub", "player": None, "token": None},
        }
        ws = await websocket_connect(
            self.get_url("/buzzersocket").replace("http", "ws")
        )
        ws.write_message(json.dumps({"message": "NAME", "text": "ignored"}))
        chooser_message = json.loads(await ws.read_message())
        assert chooser_message["message"] == "SHOW_CHOOSER"
        payload = json.loads(chooser_message["text"])
        assert payload["claimed_count"] == 0
        ws.write_message(json.dumps({"message": "CLAIM_PLAYER", "text": "1"}))
        claimed_message = json.loads(await ws.read_message())
        assert claimed_message["message"] == "CLAIMED"
        claimed_payload = json.loads(claimed_message["text"])
        assert claimed_payload["state"]["page"] == "buzz"
        ws.close()

    @gen_test
    async def test_saved_player_reconnect_by_token_skips_chooser(self) -> None:
        """Test reconnecting to a claimed saved player by token."""
        self.controller.resume_mode_active = True
        player = Player("Alice", None, 0)
        self.controller.saved_player_profiles = {
            0: {"name": "Alice", "player": player, "token": player.token.hex()}
        }
        self.controller.connected_players = [player]
        self.controller.game.players = [player]
        ws = await websocket_connect(
            self.get_url("/buzzersocket").replace("http", "ws")
        )
        ws.write_message(
            json.dumps({"message": "CHECK_IF_EXISTS", "text": player.token.hex()})
        )
        reconnect_message = json.loads(await ws.read_message())
        assert reconnect_message["message"] == "EXISTS"
        ws.close()
