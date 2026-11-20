"""Previewing every tournament board's question media before playing.

The Games tab's Preview All Media button builds every board (see
:mod:`jparty.services.board_prep`), then :class:`BoardMediaPreviewDialog`
shows each board's local question media with its correct response, so the
host can check the images before game day.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from jparty.services.board_prep import PreparedBoard

LAYOUT_SPACING = 8
CARD_COLUMNS = 4
THUMBNAIL_WIDTH = 220
THUMBNAIL_HEIGHT = 150
PROBLEM_COLOR = "#b00020"
NO_MEDIA_TEXT = "No question media."
CARD_STYLE = (
    "QFrame#media_card { background: white; border: 1px solid #c6c6c6;"
    " border-radius: 4px; }"
)


def media_summary(boards: Sequence[PreparedBoard]) -> str:
    """Return a one-line count of the boards and images previewed.

    Args:
        boards: The prepared boards.

    Returns:
        For example ``"12 images on 3 of 5 boards. 1 board couldn't load."``.
    """
    images = sum(len(board.media) for board in boards)
    with_media = sum(1 for board in boards if board.media)
    failed = sum(1 for board in boards if board.data is None)
    text = (
        f"{images} image{'s' if images != 1 else ''} on {with_media} of "
        f"{len(boards)} board{'s' if len(boards) != 1 else ''}."
    )
    if failed:
        text += f" {failed} board{'s' if failed != 1 else ''} couldn't load."
    return text


class BoardMediaPreviewDialog(QDialog):
    """Every board's question media, one section per board.

    Attributes:
        boards: The prepared boards shown.
        cards: Each media card, in order.
    """

    def __init__(
        self, boards: Sequence[PreparedBoard], parent: QWidget | None = None
    ) -> None:
        """Show the media of ``boards``.

        Args:
            boards: The prepared boards, in playing order.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.boards = list(boards)
        self.cards: list[QFrame] = []
        self.setWindowTitle("Question Media Preview")
        self.resize(1040, 720)

        self.summary_label = QLabel(media_summary(self.boards), self)
        container = QWidget()
        self.sections = QVBoxLayout(container)
        self.sections.setSpacing(LAYOUT_SPACING * 2)
        self.sections.setContentsMargins(*(LAYOUT_SPACING,) * 4)
        for board in self.boards:
            self._add_section(container, board)
        self.sections.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING * 2,) * 4)
        layout.addWidget(self.summary_label)
        layout.addWidget(scroll, 1)
        layout.addWidget(buttons)

    def _add_section(self, container: QWidget, board: PreparedBoard) -> None:
        """Add a heading and the media cards for one board."""
        heading = QLabel(
            f"<b>{escape(board.key)}</b>: {escape(board.label)}", container
        )
        heading.setTextFormat(Qt.TextFormat.RichText)
        heading.setWordWrap(True)
        self.sections.addWidget(heading)
        if board.error:
            problem = QLabel(board.error, container)
            problem.setWordWrap(True)
            problem.setStyleSheet(f"QLabel {{ color: {PROBLEM_COLOR}; }}")
            self.sections.addWidget(problem)
        if board.data is None:
            return
        if not board.media:
            self.sections.addWidget(QLabel(NO_MEDIA_TEXT, container))
            return
        grid = QGridLayout()
        grid.setSpacing(LAYOUT_SPACING)
        for index, (_round_index, question) in enumerate(board.media):
            card = self._card(container, question)
            grid.addWidget(card, index // CARD_COLUMNS, index % CARD_COLUMNS)
        self.sections.addLayout(grid)

    def _card(self, container: QWidget, question: object) -> QFrame:
        """Return a card with a clue's image, category, and correct response."""
        card = QFrame(container)
        card.setObjectName("media_card")
        card.setStyleSheet(CARD_STYLE)
        image = QLabel(card)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setMinimumSize(THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)
        pixmap = QPixmap(str(question.image_url))
        if pixmap.isNull():
            image.setText(Path(str(question.image_url)).name)
        else:
            image.setPixmap(
                pixmap.scaled(
                    THUMBNAIL_WIDTH,
                    THUMBNAIL_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        value = getattr(question, "value", -1)
        where = question.category + (f" for ${value:,}" if value and value > 0 else "")
        # Clue text comes from the game, so never read it as rich text.
        category = QLabel(where, card)
        category.setTextFormat(Qt.TextFormat.PlainText)
        category.setWordWrap(True)
        category.setAlignment(Qt.AlignmentFlag.AlignCenter)
        answer = QLabel(question.answer, card)
        answer.setTextFormat(Qt.TextFormat.PlainText)
        answer.setWordWrap(True)
        answer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        answer.setStyleSheet("QLabel { color: black; font-weight: bold; }")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(*(LAYOUT_SPACING,) * 4)
        layout.addWidget(image, 1)
        layout.addWidget(category)
        layout.addWidget(answer)
        self.cards.append(card)
        return card


def show_board_media_preview(
    boards: Sequence[PreparedBoard], parent: QWidget | None = None
) -> None:
    """Open the media preview for ``boards`` and wait until it closes.

    Args:
        boards: The prepared boards.
        parent: Parent for the dialog.

    Returns:
        ``None``.
    """
    dialog = BoardMediaPreviewDialog(boards, parent)
    dialog.exec()
    dialog.deleteLater()
