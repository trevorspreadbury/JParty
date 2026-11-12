"""Test Final Jeopardy reveal and wager rules with the real controller (#62)."""

import pytest

from jparty.web import controller as controller_module
from jparty.web.controller import BuzzerController

pytestmark = pytest.mark.integration


class RecordingLectern:
    """Stand-in lectern socket that records the states it is sent."""

    def __init__(self) -> None:
        """Start with no messages."""
        self.sent = []

    def send(self, msg: str, text: str = "") -> None:
        """Record an outgoing message."""
        self.sent.append((msg, text))

    def final_answers(self) -> list[object]:
        """Return the ``finalanswer`` field of each state sent so far."""
        return [
            controller_module.tornado.escape.json_decode(text)["finalanswer"]
            for msg, text in self.sent
            if msg == "PLAYER_STATE"
        ]


@pytest.fixture
def real_controller(game_with_players: object, monkeypatch: object) -> object:
    """Attach a real controller, with no server loop, to the test game."""
    monkeypatch.setattr(
        controller_module.tornado.options, "parse_command_line", lambda: None
    )
    controller = BuzzerController(game_with_players)
    controller.connected_players = list(game_with_players.players)
    game_with_players.buzzer_controller = controller
    return controller


def test_final_answer_reaches_lectern_only_when_revealed(
    game_with_players: object, real_controller: BuzzerController
) -> None:
    """The lectern gets the Final answer on reveal, not when judging starts."""
    game = game_with_players
    alice = game.players[0]
    alice.finalanswer = "Who is Lincoln?"
    lectern = RecordingLectern()
    real_controller.lectern_connections[alice.player_number] = lectern
    assert real_controller.get_player_state_dict(alice)["finalanswer"] is None

    game.final_jeopardy_flow.next_player()
    game.answering_player = alice
    game.final_jeopardy_flow.show_answer()

    assert lectern.final_answers()[-1] == "Who is Lincoln?"
    assert all(answer is None for answer in lectern.final_answers()[:-1])


@pytest.mark.parametrize(
    ("score", "requested", "expected"),
    [(1000, -5000, 0), (1000, 5000, 1000), (1000, 600, 600), (-400, 200, 0)],
)
def test_game_clamps_final_wagers(
    game_with_players: object, score: int, requested: int, expected: int
) -> None:
    """The game clamps Final wagers to ``0..max(score, 0)``."""
    player = game_with_players.players[0]
    player.score = score

    game_with_players.wager(0, requested)

    assert player.wager == expected
