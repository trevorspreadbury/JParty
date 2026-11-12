"""Tests for the fake clock the ``game`` fixture installs."""

import time

import pytest
from pytestqt.exceptions import TimeoutError as QtBotTimeoutError

import jparty.domain.game_engine as game_module
import jparty.domain.gameplay as gameplay_module

pytestmark = pytest.mark.integration


def test_game_fixture_fakes_the_game_clock(
    game: object, time_controller: object
) -> None:
    """The game modules read the controlled clock."""
    time_controller.set(1234.0)

    assert game_module.time.time() == 1234.0
    assert gameplay_module.time.time() == 1234.0


def test_game_fixture_leaves_the_real_clock_alone(
    game: object, time_controller: object
) -> None:
    """The shared ``time`` module keeps the real clock."""
    assert time.time() != time_controller.time()


def test_wait_until_still_times_out_with_the_game_fixture(
    game: object, qtbot: object
) -> None:
    """A failing ``qtbot.waitUntil`` must fail, not hang the test run."""
    with pytest.raises(QtBotTimeoutError):
        qtbot.waitUntil(lambda: False, timeout=200)
