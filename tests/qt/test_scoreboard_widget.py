"""Tests for host scoreboard score-edit controls."""

from types import SimpleNamespace

import pytest

from jparty.domain.models import Player
from jparty.ui.widgets.scoreboard import HostPlayerWidget, HostScoreBoard

pytestmark = pytest.mark.qt


class StubScoreGame:
    """Minimal game stub for scoreboard interaction tests."""

    def __init__(self) -> None:
        """Initialize test game state."""
        self.players = [
            Player("Alice", SimpleNamespace(send=lambda *args, **kwargs: None), 0),
            Player("Bob", SimpleNamespace(send=lambda *args, **kwargs: None), 1),
        ]
        self.can_edit = False
        self.adjust_calls = []
        self.applied_corrections = []
        self.soliciting_player = False
        self.active_question = None
        self.last_limit = None

    def can_open_score_editor(self) -> bool:
        """Return whether the host edit button should be enabled."""
        return self.can_edit

    def get_recent_score_corrections(self, limit: int = 5) -> list[dict]:
        """Return recent clue edits limited to the requested count."""
        self.last_limit = limit
        entries = []
        for question_number in range(1, 7):
            entries.append(
                {
                    "question_number": question_number,
                    "category": f"Category {question_number}",
                    "value": 200,
                    "answer": f"Answer {question_number}",
                    "is_daily_double": False,
                    "player_states": {0: "no answer", 1: "no answer"},
                }
            )
        entries.sort(key=lambda entry: entry["question_number"], reverse=True)
        return entries[:limit]

    def apply_question_history_corrections(self, corrections: list[dict]) -> bool:
        """Record the last score-correction payload."""
        self.applied_corrections.append(corrections)
        return True

    def adjust_score(self, player: object) -> None:
        """Record manual-adjust attempts."""
        self.adjust_calls.append(player.player_number)

    def remove_player(self, player: object) -> None:
        """Ignore remove-player requests in widget tests."""
        return None

    def move_player_up(self, player: object) -> None:
        """Ignore move-up requests in widget tests."""
        return None

    def move_player_down(self, player: object) -> None:
        """Ignore move-down requests in widget tests."""
        return None


def test_host_scoreboard_edit_button_tracks_enabled_state(qtbot: object) -> None:
    """Test the host edit button mirrors the game-enabled state."""
    game = StubScoreGame()
    scoreboard = HostScoreBoard(game)
    qtbot.addWidget(scoreboard)
    assert scoreboard.edit_score_button.isEnabled() is False

    game.can_edit = True
    scoreboard.refresh_score_edit_button()

    assert scoreboard.edit_score_button.isEnabled() is True


def test_host_scoreboard_opens_score_dialog_with_five_recent_entries(
    qtbot: object, monkeypatch: object
) -> None:
    """Test the score dialog receives at most five recent clues."""
    game = StubScoreGame()
    game.can_edit = True
    captured = {}

    class FakeDialog:
        """Record dialog inputs without opening a real modal."""

        def __init__(
            self, entries: list[dict], players: list[object], parent: object
        ) -> None:
            """Capture constructor arguments."""
            captured["entries"] = entries
            captured["players"] = players

        def exec(self) -> int:
            """Close the modal without saving."""
            return 0

    monkeypatch.setattr("jparty.ui.widgets.scoreboard.ScoreCorrectionDialog", FakeDialog)
    scoreboard = HostScoreBoard(game)
    qtbot.addWidget(scoreboard)

    scoreboard.open_score_editor()

    assert game.last_limit == 5
    assert len(captured["entries"]) == 5
    assert [entry["question_number"] for entry in captured["entries"]] == [6, 5, 4, 3, 2]


def test_host_player_click_adjusts_score_only_when_no_question_active(
    qtbot: object,
) -> None:
    """Test podium clicks keep manual override limited to inactive clues."""
    game = StubScoreGame()
    widget = HostPlayerWidget(game, game.players[0])
    qtbot.addWidget(widget)

    widget.mousePressEvent(None)
    assert game.adjust_calls == [0]

    game.active_question = object()
    widget.mousePressEvent(None)
    assert game.adjust_calls == [0]
