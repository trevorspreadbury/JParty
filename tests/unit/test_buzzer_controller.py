"""Unit tests for saved-player claim and reclaim in the real ``BuzzerController``.

No Tornado loop runs here, so the controller sends to the fake sockets right
away and every message can be checked in order.
"""

import json
from types import SimpleNamespace

import pytest

from jparty.domain.models import Player
from jparty.web.controller import BuzzerController

pytestmark = pytest.mark.unit

SIGNATURE_NAME = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAA+/x=="
SAVED_PLAYERS = [
    {"name": "Alice", "player_number": 0},
    {"name": SIGNATURE_NAME, "player_number": 1},
]


class FakeSocket:
    """Stand-in for a phone's websocket connection."""

    def __init__(self) -> None:
        """Start with no player, no messages, and an open connection."""
        self.player = None
        self.sent = []
        self.closed = False

    def send(self, msg: str, text: str = "") -> None:
        """Record an outgoing message."""
        self.sent.append((msg, text))

    def close(self) -> None:
        """Record that the socket was closed."""
        self.closed = True

    def messages(self) -> list[str]:
        """Return the message types sent so far."""
        return [msg for msg, _ in self.sent]

    def last_chooser(self) -> dict:
        """Return the payload of the last ``SHOW_CHOOSER`` message."""
        payloads = [text for msg, text in self.sent if msg == "SHOW_CHOOSER"]
        return json.loads(payloads[-1])


class Signal:
    """Stand-in Qt signal that counts emits."""

    def __init__(self) -> None:
        """Start with no emits."""
        self.emits = 0

    def emit(self, *args: object) -> None:
        """Count one emit."""
        self.emits += 1


@pytest.fixture
def controller() -> BuzzerController:
    """Return a real controller attached to a minimal game stub."""
    game = SimpleNamespace(players=[], new_player_trigger=Signal())
    return BuzzerController(game)


@pytest.fixture
def lobby(controller: BuzzerController) -> BuzzerController:
    """Return a controller reclaiming Alice and a player with a signature name."""
    controller.begin_saved_player_reclaim(SAVED_PLAYERS)
    return controller


def _connect(controller: BuzzerController) -> FakeSocket:
    """Open a new phone connection."""
    socket = FakeSocket()
    controller.register_socket(socket)
    return socket


def test_reclaim_offers_saved_names_including_signatures(
    controller: BuzzerController,
) -> None:
    """Saved names, including drawn signatures, are offered unchanged."""
    waiting = _connect(controller)

    controller.begin_saved_player_reclaim(SAVED_PLAYERS)

    assert controller.in_saved_player_reclaim_mode()
    assert waiting.messages() == ["LOGOUT", "SHOW_CHOOSER"]
    assert waiting.last_chooser() == {
        "players": [
            {"name": "Alice", "player_number": 0, "claimed": False},
            {"name": SIGNATURE_NAME, "player_number": 1, "claimed": False},
        ],
        "claimed_count": 0,
        "total_count": 2,
    }


def test_reclaim_skips_saved_entries_without_a_name_or_number(
    controller: BuzzerController,
) -> None:
    """Broken saved entries are left out instead of becoming blank players."""
    controller.begin_saved_player_reclaim(
        [
            {"name": "Alice", "player_number": 0},
            {"player_number": 1},
            {"name": "Bob"},
            {"name": "Cara", "player_number": "not a number"},
        ]
    )

    assert [
        choice["name"]
        for choice in controller.saved_player_choices_payload()["players"]
    ] == ["Alice"]


def test_reclaim_logs_out_phones_when_there_are_too_many(
    controller: BuzzerController,
) -> None:
    """More open phones than saved players are asked to reconnect."""
    sockets = [_connect(controller) for _ in range(3)]

    controller.begin_saved_player_reclaim(SAVED_PLAYERS)

    for socket in sockets:
        assert socket.messages() == ["LOGOUT"]
        assert socket.closed


