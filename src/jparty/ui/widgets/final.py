"""Widgets used during Final Jeopardy and score-graph presentation.

This module provides the final-round answer display widgets and the end-of-game
graph viewer shown after results have been adjudicated.
"""

import os

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from jparty.app.paths import GAME_SCORES_DIR
from jparty.ui.styles import CARDPAL, MyLabel
from jparty.ui.widgets.common import add_shadow
from jparty.ui.widgets.scoreboard import NameLabel


class GraphDisplay(QWidget):
    """Display the saved end-of-game score graph image."""

    def __init__(self, parent: object) -> None:
        """Initialize the graph display widget.

        Args:
            parent: Parent display widget.

        Returns:
            ``None``.
        """
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
    """Container widget for Final Jeopardy answer adjudication."""

    def __init__(self, game: object, parent: object) -> None:
        """Initialize the Final Jeopardy display container.

        Args:
            game: Active game instance driving Final Jeopardy flow.
            parent: Parent display widget.

        Returns:
            ``None``.
        """
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
    """Show Final Jeopardy guesses, wagers, and winner announcements."""

    def __init__(self, game: object, parent: object) -> None:
        """Initialize the final answer widget.

        Args:
            game: Active game instance driving Final Jeopardy flow.
            parent: Parent widget.

        Returns:
            ``None``.
        """
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
        """Return the starting font size for final-round labels.

        Returns:
            A font size derived from the current widget height.
        """
        return self.height() * 0.2

    def show_winner(self, winner: object) -> None:
        """Replace wager text with a winner announcement.

        Args:
            winner: Winning player object.

        Returns:
            ``None``.
        """
        self.guess_label.setText("We have a winner!")
        self.wager_label.setText("")
        self.winner_label = NameLabel(winner.name, self)
        self.main_layout.replaceWidget(self.wager_label, self.winner_label)

    def show_tie(self) -> None:
        """Show a tie announcement in the final-round UI.

        Returns:
            ``None``.
        """
        self.guess_label.setText("We have a tie!")
        self.wager_label.setText("")
