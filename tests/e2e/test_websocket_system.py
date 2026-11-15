"""Test websocket system module."""

import asyncio
import json

import pytest
from tornado.testing import AsyncHTTPTestCase as TornadoAsyncHTTPTestCase
from tornado.testing import gen_test
from tornado.websocket import websocket_connect

from jparty.app.config import MAXPLAYERS
from jparty.web.app import Application
from tests.server_fakes import FakeServerController

pytestmark = pytest.mark.e2e
SIGNATURE_NAME = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAA+/x=="
TornadoAsyncHTTPTestCase.__test__ = False


class TestBuzzerSocketSystem(TornadoAsyncHTTPTestCase):
    """Test helper for testbuzzersocketsystem."""

    __test__ = True

    def runTest(self) -> None:
        """Test runTest."""
        return None

    def get_app(self) -> object:
        """Test get app."""
        self.controller = FakeServerController()
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
        # #86 renames the server message to GAMEFULL; accept either until both land.
        assert message["message"] in {"FULL", "GAMEFULL"}
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
        self.controller.begin_saved_player_reclaim(
            [
                {"name": "Alice", "player_number": 0},
                {"name": SIGNATURE_NAME, "player_number": 1},
            ]
        )
        ws = await websocket_connect(
            self.get_url("/buzzersocket").replace("http", "ws")
        )
        ws.write_message(json.dumps({"message": "NAME", "text": "ignored"}))
        chooser_message = json.loads(await ws.read_message())
        assert chooser_message["message"] == "SHOW_CHOOSER"
        payload = json.loads(chooser_message["text"])
        assert payload["claimed_count"] == 0
        assert [choice["name"] for choice in payload["players"]] == [
            "Alice",
            SIGNATURE_NAME,
        ]
        ws.write_message(json.dumps({"message": "CLAIM_PLAYER", "text": "1"}))
        claimed_message = json.loads(await ws.read_message())
        assert claimed_message["message"] == "CLAIMED"
        claimed_payload = json.loads(claimed_message["text"])
        assert claimed_payload["state"]["page"] == "buzz"
        claimed_player = self.controller.player_with_token(claimed_payload["token"])
        assert claimed_player.name == SIGNATURE_NAME
        ws.close()

    @gen_test
    async def test_saved_player_reconnect_by_token_skips_chooser(self) -> None:
        """Test reconnecting to a claimed saved player by token."""
        self.controller.begin_saved_player_reclaim(
            [
                {"name": "Alice", "player_number": 0},
                {"name": "Bob", "player_number": 1},
            ]
        )
        ws = await websocket_connect(
            self.get_url("/buzzersocket").replace("http", "ws")
        )
        ws.write_message(json.dumps({"message": "CLAIM_PLAYER", "text": "0"}))
        claimed_message = json.loads(await ws.read_message())
        assert claimed_message["message"] == "CLAIMED"
        token = json.loads(claimed_message["text"])["token"]
        ws.close()

        ws2 = await websocket_connect(
            self.get_url("/buzzersocket").replace("http", "ws")
        )
        ws2.write_message(json.dumps({"message": "CHECK_IF_EXISTS", "text": token}))
        reconnect_message = json.loads(await ws2.read_message())
        assert reconnect_message["message"] == "EXISTS"
        player = self.controller.player_with_token(token)
        assert player.name == "Alice"
        assert player.waiter is not None
        assert self.controller.claimed_saved_players() == [player]
        ws2.close()
