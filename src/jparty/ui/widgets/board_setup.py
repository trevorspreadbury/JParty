"""Choose a tournament game's board with the advanced board editor.

:class:`BoardPickerDialog` shows the same :class:`AdvancedBoardEditor` the
welcome screen uses under Advanced Options, so boards are built the same way
in both places. The board is only stored in the tournament; it never changes
the game being set up on the welcome screen.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.tournament.setup import TournamentBoard, board_from_selections
from jparty.ui.widgets.advanced_boards import AdvancedBoardEditor

LAYOUT_SPACING = 8
INCOMPLETE_TEXT = "Fill every board slot to use this board."


class BoardPickerDialog(QDialog):
    """Choose or edit the board for one tournament game.

    Attributes:
        editor: The board-slot rows.
        board: The chosen board once accepted, else ``None``.
    """

    def __init__(
        self,
        game_key: str,
        board: TournamentBoard | None = None,
        parent: QWidget | None = None,
        run_async: Callable[[Callable[[], None]], object] | None = None,
    ) -> None:
        """Build the dialog for ``game_key``.

        Args:
            game_key: The tournament game, shown in the title.
            board: The game's current board, to edit, or ``None``.
            parent: Optional parent widget.
            run_async: Runs a callable off the UI thread; tests pass one that
                runs it inline.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.setWindowTitle(f"Set Board: {game_key}")
        self.resize(1150, 820)
        self.board: TournamentBoard | None = None

        self.editor = AdvancedBoardEditor(self, run_async=run_async)
        self.one_game_edit = QLineEdit(self)
        self.one_game_edit.setPlaceholderText("Game id")
        self.one_game_edit.returnPressed.connect(self.use_one_game)
        self.one_game_button = QPushButton("Use for Every Slot", self)
        self.one_game_button.setToolTip(
            "Play one game as it aired: every slot loads this game and picks"
            " its matching round."
        )
        self.one_game_button.clicked.connect(self.use_one_game)
        one_game_layout = QHBoxLayout()
        one_game_layout.addWidget(QLabel("Same game for every slot:", self))
        one_game_layout.addWidget(self.one_game_edit)
        one_game_layout.addWidget(self.one_game_button)
        one_game_layout.addStretch(1)

        self.summary_label = QLabel(INCOMPLETE_TEXT, self)
        self.summary_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.use_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.use_button.setText("Use This Board")
        self.use_button.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(LAYOUT_SPACING)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING * 2,) * 4)
        layout.addLayout(one_game_layout)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.buttons)

        self.editor.setup_changed.connect(self.update_summary)
        if board is not None:
            self.editor.show_board_selections(board.board_selections)
        self.update_summary()

    def use_one_game(self) -> None:
        """Load the typed game into every slot.

        Returns:
            ``None``.
        """
        game_id = self.one_game_edit.text().strip()
        if game_id:
            self.editor.fill_all_slots(game_id)

    def update_summary(self) -> None:
        """Show the board's summary and allow Use This Board once it's ready.

        Returns:
            ``None``.
        """
        setup = self.editor.current_setup()
        self.summary_label.setText(setup.summary_text() or INCOMPLETE_TEXT)
        self.use_button.setEnabled(setup.ready)

    def accept(self) -> None:
        """Keep the board and close, if every slot is ready.

        Returns:
            ``None``.
        """
        setup = self.editor.current_setup()
        if not setup.ready:
            self.update_summary()
            return
        self.board = board_from_selections(
            setup.session_game_id, setup.board_selections
        )
        super().accept()

    def resizeEvent(self, event: object) -> None:
        """Size the editor's fonts and fields for the dialog.

        Args:
            event: Qt resize event.

        Returns:
            ``None``.
        """
        super().resizeEvent(event)
        self.editor.apply_scale(self.height(), self.width())


def pick_board(
    game_key: str, board: TournamentBoard | None, parent: QWidget | None = None
) -> TournamentBoard | None:
    """Ask the host for a game's board.

    Args:
        game_key: The tournament game.
        board: Its current board, to edit, or ``None``.
        parent: Parent for the dialog.

    Returns:
        The chosen board, or ``None`` if the host cancelled.
    """
    dialog = BoardPickerDialog(game_key, board, parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.board
    return None
