"""Display windows for the host and audience game screens.

This module assembles the reusable UI widgets into full-screen windows for the
host and the audience display. It coordinates the transitions between lobby,
board, clue, Final Jeopardy, and score-graph screens.
"""

from PyQt6.QtCore import QMargins
from PyQt6.QtGui import QColor, QGuiApplication, QPalette
from PyQt6.QtWidgets import QHBoxLayout, QMainWindow, QVBoxLayout, QWidget

from jparty.ui.widgets.board import BoardWidget
from jparty.ui.widgets.borders import Borders, HostBorders
from jparty.ui.widgets.final import FinalDisplay, GraphDisplay
from jparty.ui.widgets.question import (
    DailyDoubleWidget,
    FinalJeopardyWidget,
    HostDailyDoubleWidget,
    HostFinalJeopardyWidget,
    HostImageQuestionWidget,
    HostQuestionWidget,
    QuestionWidget,
)
from jparty.ui.widgets.scoreboard import HostScoreBoard, ScoreBoard
from jparty.ui.widgets.welcome import QRWidget, QuestionMediaPreview, Welcome


class DisplayWindow(QMainWindow):
    """Base full-screen game window shared by host and audience displays."""

    def __init__(self, game: object) -> None:
        """Initialize a display window and its major child widgets.

        Args:
            game: Active game instance that drives display state.

        Returns:
            ``None``.
        """
        super().__init__()
        self.game = game
        self.setWindowTitle("Host" if self.host() else "Board")
        colorpal = QPalette()
        colorpal.setColor(QPalette.ColorRole.Window, QColor("#000000"))
        self.setPalette(colorpal)
        self.welcome_widget = None
        self.question_widget = None
        self.board_widget = BoardWidget(game, self)
        self.scoreboard = self.create_score_board()
        self.borders = self.create_border_widget()
        self.board_layout = QHBoxLayout()
        self.board_layout.addWidget(self.borders.left, 1)
        self.board_layout.addWidget(self.board_widget, 20)
        self.board_layout.addWidget(self.borders.right, 1)
        self.newWidget = QWidget(self)
        self.main_layout = QVBoxLayout()
        self.main_layout.addLayout(self.board_layout, 7)
        self.main_layout.addWidget(self.scoreboard, 2)
        self.newWidget.setLayout(self.main_layout)
        self.welcome_widget = self.create_start_menu()
        self.final_window = None
        self.final_display = None
        self.graph_display = None
        self.setCentralWidget(self.newWidget)
        monitor_index = self.monitor()
        screens = QGuiApplication.screens()
        if monitor_index >= len(screens):
            monitor_index = len(screens) - 1
        monitor = screens[monitor_index].geometry()
        self.setGeometry(monitor)
        self.showFullScreen()
        self.show()

    def host(self) -> bool:
        """Return whether this window is the host-facing display.

        Returns:
            ``False`` for the base audience display implementation.
        """
        return False

    def monitor(self) -> int:
        """Return the preferred monitor index for this window.

        Returns:
            Monitor index used when placing the window.
        """
        return 1

    def create_border_widget(self) -> object:
        """Create the border widget set for this display.

        Returns:
            A ``Borders`` instance.
        """
        return Borders(self)

    def create_start_menu(self) -> object:
        """Create the startup widget shown before a game begins.

        Returns:
            A startup widget appropriate for this display.
        """
        return QRWidget(self.game.buzzer_controller.host(), self)

    def create_score_board(self) -> object:
        """Create the scoreboard widget for this display.

        Returns:
            A ``ScoreBoard`` instance.
        """
        return ScoreBoard(self.game, self)

    def create_question_widget(self, q: object) -> object:
        """Create the clue widget for the given question.

        Args:
            q: Question object to display.

        Returns:
            A question widget appropriate for the clue type.
        """
        if q.dd:
            return DailyDoubleWidget(q, self)
        else:
            return QuestionWidget(q, self)

    def create_final_widget(self, q: object) -> object:
        """Create the Final Jeopardy widget for the given question.

        Args:
            q: Final Jeopardy question object.

        Returns:
            A final-question widget appropriate for this display.
        """
        return FinalJeopardyWidget(q, self)

    def resizeEvent(self, event: object) -> None:
        """Resize overlay widgets when the window geometry changes.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        fullrect = self.rect()
        margins = (
            QMargins(
                fullrect.width(), fullrect.height(), fullrect.width(), fullrect.height()
            )
            * self.welcome_margin_scale()
        )
        welcome_rect = (fullrect - margins).translated(
            0, int(fullrect.height() * self.welcome_vertical_offset_scale())
        )
        if self.welcome_widget is not None:
            self.welcome_widget.setGeometry(welcome_rect)
        if getattr(self, "preview_widget", None) is not None:
            self.preview_widget.setGeometry(welcome_rect)
        if self.final_display is not None:
            self.final_display.setGeometry(fullrect)

    def welcome_margin_scale(self) -> float:
        """Return the inset scale used when sizing the welcome widget.

        Returns:
            Fractional inset applied on each side of the welcome widget.
        """
        return 0.3

    def welcome_vertical_offset_scale(self) -> float:
        """Return the vertical shift applied to the welcome overlay geometry.

        Returns:
            Fractional screen-height offset for the welcome widget.
        """
        return 0.0

    def show_welcome_widgets(self) -> None:
        """Show and reset the startup widget.

        Returns:
            ``None``.
        """
        self.welcome_widget.setVisible(True)
        self.welcome_widget.setDisabled(False)
        self.welcome_widget.restart()

    def hide_welcome_widgets(self) -> None:
        """Hide and disable the startup widget.

        Returns:
            ``None``.
        """
        self.welcome_widget.setVisible(False)
        self.welcome_widget.setDisabled(True)

    def hide_question(self) -> None:
        """Swap the current clue widget out and restore the board view.

        Returns:
            ``None``.
        """
        self.board_widget.setVisible(True)
        self.board_layout.replaceWidget(self.question_widget, self.board_widget)
        self.question_widget.deleteLater()
        self.question_widget = None

    def load_question(self, q: object) -> None:
        """Replace the board with the selected clue widget.

        Args:
            q: Question object to display.

        Returns:
            ``None``.
        """
        self.question_widget = self.create_question_widget(q)
        self.board_widget.setVisible(False)
        self.board_layout.replaceWidget(self.board_widget, self.question_widget)

    def load_final(self, q: object) -> None:
        """Replace the board with the Final Jeopardy widget.

        Args:
            q: Final Jeopardy question object.

        Returns:
            ``None``.
        """
        self.question_widget = self.create_final_widget(q)
        self.board_widget.setVisible(False)
        self.board_layout.replaceWidget(self.board_widget, self.question_widget)

    def load_final_judgement(self) -> None:
        """Show the Final Jeopardy answer-adjudication view.

        Returns:
            ``None``.
        """
        self.final_display = FinalDisplay(self.game, self)
        self.final_window = self.final_display.answer_widget

    def load_final_graphs(self) -> None:
        """Show the saved end-of-game score graph view.

        Returns:
            ``None``.
        """
        self.graph_display = GraphDisplay(self)
        self.question_widget.setVisible(False)
        self.final_display.setVisible(False)
        self.board_layout.replaceWidget(self.question_widget, self.graph_display)

    def closeEvent(self, event: object) -> None:
        """Close the game when the window is closed.

        Args:
            event: Qt close event object.

        Returns:
            ``None``.
        """
        super().closeEvent(event)
        self.game.close()

    def player_widget(self, player: object) -> object:
        """Return the scoreboard widget associated with a player.

        Args:
            player: Player object to locate.

        Returns:
            Matching player widget, if found.
        """
        for pw in self.scoreboard.player_widgets:
            if pw.player is player:
                return pw

    def remove_card(self, q: object) -> None:
        """Clear a clue card on the board after it has been selected.

        Args:
            q: Question object whose board card should be cleared.

        Returns:
            ``None``.
        """
        for label in self.board_widget.question_labels:
            if label.question is q:
                label.question = None

    def restart(self) -> None:
        """Reset display widgets to the lobby state after a game ends.

        Returns:
            ``None``.
        """
        if self.graph_display is not None:
            layout_item = self.board_layout.itemAt(1)
            if layout_item is not None and layout_item.widget() == self.graph_display:
                self.graph_display.setVisible(False)
                self.board_layout.replaceWidget(self.graph_display, self.board_widget)
                self.board_widget.setVisible(True)
        self.hide_question()
        if self.final_display is not None:
            self.final_display.close()
        if self.graph_display is not None:
            self.graph_display.close()
        self.final_display = None
        self.graph_display = None
        self.board_widget.clear()
        self.show_welcome_widgets()
        self.scoreboard.refresh_players()


class HostDisplayWindow(DisplayWindow):
    """Host-specific display window with controls and review screens."""

    def __init__(self, game: object) -> None:
        """Initialize the host display window.

        Args:
            game: Active game instance that drives display state.

        Returns:
            ``None``.
        """
        super().__init__(game)
        self.on_image_question = False
        self.preview_widget = None

    def host(self) -> bool:
        """Return whether this is the host display.

        Returns:
            ``True``.
        """
        return True

    def show_welcome_widgets(self) -> None:
        """Show the welcome screen and clear any preview overlay."""
        self.hide_question_media_preview()
        super().show_welcome_widgets()

    def monitor(self) -> int:
        """Return the preferred host monitor index.

        Returns:
            Monitor index ``0`` for the host display.
        """
        return 0

    def welcome_margin_scale(self) -> float:
        """Return a larger welcome widget footprint for the host display.

        Returns:
            Fractional inset applied on each side of the host welcome widget.
        """
        return 0.16

    def welcome_vertical_offset_scale(self) -> float:
        """Shift the host welcome widget upward to clear the lecterns.

        Returns:
            Negative fractional screen-height offset.
        """
        return -0.08

    def create_start_menu(self) -> object:
        """Create the host welcome screen.

        Returns:
            A ``Welcome`` widget.
        """
        return Welcome(self.game, self)

    def create_score_board(self) -> object:
        """Create the host scoreboard.

        Returns:
            A ``HostScoreBoard`` instance.
        """
        return HostScoreBoard(self.game, self)

    def create_border_widget(self) -> object:
        """Create the host border widget set.

        Returns:
            A ``HostBorders`` instance.
        """
        return HostBorders(self)

    def create_question_widget(self, q: object) -> object:
        """Create the host clue widget for the given question.

        Args:
            q: Question object to display.

        Returns:
            A host-side clue widget appropriate for the clue type.
        """
        if q.dd:
            return HostDailyDoubleWidget(q, self)
        else:
            return HostQuestionWidget(q, self)

    def create_image_question_widget(self, game: object) -> object:
        """Create the host image-review widget for an image clue.

        Args:
            game: Active game instance whose clue is being reviewed.

        Returns:
            A ``HostImageQuestionWidget`` instance.
        """
        return HostImageQuestionWidget(game, self)

    def create_final_widget(self, q: object) -> object:
        """Create the host Final Jeopardy widget.

        Args:
            q: Final Jeopardy question object.

        Returns:
            A ``HostFinalJeopardyWidget`` instance.
        """
        return HostFinalJeopardyWidget(q, self)

    def keyPressEvent(self, event: object) -> None:
        """Forward key presses to the game's keystroke manager.

        Args:
            event: Qt key event object.

        Returns:
            ``None``.
        """
        self.game.keystroke_manager.call(event.key())

    def hide_welcome_widgets(self) -> None:
        """Hide the welcome screen and host-only lobby controls.

        Returns:
            ``None``.
        """
        super().hide_welcome_widgets()
        self.hide_question_media_preview()
        self.scoreboard.hide_close_buttons()

    def load_question_media_preview(
        self, preview_questions: list[tuple[int, object]]
    ) -> None:
        """Show the pre-start question-media preview widget."""
        self.hide_welcome_widgets()
        self.hide_question_media_preview()
        self.preview_widget = QuestionMediaPreview(
            self.game,
            preview_questions,
            on_back=self.show_welcome_from_preview,
            on_start=self.game.start_game,
            parent=self,
        )
        self.preview_widget.setGeometry(self.welcome_widget.geometry())
        self.preview_widget.setVisible(True)
        self.preview_widget.raise_()

    def hide_question_media_preview(self) -> None:
        """Hide and dispose of the question-media preview widget."""
        if self.preview_widget is None:
            return
        self.preview_widget.setVisible(False)
        self.preview_widget.deleteLater()
        self.preview_widget = None

    def show_welcome_from_preview(self) -> None:
        """Return from the preview widget to the welcome screen."""
        self.hide_question_media_preview()
        self.welcome_widget.setVisible(True)
        self.welcome_widget.setDisabled(False)
        self.welcome_widget.raise_()

    def load_image_review_screen(self, q: object) -> None:
        """Replace the board with the host image review screen.

        Args:
            q: Question object whose image is being reviewed.

        Returns:
            ``None``.
        """
        self.on_image_question = True
        self.image_question_widget = self.create_image_question_widget(self.game)
        self.board_widget.setVisible(False)
        self.board_layout.replaceWidget(self.board_widget, self.image_question_widget)

    def load_question(self, q: object) -> None:
        """Load a host clue widget, replacing either the board or image review.

        Args:
            q: Question object to display.

        Returns:
            ``None``.
        """
        self.question_widget = self.create_question_widget(q)
        self.board_widget.setVisible(False)
        if self.on_image_question:
            self.on_image_question = False
            self.board_layout.replaceWidget(
                self.image_question_widget, self.question_widget
            )
            self.image_question_widget.deleteLater()
            self.image_question_widget = None
        else:
            self.board_layout.replaceWidget(self.board_widget, self.question_widget)
