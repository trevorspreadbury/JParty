"""Browser tests for the lectern signature XSS and full-game message (#62)."""

import pytest

from jparty.app.config import MAXPLAYERS
from jparty.domain.models import Player
from tests.e2e.test_browser_smoke import (  # noqa: F401  (pytest fixtures)
    FakeWaiter,
    browser_page,
    live_browser_server,
)

pytestmark = pytest.mark.e2e

CRAFTED_SIGNATURE = (
    'data:image/png;base64" onerror="window.__xss = true" data-x="'
    "<script>window.__xss = true</script>"
)


def test_crafted_signature_name_renders_as_image_without_running_script(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """A signature name is set as an image source, never parsed as HTML."""
    live_browser_server.controller.new_player(
        Player(CRAFTED_SIGNATURE, FakeWaiter(), 0)
    )

    browser_page.goto(f"{live_browser_server.url}/lectern?player=0")
    image = browser_page.locator("#player-name img")
    image.wait_for(state="attached")
    # Give a broken image time to fire ``onerror`` if it had one.
    browser_page.wait_for_function(
        "() => document.querySelector('#player-name img').complete"
    )
    browser_page.wait_for_timeout(200)

    assert image.count() == 1
    assert image.get_attribute("src") == CRAFTED_SIGNATURE
    assert image.get_attribute("onerror") is None
    assert browser_page.locator("#player-name script").count() == 0
    assert browser_page.evaluate("window.__xss") is None


def test_full_game_shows_full_message(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """A phone that joins a full game is told the game is full."""
    controller = live_browser_server.controller
    controller.connected_players = [object() for _ in range(MAXPLAYERS)]
    alerts = []

    def record_alert(dialog: object) -> None:
        alerts.append(dialog.message)
        dialog.dismiss()

    browser_page.on("dialog", record_alert)
    browser_page.goto(f"{live_browser_server.url}/")
    browser_page.wait_for_function(
        "window.updater && window.updater.socket && window.updater.socket.readyState === 1"
    )
    browser_page.evaluate("nameForm('Late')")

    # Playwright only delivers events while it is driving the page.
    for _ in range(50):
        if alerts:
            break
        browser_page.wait_for_timeout(100)
    assert alerts[0] == "Game has too many players!"


def test_double_tap_on_play_sends_one_name(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """A second tap before the server answers sends nothing (#99)."""
    browser_page.goto(f"{live_browser_server.url}/")
    browser_page.wait_for_function(
        "window.updater && window.updater.socket && window.updater.socket.readyState === 1"
    )
    sent = browser_page.evaluate(
        """() => {
            const names = [];
            const realSend = updater.socket.send.bind(updater.socket);
            updater.socket.send = (data) => {
                if (JSON.parse(data).message === "NAME") {
                    names.push(data);
                }
                realSend(data);
            };
            nameForm("Alice");
            nameForm("Alice");
            return {
                names: names.length,
                disabled: document.getElementById("submit-button").disabled,
            };
        }"""
    )

    assert sent == {"names": 1, "disabled": True}


COUNT_NEW_SOCKETS = """() => {
    window.__opened = 0;
    const RealWebSocket = window.WebSocket;
    window.WebSocket = function(url) {
        window.__opened++;
        return new RealWebSocket(url);
    };
    Object.assign(window.WebSocket, {CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3});
}"""


def open_lectern(page: object, url: str) -> None:
    """Open the lectern page for slot 0, wait for its socket, and count new ones."""
    page.goto(f"{url}/lectern?player=0")
    page.wait_for_function(
        "window.updater && updater.socket && updater.socket.readyState === 1"
    )
    page.evaluate(COUNT_NEW_SOCKETS)


def test_lectern_waits_for_its_reconnect_timer_when_shown(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """Showing the page while a reconnect is waiting opens no extra socket."""
    open_lectern(browser_page, live_browser_server.url)
    browser_page.evaluate("updater.reconnectDelay = 300; updater.socket.close()")
    browser_page.wait_for_function("updater.socket.readyState === 3")
    browser_page.wait_for_timeout(50)

    browser_page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    assert browser_page.evaluate("window.__opened") == 0

    browser_page.wait_for_function("updater.socket.readyState === 1")
    browser_page.wait_for_timeout(500)
    assert browser_page.evaluate("window.__opened") == 1


def test_lectern_opens_no_second_socket_while_connecting(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """Showing the page while its socket is still connecting opens no other."""
    open_lectern(browser_page, live_browser_server.url)

    opened = browser_page.evaluate(
        """() => {
            updater.socket.onclose = null;
            updater.socket.close();
            updater.start();
            document.dispatchEvent(new Event('visibilitychange'));
            return window.__opened;
        }"""
    )

    assert opened == 1


def test_replaced_lectern_stops_reconnecting(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """A lectern page whose slot is taken by another page stays closed."""
    open_lectern(browser_page, live_browser_server.url)
    browser_page.evaluate(
        """() => {
            updater.reconnectDelay = 100;
            window.__other = new WebSocket(
                "ws://" + location.host + "/lecternsocket?player=0"
            );
        }"""
    )
    browser_page.wait_for_function("updater.socket.readyState === 3")
    browser_page.wait_for_timeout(500)

    # Only the second page's socket was opened; the replaced page did not
    # reconnect and take the slot back.
    assert browser_page.evaluate("window.__opened") == 1
    assert browser_page.evaluate("window.__other.readyState") == 1
    assert (
        browser_page.locator("#player-name").text_content()
        == "Opened on another screen"
    )
