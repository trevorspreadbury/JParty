"""Test setting up a lectern from the keyboard (#46).

Lectern laptops sit behind the lecterns with their screen out of sight, so
everything a host needs works without the mouse: choosing the seat (1-6),
full screen (F), and turning the page for a monitor on its side (R).
"""

import pytest
from tornado.testing import AsyncHTTPTestCase as TornadoAsyncHTTPTestCase

from jparty.app.config import MAXPLAYERS
from jparty.domain.models import Player
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


class LecternPageTest(TornadoAsyncHTTPTestCase):
    """Check what the lectern page is rendered with."""

    __test__ = True

    def runTest(self) -> None:
        """Satisfy ``unittest`` when the case is built without a method name."""

    def get_app(self) -> object:
        """Build the app around a real controller."""
        from types import SimpleNamespace

        return BuzzerController(SimpleNamespace(players=[])).app

    def test_lectern_page_without_a_seat_asks_for_one(self) -> None:
        """``/lectern`` alone no longer means seat 1; the page picks or asks."""
        response = self.fetch("/lectern")
        assert response.code == 200
        assert b"var playerNumber = null;" in response.body
        assert f"var maxPlayers = {MAXPLAYERS};".encode() in response.body


def seat(live_server: object, name: str, number: int) -> Player:
    """Seat a player in the live server's game."""
    player = Player(name, FakeWaiter(), number)
    live_server.controller.new_player(player)
    return player


def count_loads(page: object) -> list:
    """Return a list that grows by one each time ``page`` loads."""
    loads = []
    page.on("load", lambda _page: loads.append(1))
    return loads


