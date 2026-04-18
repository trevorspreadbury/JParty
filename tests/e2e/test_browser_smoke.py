import asyncio
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
import tornado.httpserver
import tornado.ioloop
import tornado.netutil
from playwright.sync_api import sync_playwright

from jparty.domain.models import Player
from jparty.web.app import Application


pytestmark = pytest.mark.e2e


def wait_until(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition was not met before timeout")


class FakeWaiter:
    def close(self):
        return None


class BrowserSmokeController:
    def __init__(self):
        self.connected_players = []
        self.accepting_players = True
        self.lectern_connections = {}
        self.buzzed_players = []
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
        self.buzzed_players.append(player.name)

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


@dataclass
class LiveBrowserServer:
    controller: BrowserSmokeController
    url: str
    loop: tornado.ioloop.IOLoop
    thread: threading.Thread
    server: tornado.httpserver.HTTPServer


@pytest.fixture
def live_browser_server():
    controller = BrowserSmokeController()
    app = Application(controller)
    sockets = tornado.netutil.bind_sockets(0, address="127.0.0.1")
    port = sockets[0].getsockname()[1]
    ready = threading.Event()
    state = {}

    def run():
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
def browser_page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.add_init_script(
            """
            window.$ = window.jQuery = function(selector) {
                if (selector === document) {
                    return {
                        ready: function(callback) {
                            if (document.readyState === "loading") {
                                document.addEventListener("DOMContentLoaded", callback, { once: true });
                            } else {
                                callback();
                            }
                        }
                    };
                }
                const nodes = typeof selector === "string"
                    ? Array.from(document.querySelectorAll(selector))
                    : (selector ? [selector] : []);
                return {
                    hide: function() { nodes.forEach((node) => { node.style.display = "none"; }); return this; },
                    show: function() { nodes.forEach((node) => { node.style.display = ""; }); return this; },
                    prop: function(name, value) {
                        if (value === undefined) {
                            return nodes[0] ? nodes[0][name] : undefined;
                        }
                        nodes.forEach((node) => { node[name] = value; });
                        return this;
                    },
                    val: function(value) {
                        if (value === undefined) {
                            return nodes[0] ? nodes[0].value : "";
                        }
                        nodes.forEach((node) => { node.value = value; });
                        return this;
                    },
                    attr: function(name, value) {
                        if (value === undefined) {
                            return nodes[0] ? nodes[0].getAttribute(name) : undefined;
                        }
                        nodes.forEach((node) => { node.setAttribute(name, value); });
                        return this;
                    },
                    on: function(name, handler) {
                        nodes.forEach((node) => { node.addEventListener(name, handler); });
                        return this;
                    }
                };
            };
            window.SignaturePad = function() {
                this.clear = function() {};
                this.isEmpty = function() { return true; };
                this.toData = function() { return []; };
                this.fromData = function() {};
                this.toDataURL = function() { return "data:image/png;base64,stub"; };
            };
            """
        )
        page.route("https://cdn.jsdelivr.net/**", lambda route: route.fulfill(body="", content_type="application/javascript"))
        page.route("http://ajax.googleapis.com/**", lambda route: route.fulfill(body="", content_type="application/javascript"))
        page.route("https://fonts.googleapis.com/**", lambda route: route.fulfill(body="", content_type="text/css"))
        page.route("https://www.w3schools.com/**", lambda route: route.fulfill(body="", content_type="text/css"))
        try:
            yield page
        finally:
            browser.close()


def test_buzzer_browser_smoke(live_browser_server, browser_page):
    browser_page.goto(f"{live_browser_server.url}/")
    browser_page.wait_for_function("window.updater && window.updater.socket && window.updater.socket.readyState === 1")
    browser_page.evaluate("nameForm('Alice')")
    wait_until(lambda: [player.name for player in live_browser_server.controller.connected_players] == ["Alice"])
    browser_page.wait_for_function("() => document.cookie.includes('token=')")
    browser_page.evaluate("buzz()")
    wait_until(lambda: live_browser_server.controller.buzzed_players == ["Alice"])

    assert live_browser_server.controller.buzzed_players == ["Alice"]


def test_lectern_browser_smoke(live_browser_server, browser_page):
    player = Player("Alice", FakeWaiter(), 0)
    player.score = 1200
    live_browser_server.controller.new_player(player)

    browser_page.goto(f"{live_browser_server.url}/lectern?player=0")
    browser_page.wait_for_function("window.updater && window.updater.socket && window.updater.socket.readyState === 1")

    name = browser_page.locator("#player-name")
    score = browser_page.locator("#player-score")
    name.wait_for(state="visible")
    score.wait_for(state="visible")

    assert name.text_content() == "Alice"
    assert score.text_content() == "$1,200"
