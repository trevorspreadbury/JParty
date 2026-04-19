"""Final module."""

import os

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from jparty.app.paths import GAME_SCORES_DIR
from jparty.ui.styles import CARDPAL, MyLabel
from jparty.ui.widgets.common import add_shadow
from jparty.ui.widgets.scoreboard import NameLabel


class GraphDisplay(QWidget):
    """Represent graphdisplay."""

    def __init__(self, parent: object) -> None:
        """Initialize the instance."""
        super().__init__(parent)
        self.main_layout = QVBoxLayout()
        self.question_label = MyLabel(
            str(GAME_SCORES_DIR / f"{os.environ['JPARTY_GAME_ID']}-all.jpg"),
            10,
            self,
            True,
        )
        self.main_layout.addWidget(self.question_label)
        self.setLayout(self.main_layout)
        self.setPalette(CARDPAL)
        self.show()


class FinalDisplay(QWidget):
    """Represent finaldisplay."""

    def __init__(self, game: object, parent: object) -> None:
        """Initialize the instance."""
        super().__init__(parent)
        self.setGeometry(parent.rect())
        self.answer_widget = FinalAnswerWidget(game, self)
        main_layout = QVBoxLayout()
        main_layout.addStretch(4)
        main_layout.addWidget(self.answer_widget, 2)
        main_layout.addStretch(3)
        self.setLayout(main_layout)
        self.show()


class FinalAnswerWidget(QWidget):
    """Represent finalanswerwidget."""

    def __init__(self, game: object, parent: object) -> None:
        """Initialize the instance."""
        super().__init__(parent)
        self.game = game
        self.winner_label = None
        self.main_layout = QVBoxLayout()
        self.guess_label = MyLabel("", self.startFontSize, self)
        self.wager_label = MyLabel("", self.startFontSize, self)
        self.main_layout.addStretch(1)
        self.main_layout.addWidget(self.guess_label, 5)
        self.main_layout.addWidget(self.wager_label, 5)
        self.main_layout.addStretch(1)
        self.setLayout(self.main_layout)
        self.setPalette(CARDPAL)
        self.setAutoFillBackground(True)
        add_shadow(self)
        self.show()

    def startFontSize(self) -> object:
        """Run startfontsize."""
        return self.height() * 0.2

    def show_winner(self, winner: object) -> None:
        """Run show winner."""
        self.guess_label.setText("We have a winner!")
        self.wager_label.setText("")
        self.winner_label = NameLabel(winner.name, self)
        self.main_layout.replaceWidget(self.wager_label, self.winner_label)

    def show_tie(self) -> None:
        """Run show tie."""
        self.guess_label.setText("We have a tie!")
        self.wager_label.setText("")
