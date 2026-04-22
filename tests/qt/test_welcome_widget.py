"""Test welcome widget module."""

from types import SimpleNamespace
from typing import NoReturn

import pytest
from jparty.domain.models import Board, FinalBoard, GameData, Question
from jparty.ui.widgets.welcome import Welcome
from PyQt6.QtWidgets import QFileDialog, QMessageBox

pytestmark = pytest.mark.qt


class StubGame:
    """Test helper for stubgame."""

    def __init__(self) -> None:
        """Test init."""
        categories = [f"Cat {index}" for index in range(6)]
        questions = [
            Question((col, row), f"Q {col}-{row}", f"A {col}-{row}", categories[col])
            for col in range(6)
            for row in range(5)
        ]
        self.data = GameData(
            [
                Board(categories, questions[:30], dj=False),
                Board(categories, questions[:30], dj=True),
                FinalBoard(
                    "Final Category",
                    Question((0, 0), "Final clue", "Final response", "Final Category"),
                ),
            ],
            "January 1, 2026",
            "Fixture game",
        )
        self.resume_expected = None
        self.buzzer_controller = SimpleNamespace(connected_players=[])
        self.start_game_calls = 0
        self.clear_resume_state_calls = 0
        self._selected_round_indices = None

    def start_game(self) -> None:
        """Test start game."""
        self.start_game_calls += 1

    def clear_resume_state(self) -> None:
        """Test clear resume state."""
        self.resume_expected = None
        self.clear_resume_state_calls += 1

    def prepare_resume_from_dir(self, selected_dir: object) -> object:
        """Test prepare resume from dir."""
        self.resume_expected = 2
        self.data = GameData(
            [self.data.rounds[0], self.data.rounds[2]],
            self.data.date,
            self.data.comments,
        )
        return {
            "game_id": "4453",
            "general_state": {
                "players": [{"name": "Alice"}, {"name": "Bob"}],
                "selected_round_indices": [0, 2],
            },
        }

    def startable(self) -> object:
        """Test startable."""
        if self.resume_expected is None:
            return False
        return len(self.buzzer_controller.connected_players) == self.resume_expected

    def set_selected_round_indices(self, indices: object) -> None:
        """Test set selected round indices."""
        self._selected_round_indices = list(indices) if indices is not None else None

    def selected_round_indices(self) -> object:
        """Test selected round indices."""
        if self._selected_round_indices is None:
            return []
        return self._selected_round_indices

    def expected_player_count(self) -> object:
        """Test expected player count."""
        return self.resume_expected

    def close(self) -> None:
        """Test close."""
        return None

    def valid_game(self) -> bool:
        """Test valid game."""
        return True


def test_load_saved_game_requires_matching_player_count(
    qtbot: object, monkeypatch: object
) -> None:
    """Test test load saved game requires matching player count."""
    game = StubGame()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "C:/saved"
    )
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.load_saved_game()
    assert widget.start_button.text() == "Resume!"
    assert widget.start_button.isEnabled() is False
    assert [checkbox.text() for checkbox in widget.round_checkboxes] == [
        "[x] Jeopardy!",
        "[x] Final Jeopardy!",
    ]
    assert all(checkbox.isChecked() for checkbox in widget.round_checkboxes)
    assert all(not checkbox.isEnabled() for checkbox in widget.round_checkboxes)
    assert "Connect exactly 2 players" in widget.summary_label.text()
    game.buzzer_controller.connected_players = [object(), object()]
    widget.check_start()
    assert widget.start_button.isEnabled() is True


def test_load_saved_game_invalid_folder_shows_warning(
    qtbot: object, monkeypatch: object
) -> None:
    """Test test load saved game invalid folder shows warning."""
    game = StubGame()
    warnings = []
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "C:/bad"
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    def raise_error(selected_dir: object) -> NoReturn:
        """Test raise error."""
        raise FileNotFoundError("Saved game folder must contain general.json")

    game.prepare_resume_from_dir = raise_error
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.load_saved_game()
    assert warnings
    assert widget.start_button.text() == "Start!"
    assert widget.start_button.isEnabled() is False


def test_welcome_round_checkboxes_default_to_all_selected(qtbot: object) -> None:
    """Test welcome round checkboxes default to all selected."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.set_summary("January 1, 2026\nFixture game")
    assert [checkbox.text() for checkbox in widget.round_checkboxes] == [
        "[x] Jeopardy!",
        "[x] Double Jeopardy!",
        "[x] Final Jeopardy!",
    ]
    assert all(checkbox.isChecked() for checkbox in widget.round_checkboxes)
    assert game.selected_round_indices() == [0, 1, 2]


def test_welcome_round_checkboxes_update_selected_rounds(qtbot: object) -> None:
    """Test welcome round checkboxes update selected rounds."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.set_summary("January 1, 2026\nFixture game")
    widget.round_checkboxes[1].setChecked(False)
    assert widget.round_checkboxes[1].text() == "[ ] Double Jeopardy!"
    assert game.selected_round_indices() == [0, 2]
    widget.round_checkboxes[1].setChecked(True)
    assert widget.round_checkboxes[1].text() == "[x] Double Jeopardy!"
    assert game.selected_round_indices() == [0, 1, 2]
