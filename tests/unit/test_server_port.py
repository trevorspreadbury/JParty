"""Unit tests for how the buzzer server picks its port (#46).

Lecterns stay open on the usual port across JParty restarts, so a restart
should wait a moment for that port instead of moving to the next one.
"""

from types import SimpleNamespace

import pytest

from jparty.app.config import PORT
from jparty.web import controller as controller_module
from jparty.web.controller import BuzzerController

pytestmark = pytest.mark.unit


class FlakyApp:
    """Stand-in Tornado app whose ``listen`` fails a set number of times."""

    def __init__(self, failures: int) -> None:
        """Fail the first ``failures`` calls to ``listen``."""
        self.failures = failures
        self.ports = []

    def listen(self, port: int) -> None:
        """Record the port, then fail while failures remain."""
        self.ports.append(port)
        if self.failures > 0:
            self.failures -= 1
            raise OSError("address in use")


@pytest.fixture
def controller(monkeypatch: pytest.MonkeyPatch) -> BuzzerController:
    """Return a controller whose waits between tries take no time."""
    monkeypatch.setattr(controller_module, "PORT_BUSY_RETRY_SECONDS", 0)
    return BuzzerController(SimpleNamespace(players=[]))


def test_usual_port_is_retried_while_briefly_busy(
    controller: BuzzerController,
) -> None:
    """A port freed a moment after a restart is used, not the next one."""
    controller.app = FlakyApp(failures=3)

    controller._listen()

    assert controller.app.ports == [PORT] * 4
    assert controller.port == PORT


def test_server_moves_on_when_the_usual_port_stays_busy(
    controller: BuzzerController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the wait is over, the next port is tried, and only once each."""
    monkeypatch.setattr(controller_module, "PORT_BUSY_WAIT_SECONDS", 0)
    controller.app = FlakyApp(failures=2)
    controller.loop = None
    monkeypatch.setattr(
        controller_module.tornado.ioloop.IOLoop,
        "current",
        staticmethod(lambda: SimpleNamespace(start=lambda: None)),
    )

    controller.start(threaded=False)

    assert controller.app.ports == [PORT, PORT + 1, PORT + 2]
    assert controller.port == PORT + 2
