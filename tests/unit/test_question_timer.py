"""Tests for the real ``QuestionTimer`` (other tests use a fake timer)."""

import threading

import pytest

from jparty.domain.input import QuestionTimer

pytestmark = pytest.mark.unit

FIRE_TIMEOUT_SECONDS = 1.0


def test_timer_that_ran_out_while_paused_fires_on_resume() -> None:
    """A resumed timer with no time left fires right away.

    When more time has elapsed than the interval, the remaining time is
    negative. ``time.sleep`` rejects negative values, so without the clamp the
    timer thread would crash and the clue would never time out.
    """
    fired = threading.Event()
    timer = QuestionTimer(0.01, fired.set)
    timer._elapsed_time = 0.5

    timer.start()

    assert fired.wait(FIRE_TIMEOUT_SECONDS)


def test_cancelled_timer_does_not_fire() -> None:
    """Cancelling before the interval ends stops the callback."""
    fired = threading.Event()
    timer = QuestionTimer(0.2, fired.set)

    timer.start()
    timer.cancel()

    assert not fired.wait(0.4)
