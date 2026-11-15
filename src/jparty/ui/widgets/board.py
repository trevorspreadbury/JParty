"""Board widgets for rendering categories and clue cards.

This module contains the card widgets that display Jeopardy categories and clue
values, along with the grid widget that lays out an entire round board for the
host and audience displays.
"""

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QGridLayout, QWidget

from jparty.domain.models import Board
from jparty.ui.styles import CARDPAL, DARKBLUE, JBLUE, MyLabel


class CardLabel(QWidget):
    """Base widget for a styled board card containing a single label."""

    def __init__(self, text: object, parent: object = None) -> None:
        """Initialize a card widget with centered auto-sized text.

        Args:
            text: Initial text to display inside the card.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.label = MyLabel(text, self.startFontSize, parent=self)
        self.label.setAutosizeMargins(0.1)
        self.setPalette(CARDPAL)
        self.setAutoFillBackground(True)

    def startFontSize(self) -> object:
        """Return the initial text size used for card auto-sizing.

        Returns:
            A font size derived from the current widget height.
        """
        return self.height() * 0.6

    def setText(self, text: object) -> None:
        """Update the card text.

        Args:
            text: New text to display.

        Returns:
            ``None``.
        """
        self.label.setText(text)

    @property
    def text(self) -> object:
        """Return the current card text.

        Returns:
            The inner label's current text value.
        """
        return self.label.text()

    def resizeEvent(self, event: object) -> None:
        """Resize the inner label to fill the card.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        self.label.setGeometry(self.rect())


class CategoryCard(CardLabel):
    """Display a category heading at the top of the board."""

    pass


class QuestionCard(CardLabel):
    """Display a clue's dollar value and completion state."""

    def __init__(self, game: object, question: object = None) -> None:
        """Initialize a board card for a clue.

        Args:
            game: Active game instance that owns the clue.
            question: Optional ``Question`` object represented by the card.

        Returns:
            ``None``.
        """
        self.game = game
        self.__question = question
        super().__init__(self.__moneytext())
        self.label.setStyleSheet("color: #ffcc00")
        self.label.setAutosizeMargins(0.2)

    @property
    def question(self) -> object:
        """Return the question currently attached to the card.

        Returns:
            The current ``Question`` object, or ``None``.
        """
        return self.__question

    def __moneytext(self) -> object:
        """Return the display text for the clue's board value.

        Returns:
            The formatted dollar amount for an available clue, or an empty
            string when the clue is unavailable.
        """
        if self.question is not None and (not self.question.complete):
            return "$" + str(self.question.value)
        else:
            return ""

    @question.setter
    def question(self, q: object) -> None:
        """Assign a new question to the card and refresh its text.

        Args:
            q: New ``Question`` object to associate with the card.

        Returns:
            ``None``.
        """
        self.__question = q
        self.setText(self.__moneytext())

    def startFontSize(self) -> object:
        """Return the initial font size for clue values.

        Returns:
            A font size derived from the current widget height.
        """
        return self.height() * 0.5

    def inactive(self) -> object:
        """Check whether the card should ignore interaction.

        Returns:
            ``True`` when the card has no question or the clue is already
            complete.
        """
        return self.question is None or self.question.complete


class HostQuestionCard(QuestionCard):
    """Interactive clue card used on the host board."""

    def __init__(self, game: object, question: object = None) -> None:
        """Initialize a host-side interactive clue card.

        Args:
            game: Active game instance that handles clue selection.
            question: Optional ``Question`` object represented by the card.

        Returns:
            ``None``.
        """
        super().__init__(game, question)
        self.setMouseTracking(True)

    def mousePressEvent(self, event: object) -> None:
        """Load the selected clue when the host clicks the card.

        Args:
            event: Qt mouse event object.

        Returns:
            ``None``.
        """
        if self.inactive():
            return None
        self.leaveEvent(None)
        if self.question.image:
            self.game.load_image_review_screen(self.question)
        else:
            self.game.load_question(self.question)

    def leaveEvent(self, event: object) -> None:
        """Restore the default card background when the mouse leaves.

        Args:
            event: Qt enter/leave event object.

        Returns:
            ``None``.
        """
        if self.inactive():
            return None
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, JBLUE)
        self.setPalette(pal)

    def enterEvent(self, event: object) -> None:
        """Highlight the card while the host hovers over it.

        Args:
            event: Qt enter/leave event object.

        Returns:
            ``None``.
        """
        if self.inactive():
            return None
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, DARKBLUE)
        self.setPalette(pal)


class BoardWidget(QWidget):
    """Render a full Jeopardy round board as a grid of card widgets."""

    rows = 6
    columns = 6

    def __init__(self, game: object, parent: object = None) -> None:
        """Initialize the board grid for a host or audience display.

        Args:
            game: Active game instance whose current round is displayed.
            parent: Optional parent widget, typically a display window.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.game = game
        self.responses_open = False
        self.questionwidget = None
        self.question_labels = []
        self.grid_layout = QGridLayout()
        self.resizeEvent(None)
        for x in range(Board.size[0]):
            self.grid_layout.setRowStretch(x, 1)
        for y in range(Board.size[1] + 1):
            self.grid_layout.setColumnStretch(y, 1)
        for x in range(Board.size[0]):
            for y in range(Board.size[1] + 1):
                if y == 0:
                    label = CategoryCard("")
                    self.grid_layout.addWidget(label, 0, x)
                else:
                    if self.parent().host():
                        label = HostQuestionCard(game, None)
                    else:
                        label = QuestionCard(game, None)
                    self.question_labels.append(label)
                    self.grid_layout.addWidget(label, y, x)
        self.setLayout(self.grid_layout)
        self.show()

    def load_round(self, round: object) -> None:
        """Populate the grid with categories and clue cards for a round.

        Args:
            round: Round object containing categories and questions.

        Returns:
            ``None``.
        """
        gl = self.grid_layout
        for x in range(Board.size[0]):
            for y in range(Board.size[1] + 1):
                if y == 0:
                    gl.itemAtPosition(y, x).widget().setText(round.categories[x])
                else:
                    q = round.get_question(x, y - 1)
                    gl.itemAtPosition(y, x).widget().question = q

    def resizeEvent(self, event: object) -> None:
        """Update grid spacing in response to widget size changes.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        self.grid_layout.setSpacing(self.width() // 150)

    @property
    def board(self) -> object:
        """Return the round currently shown on the board.

        Returns:
            The game's current round object.
        """
        return self.game.current_round

    def clear(self) -> None:
        """Reset all board cards to an empty state.

        Returns:
            ``None``.
        """
        gl = self.grid_layout
        for x in range(Board.size[0]):
            for y in range(Board.size[1] + 1):
                if y == 0:
                    gl.itemAtPosition(y, x).widget().setText("")
                else:
                    gl.itemAtPosition(y, x).widget().question = None
