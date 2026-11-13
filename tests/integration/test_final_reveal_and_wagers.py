"""Test Final Jeopardy reveal and wager rules with the real controller (#62)."""

import pytest
from PyQt6.QtCore import Qt

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
def real_controller(game_with_players: object) -> object:
    """Attach a real controller, with no server loop, to the test game."""
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
    _start_final(game_with_players)

    game_with_players.wager(0, requested)

    assert player.wager == expected


def _key_active(game: object, ident: str) -> bool:
    """Return whether a host key event is currently active."""
    return game.keystroke_manager._events[ident].active


def _start_final(game: object) -> None:
    """Move the test game into Final wagering."""
    game.current_round = game.data.rounds[2]
    game.active_question = game.current_round.question
    game.start_final()


def test_open_final_waits_for_every_wager(game_with_players: object) -> None:
    """Space opens Final only after the last wager arrives."""
    game = game_with_players
    _start_final(game)

    for i_player in range(len(game.players) - 1):
        game.wager(i_player, 0)
        assert not _key_active(game, "OPEN_FINAL")
        assert _key_active(game, "FORCE_OPEN_FINAL")

    game.wager(len(game.players) - 1, 0)

    assert _key_active(game, "OPEN_FINAL")
    assert not _key_active(game, "FORCE_OPEN_FINAL")


def test_host_can_open_final_with_missing_wagers_as_zero(
    game_with_players: object, real_controller: BuzzerController
) -> None:
    """Enter opens Final at once; missing wagers count as 0 and late ones drop."""
    game = game_with_players
    for player in game.players:
        player.score = 1000
    _start_final(game)
    real_controller.wager(game.players[0], 600)

    game.keystroke_manager.call(Qt.Key.Key_Return)

    assert [p.wager for p in game.players] == [600, 0, 0]
    assert game.dc.question_widget.show_question_calls == 1
    assert _key_active(game, "FINAL_OPEN_RESPONSES")
    assert not _key_active(game, "OPEN_FINAL")
    assert not _key_active(game, "FORCE_OPEN_FINAL")
    real_controller.wager(game.players[1], 900)
    assert game.players[1].wager == 0


def test_wager_landing_after_enter_is_ignored(
    game_with_players: object, real_controller: BuzzerController
) -> None:
    """A wager already sent when the host presses Enter doesn't replace the 0.

    The server can accept the wager just before Enter, but its signal reaches
    the game just after, when the clue (and no hint label) is on screen.
    """
    game = game_with_players
    for player in game.players:
        player.score = 1000
    _start_final(game)

    game.keystroke_manager.call(Qt.Key.Key_Return)
    # The real question widget deletes its hint label when the clue shows.
    game.host_display.question_widget.hint_label = None
    game.wager(1, 700)

    assert [p.wager for p in game.players] == [0, 0, 0]
    assert _key_active(game, "FINAL_OPEN_RESPONSES")
    assert not _key_active(game, "OPEN_FINAL")
