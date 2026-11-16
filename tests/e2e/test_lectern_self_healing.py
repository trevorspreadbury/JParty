"""Test that lectern pages recover without a manual refresh (#46).

Lecterns are laptops left on one page for hours, across many JParty
restarts. These tests cover the server half (heartbeats, the state sent on
connect, empty seats) and the page half (retrying forever, dropping a quiet
connection, falling back to the logo, and starting with no internet).
"""

import json
from types import SimpleNamespace

import pytest
from tornado import gen
from tornado.testing import AsyncHTTPTestCase as TornadoAsyncHTTPTestCase
from tornado.testing import gen_test
from tornado.websocket import websocket_connect

from jparty.domain.models import Player
from jparty.web import handlers as handlers_module
from jparty.web.controller import BuzzerController
from tests.e2e.test_browser_smoke import (  # noqa: F401  (pytest fixtures)
    FakeWaiter,
    browser_page,
    live_browser_server,
    wait_until,
)

pytestmark = pytest.mark.e2e
TornadoAsyncHTTPTestCase.__test__ = False

SOCKET_OPEN = "window.updater && updater.socket && updater.socket.readyState === 1"

# Make the page's next ``fails`` connection attempts fail, as if JParty were
# not running. A real socket to a closed port can take seconds to fail on
# Windows, so a failed attempt is a stand-in socket that closes right away.
# ``window.__opened`` counts every attempt and ``window.__fails`` counts down
# the failures still to come.
FAIL_NEXT_CONNECTIONS = """(fails) => {
    window.__opened = 0;
    window.__fails = fails;
    const RealWebSocket = window.__RealWebSocket || window.WebSocket;
    window.__RealWebSocket = RealWebSocket;
    window.WebSocket = function(url) {
        window.__opened++;
        if (window.__fails > 0) {
            window.__fails--;
            const failed = {readyState: 0, close: function() {}};
            setTimeout(function() {
                failed.readyState = 3;
                if (failed.onclose) {
                    failed.onclose({code: 1006});
                }
            }, 0);
            return failed;
        }
        return new RealWebSocket(url);
    };
    Object.assign(window.WebSocket, {CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3});
}"""


class LecternServerTest(TornadoAsyncHTTPTestCase):
    """Drive the real controller through the lectern socket."""

    __test__ = True

    def runTest(self) -> None:
        """Satisfy ``unittest`` when the case is built without a method name."""

    def get_app(self) -> object:
        """Build the app around a real controller and an empty stand-in game."""
        self.game = SimpleNamespace(players=[])
        self.controller = BuzzerController(self.game)
        return self.controller.app

    def ws_url(self, path: str) -> str:
        """Return the websocket URL for ``path``."""
        return self.get_url(path).replace("http", "ws")

    async def read(self, ws: object) -> dict:
        """Read one message from ``ws`` and decode it."""
        return json.loads(await ws.read_message())

    @gen_test
    async def test_lectern_gets_regular_heartbeats(self) -> None:
        """The server keeps a quiet lectern connection talking."""
        original = handlers_module.LECTERN_HEARTBEAT_SECONDS
        handlers_module.LECTERN_HEARTBEAT_SECONDS = 0.05
        try:
            lectern = await websocket_connect(self.ws_url("/lecternsocket?player=0"))
        finally:
            handlers_module.LECTERN_HEARTBEAT_SECONDS = original
        assert (await self.read(lectern))["message"] == "NO_PLAYER"
        assert (await self.read(lectern))["message"] == "HEARTBEAT"
        assert (await self.read(lectern))["message"] == "HEARTBEAT"

        handler = self.controller.lectern_connections[0]
        lectern.close()
        for _ in range(100):
            if handler.heartbeat is None:
                break
            await gen.sleep(0.01)
        assert handler.heartbeat is None

    @gen_test
    async def test_empty_seat_gets_no_player_even_without_a_game(self) -> None:
        """A lectern that connects before any game exists shows the logo."""
        self.controller.game = None
        lectern = await websocket_connect(self.ws_url("/lecternsocket?player=2"))
        assert (await self.read(lectern))["message"] == "NO_PLAYER"
        lectern.close()

    @gen_test
    async def test_lectern_shows_the_player_in_its_seat_not_list_position(
        self,
    ) -> None:
        """In the resume lobby a released seat leaves a gap in the roster.

        Seat 1's lectern must show seat 1's player, not whoever is second in
        the list, and the empty seat 0 must show the logo.
        """
        bob = Player("Bob", FakeWaiter(), 1)
        cara = Player("Cara", FakeWaiter(), 2)
        self.game.players.extend([bob, cara])

        seat0 = await websocket_connect(self.ws_url("/lecternsocket?player=0"))
        seat1 = await websocket_connect(self.ws_url("/lecternsocket?player=1"))

        assert (await self.read(seat0))["message"] == "NO_PLAYER"
        message = await self.read(seat1)
        assert message["message"] == "PLAYER_STATE"
        assert json.loads(message["text"])["name"] == "Bob"
        seat0.close()
        seat1.close()

    @gen_test
    async def test_clear_empty_lecterns_only_clears_empty_seats(self) -> None:
        """Seats with a player keep their state; empty seats get the logo."""
        self.game.players.append(Player("Alice", FakeWaiter(), 0))
        seat0 = await websocket_connect(self.ws_url("/lecternsocket?player=0"))
        seat1 = await websocket_connect(self.ws_url("/lecternsocket?player=1"))
        assert (await self.read(seat0))["message"] == "PLAYER_STATE"
        assert (await self.read(seat1))["message"] == "NO_PLAYER"

        self.controller.clear_empty_lecterns()
        # Seat 0 gets nothing new, so a broadcast is the next thing it reads.
        self.controller.broadcast_to_lecterns(0, {"name": "Alice"})

        assert (await self.read(seat1))["message"] == "NO_PLAYER"
        assert (await self.read(seat0))["message"] == "PLAYER_STATE"
        seat0.close()
        seat1.close()


