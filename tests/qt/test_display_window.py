"""Tests for host display window layout behavior."""

from types import SimpleNamespace

import pytest
from jparty.ui.windows.display import DisplayWindow, HostDisplayWindow
from PyQt6.QtCore import QRect, Qt

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


def _board_slot_widget(window: object) -> object:
    """Return the widget currently shown between the board borders."""
    return window.board_layout.itemAt(1).widget()


class _InertThread:
    """Thread stand-in that never runs its target.

    Real windows start background threads for hint flashing, scoreboard
    lights, and welcome-screen game loading. Those threads touch Qt widgets
    (and the network) after a test tears the windows down, which crashes the
    test process, so these tests keep them from running.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Accept and ignore ``threading.Thread`` arguments."""

    def start(self) -> None:
        """Do nothing instead of starting a thread."""


def _game_with_real_windows(qtbot: object, game: object, monkeypatch: object) -> tuple:
    """Attach real audience and host windows to a test game."""
    from jparty.services import archive_client
    from jparty.ui import welcome_loader
    from jparty.ui.widgets import borders, common, scoreboard

    for module in (borders, common, scoreboard, welcome_loader):
        monkeypatch.setattr(module, "Thread", _InertThread)
    monkeypatch.setattr(archive_client, "save_game_html", lambda game_id: None)
    monkeypatch.setenv("JPARTY_GAME_ID", "4453")
    game.buzzer_controller.host = lambda: "localhost"
    game.buzzer_controller.restart = lambda: None
    game.buzzer_controller.lectern_connections = {}
    board_window = StubDisplayWindow(game)
    host_window = StubHostDisplayWindow(game)
    qtbot.addWidget(board_window)
    qtbot.addWidget(host_window)
    game.setDisplays(host_window, board_window)
    game.dc.scoreboard.refresh_players()
    game.players[0].score = 1000
    return board_window, host_window


def _assert_back_in_lobby(*windows: object) -> None:
    """Assert Close Game returned each window to the empty board."""
    for window in windows:
        assert _board_slot_widget(window) is window.board_widget
        assert window.final_display is None
        assert window.final_window is None
        assert window.graph_display is None
        assert window.question_widget is None


def test_game_without_final_jeopardy_ends_shows_summary_and_closes(
    qtbot: object, game_with_players: object, monkeypatch: object
) -> None:
    """Test a game with no Final round finishes through real windows (issue #52)."""
    game = game_with_players
    board_window, host_window = _game_with_real_windows(qtbot, game, monkeypatch)

    game.set_selected_round_indices([0])
    game.start_game()
    # Play the last clue and return to the board, as the host would.
    last_clue = game.current_round.get_question(0, 0)
    game.dc.load_question(last_clue)
    game.dc.hide_question()
    assert board_window.question_widget is None
    assert host_window.question_widget is None

    # Space after the last clue: no later round, so the game ends.
    game.keystroke_manager.activate("NEXT_ROUND")
    game.keystroke_manager.call(Qt.Key.Key_Space)
    for window in (board_window, host_window):
        assert window.final_window is not None
        assert window.final_window.guess_label.text() == "We have a winner!"
    assert game.keystroke_manager._events["GENERATE_GRAPHS"].active

    # Space again: the audience screen swaps the board for the summary.
    game.keystroke_manager.call(Qt.Key.Key_Space)
    assert _board_slot_widget(board_window) is board_window.graph_display
    assert not board_window.final_display.isVisible()
    assert game.keystroke_manager._events["CLOSE_GAME"].active

    # Space once more: Close Game returns both windows to the lobby.
    game.keystroke_manager.call(Qt.Key.Key_Space)
    _assert_back_in_lobby(board_window, host_window)


def test_game_with_final_jeopardy_still_shows_summary_and_closes(
    qtbot: object, game_with_players: object, monkeypatch: object
) -> None:
    """Test the summary still replaces the Final clue after a Final round."""
    game = game_with_players
    board_window, host_window = _game_with_real_windows(qtbot, game, monkeypatch)
    game.start_game()
    game.current_round = game.data.rounds[-1]
    game.active_question = game.current_round.question
    game.dc.load_final(game.active_question)
    final_clue_widget = board_window.question_widget
    assert _board_slot_widget(board_window) is final_clue_widget
    game.dc.load_final_judgement()
    game.end_game()

    game.keystroke_manager.call(Qt.Key.Key_Space)
    assert _board_slot_widget(board_window) is board_window.graph_display
    assert not final_clue_widget.isVisible()

    game.keystroke_manager.call(Qt.Key.Key_Space)
    _assert_back_in_lobby(board_window, host_window)


def test_hide_question_without_a_question_is_a_no_op(qtbot: object) -> None:
    """Test returning to the board twice does not raise."""
    board_window = StubDisplayWindow(_stub_game())
    qtbot.addWidget(board_window)
    assert board_window.question_widget is None
    board_window.hide_question()
    assert _board_slot_widget(board_window) is board_window.board_widget
