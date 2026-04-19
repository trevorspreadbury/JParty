"""Test welcome widget module."""

from types import SimpleNamespace
from typing import NoReturn

import pytest
from jparty.ui.widgets.welcome import Welcome
from PyQt6.QtWidgets import QFileDialog, QMessageBox

pytestmark = pytest.mark.qt


class StubGame:
    """Test helper for stubgame."""

    def __init__(self) -> None:
        """Test init."""
        self.data = SimpleNamespace(date="January 1, 2026", comments="Fixture game")
        self.resume_expected = None
        self.buzzer_controller = SimpleNamespace(connected_players=[])
        self.start_game_calls = 0
        self.clear_resume_state_calls = 0

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
        return {
            "game_id": "4453",
            "general_state": {"players": [{"name": "Alice"}, {"name": "Bob"}]},
        }

    def startable(self) -> object:
        """Test startable."""
        if self.resume_expected is None:
            return False
        return len(self.buzzer_controller.connected_players) == self.resume_expected

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
