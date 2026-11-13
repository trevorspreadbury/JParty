"""Test that the buzzer controller writes to sockets on the Tornado thread."""

import threading

import pytest
import tornado.ioloop

from jparty.domain import Player
from jparty.web.controller import BuzzerController

pytestmark = pytest.mark.integration


class ThreadRecordingSocket:
    """Stand-in websocket that records which thread each call ran on."""

    def __init__(self) -> None:
        """Start with no player and no calls."""
        self.player = None
        self.sent = []
        self.closed_on = None

    def send(self, msg: str, text: str = "") -> None:
        """Record an outgoing message and the thread that sent it."""
        self.sent.append((msg, threading.current_thread()))

    def close(self) -> None:
        """Record the thread that closed the socket."""
        self.closed_on = threading.current_thread()


@pytest.fixture
def running_loop() -> object:
    """Run a Tornado loop on a background thread, as the app does."""
    loop = tornado.ioloop.IOLoop(make_current=False)
    thread = threading.Thread(target=loop.start, daemon=True)
    thread.start()
    yield loop, thread
    loop.add_callback(loop.stop)
    thread.join(timeout=5)
    loop.close()


@pytest.fixture
def controller(game: object, running_loop: object) -> object:
    """Return a real controller attached to the background loop."""
    controller = BuzzerController(game)
    loop, thread = running_loop
    controller.loop = loop
    controller._loop_thread_id = thread.ident
    game.buzzer_controller = controller
    return controller


def _wait_for(condition: object) -> None:
    """Wait up to five seconds for ``condition`` to become true."""
    event = threading.Event()
    for _ in range(500):
        if condition():
            return
        event.wait(0.01)
    raise AssertionError("condition was not met in time")


def test_sends_from_qt_thread_run_on_loop_thread(
    controller: BuzzerController, running_loop: object
) -> None:
    """Test player and lectern writes made on the Qt thread go through the loop."""
    _, loop_thread = running_loop
    socket = ThreadRecordingSocket()
    lectern = ThreadRecordingSocket()
    player = Player("Alice", socket, 0)
    controller.connected_players = [player]
    controller.lectern_connections[0] = lectern

    controller.open_wagers()
    controller.prompt_answers()
    controller.toolate()
    controller.broadcast_to_lecterns(0, controller.get_player_state_dict(player))
    controller.restart()

    _wait_for(lambda: len(socket.sent) == 3 and lectern.sent and socket.closed_on)
    assert [msg for msg, _ in socket.sent] == ["PROMPTWAGER", "PROMPTANSWER", "TOOLATE"]
    assert {thread for _, thread in socket.sent} == {loop_thread}
    assert lectern.sent[0] == ("PLAYER_STATE", loop_thread)
    assert socket.closed_on is loop_thread


def test_saved_player_reclaim_updates_sockets_on_loop_thread(
    controller: BuzzerController, running_loop: object
) -> None:
    """Test loading a save resets open phones from the loop thread."""
    _, loop_thread = running_loop
    socket = ThreadRecordingSocket()
    socket.player = Player("Old", socket, 0)
    controller.register_socket(socket)

    controller.begin_saved_player_reclaim(
        [{"name": "Alice", "player_number": 0}, {"name": "Bob", "player_number": 1}]
    )

    assert controller.saved_player_total_count() == 2
    _wait_for(lambda: len(socket.sent) == 2)
    assert socket.sent == [("LOGOUT", loop_thread), ("SHOW_CHOOSER", loop_thread)]
    assert socket.player is None


def test_saved_player_reclaim_logs_out_extra_phones_on_loop_thread(
    controller: BuzzerController, running_loop: object
) -> None:
    """Test a save with fewer players than open phones logs every phone out.

    Each phone is asked to reconnect and then closed, all from the loop thread.
    """
    _, loop_thread = running_loop
    sockets = [ThreadRecordingSocket() for _ in range(3)]
    for socket in sockets:
        controller.register_socket(socket)

    controller.begin_saved_player_reclaim(
        [{"name": "Alice", "player_number": 0}, {"name": "Bob", "player_number": 1}]
    )

    _wait_for(lambda: all(socket.closed_on for socket in sockets))
    for socket in sockets:
        assert socket.sent == [("LOGOUT", loop_thread)]
        assert socket.closed_on is loop_thread


def test_sends_run_directly_when_no_loop_has_started(game: object) -> None:
    """Test sends happen right away before the server loop starts."""
    controller = BuzzerController(game)
    socket = ThreadRecordingSocket()
    controller.connected_players = [Player("Alice", socket, 0)]

    controller.toolate()

    assert socket.sent == [("TOOLATE", threading.main_thread())]
