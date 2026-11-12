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