def open_lectern(page: object, url: str, player: int = 0) -> None:
    """Open the lectern page for ``player`` and wait for its socket."""
    page.goto(f"{url}/lectern?player={player}")
    page.wait_for_function(SOCKET_OPEN)


def seat(live_server: object, name: str, number: int = 0) -> Player:
    """Seat a player in the live server's game."""
    player = Player(name, FakeWaiter(), number)
    live_server.controller.new_player(player)
    return player


def close_lectern_from_server(live_server: object, number: int = 0) -> None:
    """Close the server's end of a lectern socket, as quitting JParty would."""
    lectern = live_server.controller.lectern_connections[number]
    live_server.loop.add_callback(lectern.close)


def test_lectern_keeps_retrying_past_the_old_limit(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """A lectern waiting through a long restart reconnects without reloading.

    The page used to give up after 10 tries and show "Connection lost".
    """
    seat(live_browser_server, "Alice")
    open_lectern(browser_page, live_browser_server.url)
    loads = []
    browser_page.on("load", lambda _page: loads.append(1))
    browser_page.evaluate("updater.reconnectDelay = 10; updater.maxReconnectDelay = 20")
    browser_page.evaluate(FAIL_NEXT_CONNECTIONS, 15)

    close_lectern_from_server(live_browser_server)
    browser_page.wait_for_function(
        "window.__fails === 0 && updater.socket && updater.socket.readyState === 1",
        timeout=10000,
    )

    assert browser_page.evaluate("window.__opened") == 16
    assert loads == []
    assert browser_page.locator("#player-name").text_content() == "Alice"


def test_lectern_shows_logo_once_jparty_is_gone_and_player_on_return(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """Closing JParty sends the lectern back to the logo after a short wait."""
    seat(live_browser_server, "Alice")
    open_lectern(browser_page, live_browser_server.url)
    name = browser_page.locator("#player-name")
    logo = browser_page.locator("#logo")
    name.wait_for(state="visible")
    browser_page.evaluate(
        "updater.reconnectDelay = 50; updater.maxReconnectDelay = 50;"
        " updater.logoAfter = 300"
    )
    browser_page.evaluate(FAIL_NEXT_CONNECTIONS, 1000)

    close_lectern_from_server(live_browser_server)
    logo.wait_for(state="visible")
    assert name.is_hidden()

    # JParty is back with Alice in the same seat.
    browser_page.evaluate("window.__fails = 0")
    name.wait_for(state="visible")
    assert name.text_content() == "Alice"
    assert logo.is_hidden()


def test_short_blip_keeps_the_player_on_screen(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """A reconnect quicker than the logo wait never blanks the lectern."""
    seat(live_browser_server, "Alice")
    open_lectern(browser_page, live_browser_server.url)
    browser_page.locator("#player-name").wait_for(state="visible")
    browser_page.evaluate(
        """() => {
            updater.reconnectDelay = 20;
            updater.logoAfter = 2000;
            window.__logoShown = false;
            const realShowNoPlayer = updater.showNoPlayer.bind(updater);
            updater.showNoPlayer = () => {
                window.__logoShown = true;
                realShowNoPlayer();
            };
        }"""
    )

    close_lectern_from_server(live_browser_server)
    browser_page.wait_for_function("updater.reconnectAttempts === 0 && " + SOCKET_OPEN)
    browser_page.wait_for_function("updater.logoTimer === null")
    browser_page.wait_for_timeout(200)

    assert browser_page.evaluate("window.__logoShown") is False
    assert browser_page.locator("#player-name").text_content() == "Alice"


def test_quiet_connection_is_dropped_and_replaced(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """A connection that stops sending anything is treated as dead.

    The server's heartbeat comes every 3 seconds, so waiting only 500 ms for
    a message stands in for a connection that went silent.
    """
    seat(live_browser_server, "Alice")
    open_lectern(browser_page, live_browser_server.url)
    first = live_browser_server.controller.lectern_connections[0]
    browser_page.evaluate(FAIL_NEXT_CONNECTIONS, 0)
    browser_page.evaluate("updater.staleAfter = 500; updater.reconnectDelay = 20")

    browser_page.wait_for_function("window.__opened >= 1 && " + SOCKET_OPEN)
    # Put the normal timeout back so the new socket is left alone.
    browser_page.evaluate("updater.staleAfter = 10000")

    wait_until(
        lambda: (
            live_browser_server.controller.lectern_connections.get(0)
            not in (None, first)
        )
    )
    assert browser_page.locator("#player-name").text_content() == "Alice"


def test_lectern_starts_with_no_internet(
    live_browser_server: object,  # noqa: F811
) -> None:
    """The lectern starts when every outside request fails.

    It used to wait on jQuery from a CDN before connecting.
    """
    from playwright.sync_api import sync_playwright

    seat(live_browser_server, "Alice")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if route.request.url.startswith(live_browser_server.url)
                    else route.abort()
                ),
            )
            page.goto(f"{live_browser_server.url}/lectern?player=0")
            page.wait_for_function(SOCKET_OPEN)
            page.locator("#player-name").wait_for(state="visible")
            assert page.locator("#player-name").text_content() == "Alice"
        finally:
            browser.close()
