"""Tests for host display window layout behavior."""

from types import SimpleNamespace

import pytest
import requests
from jparty.domain.models import Question
from jparty.services import image_lookup
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


def _image_question() -> Question:
    """Return an image clue with no local media file."""
    return Question(
        index=(0, 0),
        text="This arch is pictured",
        answer="What is the Gateway Arch?",
        category="Landmarks",
        value=200,
        image=True,
    )


def _text_question() -> Question:
    """Return a plain text clue."""
    return Question(
        index=(1, 0),
        text="This river flows past St. Louis",
        answer="What is the Mississippi?",
        category="Rivers",
        value=200,
    )


def _windows(qtbot: object, game: object) -> tuple:
    """Build audience and host windows for clue-loading tests."""
    board_window = StubDisplayWindow(game)
    host_window = StubHostDisplayWindow(game)
    qtbot.addWidget(board_window)
    qtbot.addWidget(host_window)
    return board_window, host_window


def _assert_showing_clue(window: object, question: object) -> None:
    """Assert the window has swapped its board for a widget showing the clue."""
    assert window.question_widget is not None
    assert window.question_widget.question is question
    assert window.board_layout.indexOf(window.question_widget) != -1
    assert window.board_layout.indexOf(window.board_widget) == -1


def test_offline_image_clue_then_text_clue_updates_both_screens(
    qtbot: object, monkeypatch: object
) -> None:
    """Test an offline image lookup still lets the host play on (issue #49)."""

    def offline(*args: object, **kwargs: object) -> None:
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(image_lookup.requests, "get", offline)
    game = _stub_game()
    board_window, host_window = _windows(qtbot, game)
    image_question = _image_question()
    game.active_question = image_question

    host_window.load_image_review_screen(image_question)
    assert host_window.on_image_question
    assert host_window.image_question_widget is not None
    assert host_window.image_question_widget.image_url == "No image found."

    # "No Image Necessary": the clue continues as a text clue on both screens.
    image_question.image = False
    for window in (board_window, host_window):
        window.load_question(image_question)
        _assert_showing_clue(window, image_question)
    assert not host_window.on_image_question
    assert host_window.image_question_widget is None
    for window in (board_window, host_window):
        window.hide_question()

    text_question = _text_question()
    for window in (board_window, host_window):
        window.load_question(text_question)
        _assert_showing_clue(window, text_question)


def test_failed_image_review_screen_leaves_board_usable(
    qtbot: object, monkeypatch: object
) -> None:
    """Test a review-widget failure does not leave the host in image mode."""
    game = _stub_game()
    board_window, host_window = _windows(qtbot, game)

    def broken_widget(game: object) -> None:
        raise RuntimeError("review widget failed")

    monkeypatch.setattr(host_window, "create_image_question_widget", broken_widget)
    with pytest.raises(RuntimeError):
        host_window.load_image_review_screen(_image_question())
    assert not host_window.on_image_question
    assert host_window.image_question_widget is None
    assert host_window.board_layout.indexOf(host_window.board_widget) != -1

    text_question = _text_question()
    for window in (board_window, host_window):
        window.load_question(text_question)
        _assert_showing_clue(window, text_question)
