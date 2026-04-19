"""Display module."""

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
from jparty.ui.widgets.welcome import QRWidget, Welcome


class DisplayWindow(QMainWindow):
    """Represent displaywindow."""

    def __init__(self, game: object) -> None:
        """Initialize the instance."""
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
        """Run host."""
        return False

    def monitor(self) -> int:
        """Run monitor."""
        return 1

    def create_border_widget(self) -> object:
        """Run create border widget."""
        return Borders(self)

    def create_start_menu(self) -> object:
        """Run create start menu."""
        return QRWidget(self.game.buzzer_controller.host(), self)

    def create_score_board(self) -> object:
        """Run create score board."""
        return ScoreBoard(self.game, self)

    def create_question_widget(self, q: object) -> object:
        """Run create question widget."""
        if q.dd:
            return DailyDoubleWidget(q, self)
        else:
            return QuestionWidget(q, self)

    def create_final_widget(self, q: object) -> object:
        """Run create final widget."""
        return FinalJeopardyWidget(q, self)

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
        fullrect = self.rect()
        margins = (
            QMargins(
                fullrect.width(), fullrect.height(), fullrect.width(), fullrect.height()
            )
            * 0.3
        )
        if self.welcome_widget is not None:
            self.welcome_widget.setGeometry(fullrect - margins)
        if self.final_display is not None:
            self.final_display.setGeometry(fullrect)

    def show_welcome_widgets(self) -> None:
        """Run show welcome widgets."""
        self.welcome_widget.setVisible(True)
        self.welcome_widget.setDisabled(False)
        self.welcome_widget.restart()

    def hide_welcome_widgets(self) -> None:
        """Run hide welcome widgets."""
        self.welcome_widget.setVisible(False)
        self.welcome_widget.setDisabled(True)

    def hide_question(self) -> None:
        """Run hide question."""
        self.board_widget.setVisible(True)
        self.board_layout.replaceWidget(self.question_widget, self.board_widget)
        self.question_widget.deleteLater()
        self.question_widget = None

    def load_question(self, q: object) -> None:
        """Run load question."""
        self.question_widget = self.create_question_widget(q)
        self.board_widget.setVisible(False)
        self.board_layout.replaceWidget(self.board_widget, self.question_widget)

    def load_final(self, q: object) -> None:
        """Run load final."""
        self.question_widget = self.create_final_widget(q)
        self.board_widget.setVisible(False)
        self.board_layout.replaceWidget(self.board_widget, self.question_widget)

    def load_final_judgement(self) -> None:
        """Run load final judgement."""
        self.final_display = FinalDisplay(self.game, self)
        self.final_window = self.final_display.answer_widget

    def load_final_graphs(self) -> None:
        """Run load final graphs."""
        self.graph_display = GraphDisplay(self)
        self.question_widget.setVisible(False)
        self.final_display.setVisible(False)
        self.board_layout.replaceWidget(self.question_widget, self.graph_display)

    def closeEvent(self, event: object) -> None:
        """Run closeevent."""
        super().closeEvent(event)
        self.game.close()

    def player_widget(self, player: object) -> object:
        """Run player widget."""
        for pw in self.scoreboard.player_widgets:
            if pw.player is player:
                return pw

    def remove_card(self, q: object) -> None:
        """Run remove card."""
        for label in self.board_widget.question_labels:
            if label.question is q:
                label.question = None

    def restart(self) -> None:
        """Run restart."""
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
    """Represent hostdisplaywindow."""

    def __init__(self, game: object) -> None:
        """Initialize the instance."""
        super().__init__(game)
        self.on_image_question = False

    def host(self) -> bool:
        """Run host."""
        return True

    def monitor(self) -> int:
        """Run monitor."""
        return 0

    def create_start_menu(self) -> object:
        """Run create start menu."""
        return Welcome(self.game, self)

    def create_score_board(self) -> object:
        """Run create score board."""
        return HostScoreBoard(self.game, self)

    def create_border_widget(self) -> object:
        """Run create border widget."""
        return HostBorders(self)

    def create_question_widget(self, q: object) -> object:
        """Run create question widget."""
        if q.dd:
            return HostDailyDoubleWidget(q, self)
        else:
            return HostQuestionWidget(q, self)

    def create_image_question_widget(self, game: object) -> object:
        """Run create image question widget."""
        return HostImageQuestionWidget(game, self)

    def create_final_widget(self, q: object) -> object:
        """Run create final widget."""
        return HostFinalJeopardyWidget(q, self)

    def keyPressEvent(self, event: object) -> None:
        """Run keypressevent."""
        self.game.keystroke_manager.call(event.key())

    def hide_welcome_widgets(self) -> None:
        """Run hide welcome widgets."""
        super().hide_welcome_widgets()
        self.scoreboard.hide_close_buttons()

    def load_image_review_screen(self, q: object) -> None:
        """Run load image review screen."""
        self.on_image_question = True
        self.image_question_widget = self.create_image_question_widget(self.game)
        self.board_widget.setVisible(False)
        self.board_layout.replaceWidget(self.board_widget, self.image_question_widget)

    def load_question(self, q: object) -> None:
        """Run load question."""
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
