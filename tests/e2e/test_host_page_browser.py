"""Drive the host's /host phone page in a browser."""

import pytest

from jparty.domain.tournament_host import HostPage, HostPlayer, HostPrompt
from tests.e2e.test_browser_smoke import (  # noqa: F401  (pytest fixtures)
    browser_page,
    live_browser_server,
    wait_until,
)

pytestmark = pytest.mark.e2e

PAGE = HostPage(
    "Fun",
    (
        HostPlayer("p2", "Cy", "Cy", (HostPrompt(1, "Juggles"),), seat=3),
        HostPlayer(
            "p0",
            "Ann",
            "A teacher from Chicago, Ann Lee",
            (HostPrompt(1, "Has a cat"), HostPrompt(2, "Sings", True)),
            seat=1,
        ),
    ),
    in_game=True,
)


def visible_name(page: object) -> str:
    """Return the name on the card being shown."""
    return page.locator(".player:not([hidden]) .name").inner_text()


def test_cards_step_through_the_players_one_at_a_time(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """Next and Previous move between players, and the ends are disabled."""
    live_browser_server.controller.host_page = lambda: PAGE
    browser_page.goto(f"{live_browser_server.url}/host")
    assert visible_name(browser_page) == "Cy"
    assert browser_page.locator("#previous").is_disabled()
    browser_page.click("#next")
    assert visible_name(browser_page) == "Ann"
    assert browser_page.locator("#next").is_disabled()
    assert browser_page.locator(
        ".player:not([hidden]) input[data-prompt='2']"
    ).is_checked()


def test_a_tick_that_cant_be_saved_flips_back_and_says_why(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """The box goes back to unticked, and the page shows the reason."""
    controller = live_browser_server.controller
    controller.host_page = lambda: PAGE
    controller.mark_host_prompt = lambda *_args: "Couldn't save used_prompts.csv."
    browser_page.goto(f"{live_browser_server.url}/host")
    box = browser_page.locator(".player:not([hidden]) input[data-prompt='1']")
    box.check()
    problem = browser_page.locator("#save-problem")
    wait_until(lambda: problem.is_visible())
    assert not box.is_checked()
    assert "Couldn't save used_prompts.csv." in problem.inner_text()


def test_a_saved_tick_is_crossed_out(
    live_browser_server: object,  # noqa: F811
    browser_page: object,  # noqa: F811
) -> None:
    """A tick the server saves stays ticked, crossed out, with no problem shown."""
    controller = live_browser_server.controller
    controller.host_page = lambda: PAGE
    saved = []
    controller.mark_host_prompt = lambda *args: saved.append(args) or ""
    browser_page.goto(f"{live_browser_server.url}/host")
    box = browser_page.locator(".player:not([hidden]) input[data-prompt='1']")
    box.check()
    wait_until(lambda: saved == [("p2", 1, True)])
    assert box.is_checked()
    assert "used" in box.locator("xpath=..").get_attribute("class")
    assert not browser_page.locator("#save-problem").is_visible()