def test_lectern_with_no_seat_shows_the_picker_and_waits(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """Nothing connects until a seat is chosen."""
    browser_page.goto(f"{live_browser_server.url}/lectern")
    picker = browser_page.locator("#seat-picker")
    picker.wait_for(state="visible")

    assert browser_page.locator("#seat-picker-buttons button").count() == MAXPLAYERS
    assert browser_page.evaluate("updater.socket") is None
    assert live_browser_server.controller.lectern_connections == {}


def test_number_key_chooses_the_seat_without_reloading(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """Pressing 2 shows seat 2 (``player=1``) and saves the choice."""
    seat(live_browser_server, "Alice", 0)
    seat(live_browser_server, "Bob", 1)
    browser_page.goto(f"{live_browser_server.url}/lectern")
    browser_page.locator("#seat-picker").wait_for(state="visible")
    loads = count_loads(browser_page)

    browser_page.keyboard.press("2")
    browser_page.wait_for_function(SOCKET_OPEN)
    browser_page.locator("#player-name").wait_for(state="visible")

    assert browser_page.locator("#player-name").text_content() == "Bob"
    assert browser_page.locator("#seat-picker").is_hidden()
    assert browser_page.locator("#lectern-toast-seat").text_content() == "Lectern 2"
    assert "player=1" in browser_page.url
    assert loads == []
    wait_until(lambda: list(live_browser_server.controller.lectern_connections) == [1])


def test_lectern_reopens_the_seat_it_used_last(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """The same plain address opens the seat this browser chose before."""
    seat(live_browser_server, "Cara", 2)
    browser_page.goto(f"{live_browser_server.url}/lectern")
    browser_page.locator("#seat-picker").wait_for(state="visible")
    browser_page.keyboard.press("3")
    browser_page.wait_for_function(SOCKET_OPEN)

    browser_page.goto(f"{live_browser_server.url}/lectern")
    browser_page.wait_for_function(SOCKET_OPEN)

    assert browser_page.locator("#seat-picker").is_hidden()
    assert browser_page.evaluate("updater.playerNumber") == 2
    browser_page.locator("#player-name").wait_for(state="visible")
    assert browser_page.locator("#player-name").text_content() == "Cara"


def test_seat_in_the_address_wins_over_the_remembered_seat(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """``player=`` in the address is used even if another seat was saved."""
    browser_page.goto(f"{live_browser_server.url}/lectern?player=4")
    browser_page.wait_for_function(SOCKET_OPEN)

    browser_page.goto(f"{live_browser_server.url}/lectern?player=0")
    browser_page.wait_for_function(SOCKET_OPEN)

    assert browser_page.evaluate("updater.playerNumber") == 0
    assert browser_page.evaluate("localStorage.getItem('jparty-lectern-seat')") == "0"


def test_number_key_moves_a_connected_lectern_to_another_seat(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """Changing seats swaps the connection without a reload."""
    seat(live_browser_server, "Alice", 0)
    seat(live_browser_server, "Cara", 2)
    browser_page.goto(f"{live_browser_server.url}/lectern?player=0")
    browser_page.wait_for_function(SOCKET_OPEN)
    loads = count_loads(browser_page)

    browser_page.keyboard.press("3")
    browser_page.wait_for_function("updater.playerNumber === 2 && " + SOCKET_OPEN)
    browser_page.wait_for_function(
        "document.getElementById('player-name').textContent === 'Cara'"
    )

    assert loads == []
    wait_until(lambda: list(live_browser_server.controller.lectern_connections) == [2])


def test_replaced_lectern_can_choose_a_seat_again(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """A lectern bumped off its seat by another screen can pick a new one."""
    seat(live_browser_server, "Bob", 1)
    browser_page.goto(f"{live_browser_server.url}/lectern?player=0")
    browser_page.wait_for_function(SOCKET_OPEN)
    browser_page.evaluate(
        "window.__other = new WebSocket("
        "'ws://' + location.host + '/lecternsocket?player=0')"
    )
    browser_page.wait_for_function("updater.replaced === true")

    browser_page.keyboard.press("2")
    browser_page.wait_for_function("updater.playerNumber === 1 && " + SOCKET_OPEN)

    assert browser_page.evaluate("updater.replaced") is False
    browser_page.wait_for_function(
        "document.getElementById('player-name').textContent === 'Bob'"
    )


def body_rotation(page: object) -> int:
    """Return the rotation the page is drawn at, from the body's class."""
    return page.evaluate(
        """() => {
            const match = document.body.className.match(/rotate-(\\d+)/);
            return match ? parseInt(match[1], 10) : 0;
        }"""
    )


def test_r_turns_the_lectern_and_shift_r_turns_it_back(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """R steps through quarter turns, and the choice is kept."""
    browser_page.goto(f"{live_browser_server.url}/lectern?player=0")
    browser_page.wait_for_function(SOCKET_OPEN)
    seen = []
    for _ in range(4):
        browser_page.keyboard.press("r")
        seen.append(body_rotation(browser_page))
    browser_page.keyboard.press("Shift+R")
    seen.append(body_rotation(browser_page))

    assert seen == [90, 180, 270, 0, 270]
    assert "rotate=270" in browser_page.url

    browser_page.goto(f"{live_browser_server.url}/lectern?player=0")
    browser_page.wait_for_function(SOCKET_OPEN)
    assert body_rotation(browser_page) == 270


@pytest.mark.parametrize(
    ("value", "expected"),
    [("90", 90), ("right", 90), ("left", 270), ("180", 180), ("45", 0), ("x", 0)],
)
def test_rotation_can_be_set_in_the_address(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
    value: str,
    expected: int,
) -> None:
    """``rotate=`` takes degrees or left/right; anything else means upright."""
    browser_page.goto(f"{live_browser_server.url}/lectern?player=0&rotate={value}")
    browser_page.wait_for_function(SOCKET_OPEN)

    assert body_rotation(browser_page) == expected


def test_turned_lectern_fills_the_screen_in_portrait(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """Turned a quarter turn, the lectern is drawn tall and fills the window."""
    seat(live_browser_server, "Alice", 0)
    browser_page.set_viewport_size({"width": 1280, "height": 720})
    browser_page.goto(f"{live_browser_server.url}/lectern?player=0&rotate=90")
    browser_page.wait_for_function(SOCKET_OPEN)
    browser_page.locator("#player-name").wait_for(state="visible")
    browser_page.wait_for_timeout(300)

    layout = browser_page.evaluate(
        """() => {
            const box = document.getElementById('lectern-container');
            const rect = box.getBoundingClientRect();
            const height = (id) => document.getElementById(id).offsetHeight;
            return {
                rect: [rect.left, rect.top, rect.width, rect.height],
                size: [box.clientWidth, box.clientHeight],
                answeringBottom:
                    height('lights-container') + height('score-box')
                    + height('answering-box'),
            };
        }"""
    )

    assert [round(v) for v in layout["rect"]] == [0, 0, 1280, 720]
    assert layout["size"] == [720, 1280]
    # The answering box ends 13.5/28.1 of the way down the tall lectern.
    assert abs(layout["answeringBottom"] - 13.5 / 28.1 * 1280) <= 2


def test_f_toggles_full_screen_and_ctrl_f_is_left_alone(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """F asks the browser for full screen, and asks to leave it the second time."""
    browser_page.goto(f"{live_browser_server.url}/lectern?player=0")
    browser_page.wait_for_function(SOCKET_OPEN)
    browser_page.evaluate(
        """() => {
            window.__calls = [];
            window.__full = false;
            Object.defineProperty(document, 'fullscreenElement', {
                get: () => window.__full ? document.documentElement : null,
            });
            document.documentElement.requestFullscreen = () => {
                window.__calls.push('enter');
                window.__full = true;
                return Promise.resolve();
            };
            document.exitFullscreen = () => {
                window.__calls.push('exit');
                window.__full = false;
                return Promise.resolve();
            };
        }"""
    )

    browser_page.keyboard.press("Control+f")
    browser_page.keyboard.press("f")
    browser_page.keyboard.press("F")

    assert browser_page.evaluate("window.__calls") == ["enter", "exit"]


def test_cursor_hides_when_the_mouse_is_still(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """The cursor disappears after a moment and comes back when moved."""
    browser_page.goto(f"{live_browser_server.url}/lectern?player=0")
    browser_page.wait_for_function(SOCKET_OPEN)
    browser_page.evaluate(
        "lecternControls.cursorHideAfter = 100; lecternControls.showCursor()"
    )
    browser_page.wait_for_function("document.body.classList.contains('cursor-hidden')")

    browser_page.mouse.move(50, 50)
    browser_page.mouse.move(60, 60)

    assert (
        browser_page.evaluate("document.body.classList.contains('cursor-hidden')")
        is False
    )
