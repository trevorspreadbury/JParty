"""Tests for host display window layout behavior."""

from types import SimpleNamespace

import pytest
from jparty.ui.windows.display import DisplayWindow, HostDisplayWindow
from PyQt6.QtCore import QRect

pytestmark = pytest.mark.qt


class StubDisplayWindow(DisplayWindow):
    """Concrete non-host display for resize tests."""

    def __init__(self, game: object) -> None:
        """Initialize without showing fullscreen windows."""
        self._test_geometry = QRect(0, 0, 1200, 800)
        super().__init__(game)

    def showFullScreen(self) -> None:
        """Suppress fullscreen behavior in tests."""
        return None

    def show(self) -> None:
        """Suppress normal show behavior in tests."""
        return None

    def setGeometry(self, geometry: object) -> None:
        """Apply the provided test geometry."""
        if isinstance(geometry, QRect):
            self._test_geometry = geometry
            self.resize(geometry.size())
        else:
            super().setGeometry(geometry)


class StubHostDisplayWindow(HostDisplayWindow, StubDisplayWindow):
    """Concrete host display that reuses the fullscreen suppression."""


def _stub_game() -> object:
    """Return the minimal game object needed by display windows."""
    buzzer = SimpleNamespace(host=lambda: "localhost")
    return SimpleNamespace(
        buzzer_controller=buzzer,
        close=lambda: None,
        can_open_score_editor=lambda: False,
        players=[],
        start_game=lambda: None,
        clear_resume_state=lambda: None,
        prepare_resume_from_dir=lambda selected_dir: {},
        set_selected_round_indices=lambda indices: None,
        selected_round_indices=lambda: [],
        set_board_selection_configs=lambda configs: None,
        board_selection_configs=lambda: [],
        set_session_game_id=lambda game_id: None,
        set_reveal_answers_after_triple_stumper=lambda enabled: None,
        reveal_answers_after_triple_stumper_enabled=lambda: False,
        expected_player_count=lambda: None,
        resume_claim_status=lambda: (0, 0),
        startable=lambda: False,
        valid_game=lambda: False,
        data=None,
    )


def test_host_welcome_widget_is_shifted_upward_more_than_default(qtbot: object) -> None:
    """Test the host welcome overlay sits higher than the default display."""
    game = _stub_game()
    board_window = StubDisplayWindow(game)
    host_window = StubHostDisplayWindow(game)
    qtbot.addWidget(board_window)
    qtbot.addWidget(host_window)
    board_window.resize(1200, 800)
    host_window.resize(1200, 800)
    board_window.resizeEvent(None)
    host_window.resizeEvent(None)

    assert host_window.welcome_widget.geometry().center().y() < (
        board_window.welcome_widget.geometry().center().y()
    )
    assert host_window.welcome_widget.geometry().bottom() < 800
