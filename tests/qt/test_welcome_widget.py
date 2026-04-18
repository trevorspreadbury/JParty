from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from jparty.welcome_widget import Welcome


pytestmark = pytest.mark.qt


class StubGame:
    def __init__(self):
        self.data = SimpleNamespace(date="January 1, 2026", comments="Fixture game")
        self.resume_expected = None
        self.buzzer_controller = SimpleNamespace(connected_players=[])
        self.start_game_calls = 0
        self.clear_resume_state_calls = 0

    def start_game(self):
        self.start_game_calls += 1

    def clear_resume_state(self):
        self.resume_expected = None
        self.clear_resume_state_calls += 1

    def prepare_resume_from_dir(self, selected_dir):
        self.resume_expected = 2
        return {
            "game_id": "4453",
            "general_state": {"players": [{"name": "Alice"}, {"name": "Bob"}]},
        }

    def startable(self):
        if self.resume_expected is None:
            return False
        return len(self.buzzer_controller.connected_players) == self.resume_expected

    def expected_player_count(self):
        return self.resume_expected

    def close(self):
        return None

    def valid_game(self):
        return True


def test_load_saved_game_requires_matching_player_count(qtbot, monkeypatch):
    game = StubGame()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "C:/saved")

    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.load_saved_game()

    assert widget.start_button.text() == "Resume!"
    assert widget.start_button.isEnabled() is False
    assert "Connect exactly 2 players" in widget.summary_label.text()

    game.buzzer_controller.connected_players = [object(), object()]
    widget.check_start()

    assert widget.start_button.isEnabled() is True


def test_load_saved_game_invalid_folder_shows_warning(qtbot, monkeypatch):
    game = StubGame()
    warnings = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "C:/bad")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    def raise_error(selected_dir):
        raise FileNotFoundError("Saved game folder must contain general.json")

    game.prepare_resume_from_dir = raise_error

    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.load_saved_game()

    assert warnings
    assert widget.start_button.text() == "Start!"
    assert widget.start_button.isEnabled() is False
