"""Board widgets for rendering categories and clue cards.

This module contains the card widgets that display Jeopardy categories and clue
values, along with the grid widget that lays out an entire round board for the
host and audience displays.
"""

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QGridLayout, QWidget

from jparty.domain.models import Board
from jparty.ui.styles import (
    CARDPAL,
    CATEGORY_COMMENT_STYLE,
    DARKBLUE,
    JBLUE,
    MyLabel,
)


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

    def setComment(self, comment: str) -> None:
        """Ignore category comments; only the host sees them.

        Args:
            comment: Host-only hint for the category.

        Returns:
            ``None``.
        """
        return None


# Share of a host category card's height given to the hint when there is one.
CATEGORY_COMMENT_HEIGHT_FRACTION = 0.4


class HostCategoryCard(CategoryCard):
    """Category heading on the host board, with the category's hint beneath it.

    J-Archive records what the TV host said about some categories, such as
    ``(Ken: Each response ends in "-ing".)``. The host board shows that under
    the category name so the host can read it out; the audience board never
    does.
    """

    def __init__(self, text: object, parent: object = None) -> None:
        """Initialize a host category card with an empty hint.

        Args:
            text: Initial category name.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(text, parent)
        self.comment_label = MyLabel("", self.commentFontSize, parent=self)
        self.comment_label.setAutosizeMargins(0.05)
        self.comment_label.setStyleSheet(CATEGORY_COMMENT_STYLE)
        self.comment_label.setVisible(False)

    def commentFontSize(self) -> object:
        """Return the initial text size used for the hint.

        Returns:
            A font size derived from the current widget height.
        """
        return self.height() * 0.25

    def setComment(self, comment: str) -> None:
        """Show ``comment`` under the category name, or hide it when empty.

        Args:
            comment: Host-only hint for the category.

        Returns:
            ``None``.
        """
        comment = comment or ""
        self.comment_label.setText(comment)
        self.comment_label.setVisible(bool(comment))
        self.resizeEvent(None)

    @property
    def comment(self) -> str:
        """Return the hint currently shown under the category name.

        Returns:
            The hint text, or ``""`` when the category has none.
        """
        return self.comment_label.text()

    def resizeEvent(self, event: object) -> None:
        """Split the card between the name and the hint when there is a hint.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        rect = self.rect()
        if not self.comment_label.isVisibleTo(self):
            self.label.setGeometry(rect)
            return
        comment_height = int(rect.height() * CATEGORY_COMMENT_HEIGHT_FRACTION)
        name_rect = rect.adjusted(0, 0, 0, -comment_height)
        self.label.setGeometry(name_rect)
        self.comment_label.setGeometry(
            rect.left(), name_rect.bottom() + 1, rect.width(), comment_height
        )


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
                    if self.parent().host():
                        label = HostCategoryCard("")
                    else:
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
                    card = gl.itemAtPosition(y, x).widget()
                    card.setText(round.categories[x])
                    card.setComment(round.category_comments[x])
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
                    gl.itemAtPosition(y, x).widget().setComment("")
                else:
                    gl.itemAtPosition(y, x).widget().question = None
