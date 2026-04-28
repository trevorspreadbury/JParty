"""Test browser smoke module."""

import asyncio
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
import tornado.httpserver
import tornado.ioloop
import tornado.netutil
from jparty.domain.models import Player
from jparty.web.app import Application
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.e2e


def wait_until(predicate: object, timeout: object = 2.0) -> None:
    """Test wait until."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition was not met before timeout")


class FakeWaiter:
    """Test helper for fakewaiter."""

    def close(self) -> None:
        """Test close."""
        return None


class BrowserSmokeController:
    """Test helper for browsersmokecontroller."""

    def __init__(self) -> None:
        """Test init."""
        self.connected_players = []
        self.accepting_players = True
        self.lectern_connections = {}
        self.active_buzzer_sockets = set()
        self.saved_player_profiles = {}
        self.resume_mode_active = False
        self.buzzed_players = []
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
        """Track an open buzzer websocket for the smoke test server."""
        self.active_buzzer_sockets.add(socket_handler)

    def unregister_socket(self, socket_handler: object) -> None:
        """Stop tracking a buzzer websocket for the smoke test server."""
        self.active_buzzer_sockets.discard(socket_handler)

    def in_saved_player_reclaim_mode(self) -> bool:
        """Report whether the smoke-test lobby is reclaiming saved players."""
        return self.resume_mode_active

    def saved_player_claims_complete(self) -> bool:
        """Report whether all saved-player claims are complete."""
        return bool(self.saved_player_profiles) and all(
            profile.get("player") is not None
            for profile in self.saved_player_profiles.values()
        )

    def saved_player_choices_payload(self) -> object:
        """Build the saved-player chooser payload for smoke tests."""
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
        """Claim a saved player profile for the smoke-test controller."""
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

    def buzz(self, player: object) -> None:
        """Test buzz."""
        self.buzzed_players.append(player.name)

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


@dataclass
class LiveBrowserServer:
    """Test helper for livebrowserserver."""

    controller: BrowserSmokeController
    url: str
    loop: tornado.ioloop.IOLoop
    thread: threading.Thread
    server: tornado.httpserver.HTTPServer


@pytest.fixture
def live_browser_server() -> object:
    """Test live browser server."""
    controller = BrowserSmokeController()
    app = Application(controller)
    sockets = tornado.netutil.bind_sockets(0, address="127.0.0.1")
    port = sockets[0].getsockname()[1]
    ready = threading.Event()
    state = {}

    def run() -> None:
        """Test run."""
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = tornado.ioloop.IOLoop.current()
        server = tornado.httpserver.HTTPServer(app)
        server.add_sockets(sockets)
        state["loop"] = loop
        state["server"] = server
        ready.set()
        loop.start()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(timeout=5)
    live_server = LiveBrowserServer(
        controller=controller,
        url=f"http://127.0.0.1:{port}",
        loop=state["loop"],
        thread=thread,
        server=state["server"],
    )
    try:
        yield live_server
    finally:
        live_server.loop.add_callback(live_server.server.stop)
        live_server.loop.add_callback(live_server.loop.stop)
        live_server.thread.join(timeout=5)
        for sock in sockets:
            sock.close()


@pytest.fixture
def browser_page() -> object:
    """Test browser page."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.add_init_script(
            '\n            window.$ = window.jQuery = function(selector) {\n                if (selector === document) {\n                    return {\n                        ready: function(callback) {\n                            if (document.readyState === "loading") {\n                                document.addEventListener("DOMContentLoaded", callback, { once: true });\n                            } else {\n                                callback();\n                            }\n                        }\n                    };\n                }\n                const nodes = typeof selector === "string"\n                    ? Array.from(document.querySelectorAll(selector))\n                    : (selector ? [selector] : []);\n                return {\n                    hide: function() { nodes.forEach((node) => { node.style.display = "none"; }); return this; },\n                    show: function() { nodes.forEach((node) => { node.style.display = ""; }); return this; },\n                    prop: function(name, value) {\n                        if (value === undefined) {\n                            return nodes[0] ? nodes[0][name] : undefined;\n                        }\n                        nodes.forEach((node) => { node[name] = value; });\n                        return this;\n                    },\n                    val: function(value) {\n                        if (value === undefined) {\n                            return nodes[0] ? nodes[0].value : "";\n                        }\n                        nodes.forEach((node) => { node.value = value; });\n                        return this;\n                    },\n                    attr: function(name, value) {\n                        if (value === undefined) {\n                            return nodes[0] ? nodes[0].getAttribute(name) : undefined;\n                        }\n                        nodes.forEach((node) => { node.setAttribute(name, value); });\n                        return this;\n                    },\n                    on: function(name, handler) {\n                        nodes.forEach((node) => { node.addEventListener(name, handler); });\n                        return this;\n                    }\n                };\n            };\n            window.SignaturePad = function() {\n                this.clear = function() {};\n                this.isEmpty = function() { return true; };\n                this.toData = function() { return []; };\n                this.fromData = function() {};\n                this.toDataURL = function() { return "data:image/png;base64,stub"; };\n            };\n            '
        )
        page.route(
            "https://cdn.jsdelivr.net/**",
            lambda route: route.fulfill(body="", content_type="application/javascript"),
        )
        page.route(
            "http://ajax.googleapis.com/**",
            lambda route: route.fulfill(body="", content_type="application/javascript"),
        )
        page.route(
            "https://fonts.googleapis.com/**",
            lambda route: route.fulfill(body="", content_type="text/css"),
        )
        page.route(
            "https://www.w3schools.com/**",
            lambda route: route.fulfill(body="", content_type="text/css"),
        )
        try:
            yield page
        finally:
            browser.close()


def test_buzzer_browser_smoke(
    live_browser_server: object, browser_page: object
) -> None:
    """Test test buzzer browser smoke."""
    browser_page.goto(f"{live_browser_server.url}/")
    browser_page.wait_for_function(
        "window.updater && window.updater.socket && window.updater.socket.readyState === 1"
    )
    browser_page.evaluate("nameForm('Alice')")
    wait_until(
        lambda: (
            [player.name for player in live_browser_server.controller.connected_players]
            == ["Alice"]
        )
    )
    browser_page.wait_for_function("() => document.cookie.includes('token=')")
    browser_page.evaluate("buzz()")
    wait_until(lambda: live_browser_server.controller.buzzed_players == ["Alice"])
    assert live_browser_server.controller.buzzed_players == ["Alice"]


def test_lectern_browser_smoke(
    live_browser_server: object, browser_page: object
) -> None:
    """Test test lectern browser smoke."""
    player = Player("Alice", FakeWaiter(), 0)
    player.score = 1200
    live_browser_server.controller.new_player(player)
    browser_page.goto(f"{live_browser_server.url}/lectern?player=0")
    browser_page.wait_for_function(
        "window.updater && window.updater.socket && window.updater.socket.readyState === 1"
    )
    name = browser_page.locator("#player-name")
    score = browser_page.locator("#player-score")
    name.wait_for(state="visible")
    score.wait_for(state="visible")
    assert name.text_content() == "Alice"
    assert score.text_content() == "$1,200"
