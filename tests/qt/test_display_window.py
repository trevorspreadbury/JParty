"""Tests for host display window layout behavior."""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEvent, QRect, Qt
from PyQt6.QtGui import QKeyEvent

from jparty.domain.input import KeystrokeManager
from jparty.domain.models import Question
from jparty.ui.windows.display import DisplayWindow, HostDisplayWindow

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

    Real windows start a background thread for welcome-screen game loading.
    It touches Qt widgets (and the network) after a test tears the windows
    down, which crashes the test process, so these tests keep it from
    running.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Accept and ignore ``threading.Thread`` arguments."""

    def start(self) -> None:
        """Do nothing instead of starting a thread."""


def _game_with_real_windows(qtbot: object, game: object, monkeypatch: object) -> tuple:
    """Attach real audience and host windows to a test game."""
    from jparty.services import archive_client
    from jparty.ui import welcome_loader

    monkeypatch.setattr(welcome_loader, "Thread", _InertThread)
    monkeypatch.setattr(archive_client, "save_game_html", lambda game_id: None)
    game.set_session_game_id("4453")
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


def test_second_final_replaces_first_final_on_both_screens(
    qtbot: object, game_with_players: object, monkeypatch: object
) -> None:
    """After one Final is judged, the next Final's clue takes the board slot."""
    from jparty.domain import FinalBoard, Question

    game = game_with_players
    board_window, host_window = _game_with_real_windows(qtbot, game, monkeypatch)
    second_final = FinalBoard(
        "Second Final",
        Question((0, 0), "Second clue", "Second response", "Second Final"),
    )
    game.data.rounds.append(second_final)
    game.start_game()
    game.current_round = game.data.rounds[2]
    game.active_question = game.current_round.question
    game.dc.load_final(game.active_question)
    game.dc.load_final_judgement()
    first_final_displays = [board_window.final_display, host_window.final_display]
    game._judgement_round = len(game.players)
    game.final_next_player()

    assert game.current_round is second_final
    for window, first_display in zip(
        (board_window, host_window), first_final_displays, strict=True
    ):
        assert not first_display.isVisible()
        assert window.final_display is None
        assert window.final_window is None
        assert _board_slot_widget(window) is window.question_widget
    assert not game.keystroke_manager._events["GENERATE_GRAPHS"].active


def test_hide_question_without_a_question_is_a_no_op(qtbot: object) -> None:
    """Test returning to the board twice does not raise."""
    board_window = StubDisplayWindow(_stub_game())
    qtbot.addWidget(board_window)
    assert board_window.question_widget is None
    board_window.hide_question()
    assert _board_slot_widget(board_window) is board_window.board_widget


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
    qtbot: object, offline_image_lookup: None
) -> None:
    """Test an offline image lookup still lets the host play on (issue #49)."""
    game = _stub_game()
    board_window, host_window = _windows(qtbot, game)
    image_question = _image_question()
    game.active_question = image_question

    host_window.load_image_review_screen(image_question)
    assert host_window.on_image_question
    review_widget = host_window.image_question_widget
    assert review_widget is not None
    qtbot.waitUntil(
        lambda: review_widget.image_label.text() == "Failed to load image.",
        timeout=10000,
    )

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


@pytest.mark.parametrize(("auto_repeat", "expected_calls"), [(False, 1), (True, 0)])
def test_host_key_auto_repeat_is_ignored(
    qtbot: object, auto_repeat: bool, expected_calls: int
) -> None:
    """Holding a key fires its host action once, not again for each repeat."""
    calls = []
    game = _stub_game()
    game.keystroke_manager = KeystrokeManager()
    game.keystroke_manager.addEvent(
        "STEP", Qt.Key.Key_Space, lambda: calls.append(1), active=True, persistent=True
    )
    host_window = StubHostDisplayWindow(game)
    qtbot.addWidget(host_window)
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Space,
        Qt.KeyboardModifier.NoModifier,
        " ",
        auto_repeat,
    )

    host_window.keyPressEvent(event)

    assert len(calls) == expected_calls


def test_tiebreaker_clue_replaces_final_and_winner_returns(
    qtbot: object, game_with_players: object, monkeypatch: object
) -> None:
    """A tiebreaker plays in the board slot on real windows (#44).

    The category shows first, Space reveals the clue, a correct answer
    brings back the winner card, and the summary and Close Game still work.
    """
    game = game_with_players
    board_window, host_window = _game_with_real_windows(qtbot, game, monkeypatch)
    game.start_game()
    game.players[0].score = 1000
    game.players[1].score = 1000
    clue = Question((0, 4), "Tiebreaker clue", "Tiebreaker answer", "Rivers", 2000)
    monkeypatch.setattr(game, "prompt_tiebreaker_game_id", lambda: "")
    monkeypatch.setattr(
        game, "load_tiebreaker_clues", lambda gid, is_cancelled: ("9", [clue])
    )
    monkeypatch.setattr(game, "run_in_background", lambda work: work())
    game.current_round = game.data.rounds[-1]
    game.active_question = game.current_round.question
    game.dc.load_final(game.active_question)
    final_clue_widget = board_window.question_widget
    game.dc.load_final_judgement()
    game.end_game()

    game.keystroke_manager.call(Qt.Key.Key_Space)
    for window in (board_window, host_window):
        tiebreaker_widget = _board_slot_widget(window)
        assert tiebreaker_widget is window.question_widget
        assert tiebreaker_widget.category_label.text() == "Rivers"
        assert window.final_display.isHidden()
    assert _board_slot_widget(board_window) is not final_clue_widget

    game.keystroke_manager.call(Qt.Key.Key_Space)
    assert board_window.question_widget.category_label is None
    assert not board_window.question_widget.question_label.isHidden()
    game.keystroke_manager.call(Qt.Key.Key_Space)
    game.buzz(1)
    game.keystroke_manager.call(Qt.Key.Key_Left)
    assert game.players[1].score == 1000
    assert game.tiebreaker_winner is game.players[1]
    assert board_window.final_window.guess_label.text() == "We have a winner!"

    game.keystroke_manager.call(Qt.Key.Key_Space)
    assert _board_slot_widget(board_window) is board_window.graph_display
    game.keystroke_manager.call(Qt.Key.Key_Space)
    _assert_back_in_lobby(board_window, host_window)