def test_claiming_a_signature_profile_restores_its_name(
    lobby: BuzzerController,
) -> None:
    """The claimed player gets the saved signature name and seat."""
    socket = _connect(lobby)

    player = lobby.claim_saved_player(socket, 1)

    assert player.name == SIGNATURE_NAME
    assert player.player_number == 1
    assert player.waiter is socket
    assert player.page == "buzz"
    assert socket.player is player
    assert lobby.connected_players == [player]
    assert lobby.claimed_saved_players() == [player]
    assert lobby.game.new_player_trigger.emits == 2


def test_claims_update_chooser_and_completion(lobby: BuzzerController) -> None:
    """Phones still choosing see claimed slots, and the lobby knows when all are in."""
    alice_socket = _connect(lobby)
    waiting = _connect(lobby)

    lobby.claim_saved_player(alice_socket, 0)

    assert lobby.saved_player_claim_count() == 1
    assert not lobby.saved_player_claims_complete()
    chooser = waiting.last_chooser()
    assert chooser["claimed_count"] == 1
    assert [choice["claimed"] for choice in chooser["players"]] == [True, False]
    assert "SHOW_CHOOSER" not in alice_socket.messages()

    lobby.claim_saved_player(waiting, 1)

    assert lobby.saved_player_claims_complete()
    assert [player.name for player in lobby.claimed_saved_players()] == [
        "Alice",
        SIGNATURE_NAME,
    ]


def test_claiming_a_taken_profile_sends_player_taken(lobby: BuzzerController) -> None:
    """A second phone cannot take a profile another phone holds."""
    first = _connect(lobby)
    second = _connect(lobby)
    player = lobby.claim_saved_player(first, 0)
    second.sent.clear()

    assert lobby.claim_saved_player(second, 0) is None

    assert second.messages() == ["PLAYER_TAKEN", "SHOW_CHOOSER"]
    assert second.player is None
    assert player.waiter is first
    assert lobby.connected_players == [player]


def test_same_phone_claiming_again_keeps_its_player(lobby: BuzzerController) -> None:
    """A repeated claim from the holding phone is not treated as taken."""
    socket = _connect(lobby)
    player = lobby.claim_saved_player(socket, 0)

    assert lobby.claim_saved_player(socket, 0) is player

    assert "PLAYER_TAKEN" not in socket.messages()
    assert lobby.connected_players == [player]


def test_claiming_an_unknown_profile_shows_the_chooser(
    lobby: BuzzerController,
) -> None:
    """A slot that is not in the save sends the phone back to the chooser."""
    socket = _connect(lobby)

    assert lobby.claim_saved_player(socket, 7) is None

    assert socket.messages() == ["SHOW_CHOOSER"]
    assert lobby.connected_players == []


def test_claims_are_refused_outside_reclaim_mode(
    controller: BuzzerController,
) -> None:
    """Without a loaded save, there is nothing to claim."""
    socket = _connect(controller)

    assert controller.claim_saved_player(socket, 0) is None

    assert socket.sent == []


def test_claimed_token_logs_back_in_to_the_same_player(
    lobby: BuzzerController,
) -> None:
    """The token sent on claim finds the claimed player after a reconnect."""
    socket = _connect(lobby)
    player = lobby.claim_saved_player(socket, 1)

    assert lobby.player_with_saved_token(player.token.hex()) is player
    assert lobby.player_with_token(player.token.hex()) is player
    assert lobby.player_with_token(Player("Other", None, 0).token.hex()) is None


def test_released_token_no_longer_logs_in(lobby: BuzzerController) -> None:
    """Releasing a slot stops its old token working and frees it for others."""
    old_socket = _connect(lobby)
    player = lobby.claim_saved_player(old_socket, 1)
    token = player.token.hex()

    assert lobby.release_saved_player(player)

    assert lobby.player_with_token(token) is None
    assert "LOGOUT" in old_socket.messages()
    new_player = lobby.claim_saved_player(_connect(lobby), 1)
    assert new_player.name == SIGNATURE_NAME
    assert new_player.token.hex() != token


def test_regular_players_log_in_by_token(controller: BuzzerController) -> None:
    """Outside reclaim mode, tokens match players who joined by name."""
    player = Player("Alice", FakeSocket(), 0)
    controller.new_player(player)

    assert controller.player_with_token(player.token.hex()) is player
    assert controller.player_with_token("not-a-token") is None
