"""Test browser smoke module."""

import asyncio
import threading
import time
from dataclasses import dataclass

import pytest
import tornado.httpserver
import tornado.ioloop
import tornado.netutil
from playwright.sync_api import sync_playwright

from jparty.domain.models import Player
from jparty.web.app import Application
from tests.server_fakes import FakeServerController

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


@dataclass
class LiveBrowserServer:
    """Test helper for livebrowserserver."""

    controller: FakeServerController
    url: str
    loop: tornado.ioloop.IOLoop
    thread: threading.Thread
    server: tornado.httpserver.HTTPServer


@pytest.fixture
def live_browser_server() -> object:
    """Test live browser server."""
    controller = FakeServerController()
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


def test_new_final_prompts_start_with_empty_boxes(
    live_browser_server: object, browser_page: object
) -> None:
    """A second Final's wager and answer boxes don't keep the first Final's text.

    When time runs out the phone sends whatever is in the answer box, so a
    leftover answer would be recorded for the next Final.
    """
    browser_page.goto(f"{live_browser_server.url}/")
    browser_page.wait_for_function(
        "window.updater && window.updater.socket && window.updater.socket.readyState === 1"
    )
    browser_page.evaluate("nameForm('Alice')")
    wait_until(lambda: len(live_browser_server.controller.connected_players) == 1)
    socket = live_browser_server.controller.connected_players[0].waiter

    def server_sends(msg: str, text: str = "") -> None:
        live_browser_server.loop.add_callback(socket.send, msg, text)

    wager_box = browser_page.locator("input[name='wager']")
    answer_box = browser_page.locator("input[name='answer']")
    # The page stylesheet hides each page and the test's jQuery stub only
    # sets inline styles, so wait on the page's own state, not visibility.
    current_page = "page => current_page === page"

    def type_into(name: str, text: str) -> None:
        browser_page.evaluate(
            "([name, text]) => {"
            " document.querySelector(`input[name='${name}']`).value = text; }",
            [name, text],
        )

    # First Final: the player types a wager and an answer.
    server_sends("PROMPTWAGER", "1000")
    browser_page.wait_for_function(current_page, arg="wager")
    type_into("wager", "500")
    server_sends("PROMPTANSWER")
    browser_page.wait_for_function(current_page, arg="answer")
    type_into("answer", "What is Ohio?")
    assert wager_box.input_value() == "500"
    assert answer_box.input_value() == "What is Ohio?"

    # Second Final: both prompts must start empty.
    server_sends("PROMPTWAGER", "2000")
    browser_page.wait_for_function(current_page, arg="wager")
    assert wager_box.input_value() == ""
    server_sends("PROMPTANSWER")
    browser_page.wait_for_function(current_page, arg="answer")
    assert answer_box.input_value() == ""


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
