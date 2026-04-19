"""Board module."""

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QGridLayout, QWidget

from jparty.domain.models import Board
from jparty.ui.styles import CARDPAL, DARKBLUE, JBLUE, MyLabel


class CardLabel(QWidget):
    """Represent cardlabel."""

    def __init__(self, text: object, parent: object = None) -> None:
        """Initialize the instance."""
        super().__init__(parent)
        self.label = MyLabel(text, self.startFontSize, parent=self)
        self.label.setAutosizeMargins(0.1)
        self.setPalette(CARDPAL)
        self.setAutoFillBackground(True)

    def startFontSize(self) -> object:
        """Run startfontsize."""
        return self.height() * 0.6

    def setText(self, text: object) -> None:
        """Run settext."""
        self.label.setText(text)

    @property
    def text(self) -> object:
        """Run text."""
        return self.label.text()

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
        self.label.setGeometry(self.rect())


class CategoryCard(CardLabel):
    """Represent categorycard."""

    pass


class QuestionCard(CardLabel):
    """Represent questioncard."""

    def __init__(self, game: object, question: object = None) -> None:
        """Initialize the instance."""
        self.game = game
        self.__question = question
        super().__init__(self.__moneytext())
        self.label.setStyleSheet("color: #ffcc00")
        self.label.setAutosizeMargins(0.2)

    @property
    def question(self) -> object:
        """Run question."""
        return self.__question

    def __moneytext(self) -> object:
        """Return moneytext."""
        if self.question is not None and (not self.question.complete):
            return "$" + str(self.question.value)
        else:
            return ""

    @question.setter
    def question(self, q: object) -> None:
        """Run question."""
        self.__question = q
        self.setText(self.__moneytext())

    def startFontSize(self) -> object:
        """Run startfontsize."""
        return self.height() * 0.5

    def inactive(self) -> object:
        """Run inactive."""
        return self.question is None or self.question.complete


class HostQuestionCard(QuestionCard):
    """Represent hostquestioncard."""

    def __init__(self, game: object, question: object = None) -> None:
        """Initialize the instance."""
        super().__init__(game, question)
        self.setMouseTracking(True)

    def mousePressEvent(self, event: object) -> None:
        """Run mousepressevent."""
        if self.inactive():
            return None
        self.leaveEvent(None)
        if self.question.image:
            self.game.load_image_review_screen(self.question)
        else:
            self.game.load_question(self.question)

    def leaveEvent(self, event: object) -> None:
        """Run leaveevent."""
        if self.inactive():
            return None
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, JBLUE)
        self.setPalette(pal)

    def enterEvent(self, event: object) -> None:
        """Run enterevent."""
        if self.inactive():
            return None
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, DARKBLUE)
        self.setPalette(pal)


class BoardWidget(QWidget):
    """Represent boardwidget."""

    rows = 6
    columns = 6

    def __init__(self, game: object, parent: object = None) -> None:
        """Initialize the instance."""
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
        """Run load round."""
        gl = self.grid_layout
        for x in range(Board.size[0]):
            for y in range(Board.size[1] + 1):
                if y == 0:
                    gl.itemAtPosition(y, x).widget().setText(round.categories[x])
                else:
                    q = round.get_question(x, y - 1)
                    gl.itemAtPosition(y, x).widget().question = q

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
        self.grid_layout.setSpacing(self.width() // 150)

    @property
    def board(self) -> object:
        """Run board."""
        return self.game.current_round

    def clear(self) -> None:
        """Run clear."""
        gl = self.grid_layout
        for x in range(Board.size[0]):
            for y in range(Board.size[1] + 1):
                if y == 0:
                    gl.itemAtPosition(y, x).widget().setText("")
                else:
                    gl.itemAtPosition(y, x).widget().question = None
