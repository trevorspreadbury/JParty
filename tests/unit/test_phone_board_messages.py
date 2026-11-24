"""Unit tests for the phone messages that pick clues and wager on Daily Doubles.

No Tornado loop runs here, so the controller sends to the fake sockets right
away.
"""

import json
from types import SimpleNamespace

import pytest

from jparty.domain.models import Player
from jparty.web.controller import BuzzerController
from jparty.web.handlers import parse_pick

pytestmark = pytest.mark.unit


class FakeSocket:
    """Stand-in for a phone's websocket connection."""

    def __init__(self) -> None:
        """Start with no messages."""
        self.sent = []

    def send(self, msg: str, text: str = "") -> None:
        """Record an outgoing message."""
        self.sent.append((msg, text))


class Signal:
    """Stand-in Qt signal that records emits."""

    def __init__(self) -> None:
        """Start with no emits."""
        self.emits = []

    def emit(self, *args: object) -> None:
        """Record one emit."""
        self.emits.append(args)


@pytest.fixture
def setup() -> SimpleNamespace:
    """Return a real controller with two seated players on fake phones."""
    alice = Player("Alice", FakeSocket(), 0)
    bob = Player("Bob", FakeSocket(), 1)
    game = SimpleNamespace(
        players=[alice, bob],
        pick_trigger=Signal(),
        dd_wager_trigger=Signal(),
        wager_trigger=Signal(),
        new_player_trigger=Signal(),
    )
    controller = BuzzerController(game)
    controller.run_on_loop = lambda callback, *args: callback(*args)
    controller.connected_players = [alice, bob]
    return SimpleNamespace(controller=controller, game=game, alice=alice, bob=bob)


BOARD = {"categories": ["A", "B"], "rows": [[200, None]]}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0,0", (0, 0)),
        ("5, 4", (5, 4)),
        ("1", None),
        ("1,2,3", None),
        ("a,b", None),
        ("-1,0", None),
        ("0,999", None),
        (None, None),
        (7, None),
    ],
)
def test_parse_pick(text: object, expected: object) -> None:
    """Only two small non-negative whole numbers make a pick."""
    assert parse_pick(text) == expected


def test_prompt_pick_shows_the_board(setup: SimpleNamespace) -> None:
    """The player in control's phone gets the board to pick from."""
    setup.controller.prompt_pick(setup.alice, BOARD)
    assert setup.alice.page == "pick"
    assert setup.alice.waiter.sent == [("PROMPTPICK", json.dumps(BOARD))]
    assert setup.alice.state() == {"page": "pick", "score": 0, "page_data": BOARD}


def test_offering_the_board_to_a_new_player_takes_it_back(
    setup: SimpleNamespace,
) -> None:
    """Only one phone shows the board at a time."""
    setup.controller.prompt_pick(setup.alice, BOARD)
    setup.controller.prompt_pick(setup.bob, BOARD)
    assert setup.alice.page == "buzz"
    assert setup.alice.waiter.sent[-1] == ("SHOW_PAGE", "buzz")
    assert setup.bob.page == "pick"


def test_pick_goes_to_the_game_and_the_buzzer_comes_back(
    setup: SimpleNamespace,
) -> None:
    """The phone can buzz on the clue it just picked."""
    setup.controller.prompt_pick(setup.alice, BOARD)

    setup.controller.pick(setup.alice, 0, 0)

    assert setup.game.pick_trigger.emits == [(0, 0, 0)]
    assert setup.alice.page == "buzz"
    assert setup.alice.state() == {"page": "buzz", "score": 0}
    assert setup.alice.waiter.sent[-1] == ("SHOW_PAGE", "buzz")


def test_pick_without_the_board_is_ignored(setup: SimpleNamespace) -> None:
    """A phone not offered the board can't pick."""
    setup.controller.pick(setup.bob, 0, 0)
    setup.controller.pick(None, 0, 0)
    assert setup.game.pick_trigger.emits == []


def test_end_pick_returns_phones_to_the_buzzer(setup: SimpleNamespace) -> None:
    """When a clue is picked any other way, the board leaves the phone."""
    setup.controller.prompt_pick(setup.alice, BOARD)
    setup.controller.end_pick()
    assert setup.alice.page == "buzz"
    assert setup.alice.waiter.sent[-1] == ("SHOW_PAGE", "buzz")


def test_daily_double_wager_goes_to_the_game(setup: SimpleNamespace) -> None:
    """A Daily Double wager is sent as one, not as a Final wager."""
    setup.controller.prompt_dd_wager(setup.alice, 5, 1000)
    assert setup.alice.waiter.sent == [
        ("PROMPTDDWAGER", json.dumps({"min": 5, "max": 1000}))
    ]
    assert setup.alice.state()["page_data"] == {"min": 5, "max": 1000}

    setup.controller.wager(setup.alice, 750)

    assert setup.game.dd_wager_trigger.emits == [(0, 750)]
    assert setup.game.wager_trigger.emits == []
    assert setup.alice.waiter.sent[-1] == ("SHOW_PAGE", "buzz")
    setup.controller.wager(setup.alice, 750)
    assert setup.game.dd_wager_trigger.emits == [(0, 750)]


def test_end_dd_wager_withdraws_the_prompt(setup: SimpleNamespace) -> None:
    """When the host enters the wager, the phone goes back to its buzzer."""
    setup.controller.prompt_dd_wager(setup.alice, 5, 1000)
    setup.controller.end_dd_wager()
    assert setup.alice.page == "buzz"
    assert setup.alice.waiter.sent[-1] == ("SHOW_PAGE", "buzz")