def test_contestant_intro_back_and_start(qtbot: object) -> None:
    """The intro replaces the welcome screen; Back returns, Start Game starts."""
    from jparty.ui.widgets.welcome import ContestantIntro

    host_window = StubHostDisplayWindow(_stub_game())
    qtbot.addWidget(host_window)
    lines = ["Let's meet today's contestants:", "A teacher from Chicago, Jane Smith"]
    starts = []

    def on_start() -> None:
        """Record the start, and whether the intro was already closed."""
        starts.append(host_window.preview_widget)

    host_window.load_contestant_intro(lines, on_start)
    intro = host_window.preview_widget
    assert isinstance(intro, ContestantIntro)
    assert intro.title_label.text() == lines[0]
    assert [label.text() for label in intro.line_labels] == lines[1:]
    assert host_window.welcome_widget.isHidden()

    intro.back_button.click()
    assert host_window.preview_widget is None
    assert not host_window.welcome_widget.isHidden()
    assert host_window.welcome_widget.isEnabled()
    assert starts == []

    host_window.load_contestant_intro(lines, on_start)
    host_window.preview_widget.start_button.click()
    assert starts == [None]
    assert host_window.preview_widget is None


def test_tournament_tiebreaker_session_through_real_windows(
    qtbot: object, game_with_players: object, monkeypatch: object, temp_dir: object
) -> None:
    """A tiebreaker session shows the tie, plays a clue, and saves the win."""
    from jparty.domain import game_engine
    from jparty.domain.tournament_advancement import (
        TIE_WILDCARD,
        TiebreakerSession,
        TieForSpot,
    )
    from jparty.domain.tournament_store import load_tiebreaks

    game = game_with_players
    board_window, host_window = _game_with_real_windows(qtbot, game, monkeypatch)
    monkeypatch.setattr(game_engine, "TOURNAMENTS_DIR", temp_dir / "tournaments")
    clue = Question(
        index=(0, 4), text="Clue", answer="Answer", category="Category", value=2000
    )
    monkeypatch.setattr(
        game, "load_tiebreaker_clues", lambda game_id, is_cancelled: (game_id, [clue])
    )
    monkeypatch.setattr(game, "run_in_background", lambda work: work())
    monkeypatch.setattr(game, "prompt_tiebreaker_game_id", lambda: "")
    seats = tuple(
        (f"id{index}", player.name) for index, player in enumerate(game.players)
    )
    tie = TieForSpot("Quarterfinals", TIE_WILDCARD, tuple(p for p, _ in seats), 400, 1)
    game.start_tiebreaker_session(TiebreakerSession("Fun", tie, seats))

    assert not host_window.welcome_widget.isVisible()
    for window in (board_window, host_window):
        assert window.final_window.guess_label.text() == "We have a tie!"

    game.keystroke_manager.call(Qt.Key.Key_Space)  # Load the clue.
    game.keystroke_manager.call(Qt.Key.Key_Space)  # Show it.
    game.keystroke_manager.call(Qt.Key.Key_Space)  # Open buzzing.
    game.buzz(0)
    game.correct_answer()
    for window in (board_window, host_window):
        assert window.final_window.guess_label.text() == "We have a winner!"
    (tiebreak,) = load_tiebreaks(temp_dir / "tournaments" / "Fun")
    assert tiebreak.winner == "id0"

    game.keystroke_manager.call(Qt.Key.Key_Space)  # Back to the lobby.
    _assert_back_in_lobby(board_window, host_window)


def test_host_code_replaces_the_board_until_hidden(qtbot: object) -> None:
    """The /host QR code sits where the board was, then gives it back."""
    from jparty.ui.widgets.welcome import QRWidget

    host_window = StubHostDisplayWindow(_stub_game())
    qtbot.addWidget(host_window)
    host_window.load_host_code("192.168.1.20:8080")
    code = host_window.host_code_widget
    assert isinstance(code, QRWidget)
    assert code.url == "http://192.168.1.20:8080/host"
    assert code.hint_label.text() == "Scan for the players' prompts:"
    assert host_window.board_layout.indexOf(code) == 1
    assert host_window.board_widget.isHidden()

    host_window.hide_host_code()
    assert host_window.host_code_widget is None
    assert host_window.board_layout.indexOf(host_window.board_widget) == 1
    assert not host_window.board_widget.isHidden()
    host_window.hide_host_code()  # Nothing to hide; no error.


def test_restart_puts_the_board_back_from_the_host_code(qtbot: object) -> None:
    """Closing a game while the code shows leaves the board ready next game."""
    host_window = StubHostDisplayWindow(_stub_game())
    qtbot.addWidget(host_window)
    host_window.load_host_code("192.168.1.20:8080")
    host_window.restart()
    assert host_window.host_code_widget is None
    assert host_window.board_layout.indexOf(host_window.board_widget) == 1
