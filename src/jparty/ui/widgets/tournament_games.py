"""A tournament's Games tab: which board each bracket game plays.

"Set Board..." (or double-clicking a game) opens the board picker
(:mod:`jparty.ui.widgets.board_setup`), which uses the same advanced board
editor as the welcome screen, to choose or edit that game's board. Boards can be swapped between games, and boards whose game leaves the
bracket wait in an unassigned pool. The assignment rules live in
:mod:`jparty.domain.tournament_setup`.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.tournament import TournamentPlan
from jparty.domain.tournament_setup import (
    TournamentBoard,
    assign_from_pool,
    plan_games,
    reconcile_boards,
    shared_board_warnings,
    swap_boards,
    unassign_board,
)
from jparty.services.question_media import detect_question_media
from jparty.ui.widgets.board_setup import pick_board

LAYOUT_SPACING = 8
COLUMN_GAME = 0
COLUMN_SEATS = 1
COLUMN_BOARD = 2
COLUMN_MEDIA = 3
TABLE_HEADERS = ("Game", "Players", "Board", "Question media")
NO_BOARD_TEXT = "Unassigned"
SWAP_GAME_COUNT = 2
PROBLEM_STYLE = "QLabel { color: #b00020; }"


def missing_media_ids(board: TournamentBoard) -> list[str]:
    """Return the board's source game ids that have no usable question media.

    This only looks for a local media folder or zip, so it is quick enough
    for the UI thread.

    Args:
        board: A tournament board.

    Returns:
        Source game ids without a media folder or a zip that extracts.
    """
    missing = []
    for game_id in board.source_game_ids:
        status = detect_question_media(game_id)
        if status.error or not (status.has_directory or status.has_zip):
            missing.append(game_id)
    return missing


class GamesEditor(QWidget):
    """Assign boards to a tournament's games.

    Attributes:
        boards: Board for each game, by game key.
        unassigned: Boards not assigned to any game.
    """

    games_changed = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        pick_board: Callable[
            [str, TournamentBoard | None, QWidget | None], TournamentBoard | None
        ] = pick_board,
        missing_media: Callable[[TournamentBoard], list[str]] = missing_media_ids,
    ) -> None:
        """Build the games table and the unassigned pool.

        Args:
            parent: Optional parent widget.
            pick_board: Asks the host for a game's board, given the game key
                and its current board; returns ``None`` if cancelled. Tests
                pass a fake.
            missing_media: Returns a board's source ids without question
                media; tests pass a fake.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.pick_board = pick_board
        self.missing_media = missing_media
        self.boards: dict[str, TournamentBoard] = {}
        self.unassigned: list[TournamentBoard] = []
        self._game_keys: list[str] = []
        self._plan: TournamentPlan | None = None

        self.summary_label = QLabel(self)
        self.summary_label.setWordWrap(True)

        self.table = QTableWidget(0, len(TABLE_HEADERS), self)
        self.table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column in (COLUMN_GAME, COLUMN_MEDIA):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.cellDoubleClicked.connect(self.set_board_for_row)

        self.set_board_button = QPushButton("Set Board...", self)
        self.set_board_button.setToolTip(
            "Choose or edit the selected game's board with the welcome"
            " screen's board tools. Double-clicking a game does the same."
        )
        self.set_board_button.clicked.connect(self.set_selected_board)
        self.swap_button = QPushButton("Swap Boards", self)
        self.swap_button.setToolTip("Swap the boards of the two selected games.")
        self.swap_button.clicked.connect(self.swap_selected)
        self.unassign_button = QPushButton("Unassign", self)
        self.unassign_button.setToolTip(
            "Move the selected games' boards to Unassigned."
        )
        self.unassign_button.clicked.connect(self.unassign_selected)
        game_buttons = QHBoxLayout()
        game_buttons.addWidget(self.set_board_button)
        game_buttons.addWidget(self.swap_button)
        game_buttons.addWidget(self.unassign_button)
        game_buttons.addStretch(1)

        self.pool_label = QLabel("Unassigned boards:", self)
        self.pool_list = QListWidget(self)
        self.pool_list.setMaximumHeight(110)
        self.pool_list.itemSelectionChanged.connect(self._update_buttons)
        self.assign_pool_button = QPushButton("Assign to Selected Game", self)
        self.assign_pool_button.clicked.connect(self.assign_selected_pool_board)
        self.delete_pool_button = QPushButton("Delete Board", self)
        self.delete_pool_button.clicked.connect(self.delete_selected_pool_board)
        pool_buttons = QHBoxLayout()
        pool_buttons.addWidget(self.assign_pool_button)
        pool_buttons.addWidget(self.delete_pool_button)
        pool_buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setSpacing(LAYOUT_SPACING)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING,) * 4)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table, 1)
        layout.addLayout(game_buttons)
        layout.addWidget(self.pool_label)
        layout.addWidget(self.pool_list)
        layout.addLayout(pool_buttons)
        self._redraw()

    def set_boards(
        self, boards: dict[str, TournamentBoard], unassigned: list[TournamentBoard]
    ) -> None:
        """Show saved assignments, without emitting :attr:`games_changed`.

        Args:
            boards: Board for each game, by game key.
            unassigned: Boards not assigned to any game.

        Returns:
            ``None``.
        """
        self.boards = dict(boards)
        self.unassigned = list(unassigned)
        self._reconcile()
        self._redraw()

    def set_plan(self, plan: TournamentPlan) -> None:
        """Show the games of ``plan``; boards for dropped games go to the pool.

        While the plan is invalid, assignments are left alone, so fixing the
        bracket brings them back.

        Args:
            plan: The tournament's current bracket.

        Returns:
            ``None``.
        """
        self._plan = plan
        self._game_keys = [key for key, _, _ in plan_games(plan)]
        changed = self._reconcile()
        self._redraw()
        if changed:
            self.games_changed.emit()

    def selected_keys(self) -> list[str]:
        """Return the keys of the selected games, in playing order."""
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [
            self._game_keys[row] for row in sorted(rows) if row < len(self._game_keys)
        ]

    def set_selected_board(self) -> None:
        """Choose or edit the selected game's board.

        Returns:
            ``None``.
        """
        keys = self.selected_keys()
        if len(keys) == 1:
            self.set_board(keys[0])

    def set_board_for_row(self, row: int, _column: int = 0) -> None:
        """Choose or edit the board of the game in ``row``.

        Args:
            row: Table row, as given by a double-click.
            _column: Clicked column; unused.

        Returns:
            ``None``.
        """
        if 0 <= row < len(self._game_keys):
            self.set_board(self._game_keys[row])

    def set_board(self, key: str) -> None:
        """Ask the host for a game's board and store it.

        Editing a game's board replaces it. A cancelled pick changes nothing.

        Args:
            key: The game's key.

        Returns:
            ``None``.
        """
        board = self.pick_board(key, self.boards.get(key), self)
        if board is None:
            return
        # An edit replaces the old version instead of keeping it in the pool.
        self.boards = {**self.boards, key: board}
        self._changed()

    def swap_selected(self) -> None:
        """Swap the boards of the two selected games.

        Returns:
            ``None``.
        """
        keys = self.selected_keys()
        if len(keys) == SWAP_GAME_COUNT:
            self.boards = swap_boards(self.boards, *keys)
            self._changed()

    def unassign_selected(self) -> None:
        """Move the selected games' boards to the pool.

        Returns:
            ``None``.
        """
        for key in self.selected_keys():
            self.boards, self.unassigned = unassign_board(
                self.boards, self.unassigned, key
            )
        self._changed()

    def assign_selected_pool_board(self) -> None:
        """Give the selected game the selected unassigned board.

        Returns:
            ``None``.
        """
        keys = self.selected_keys()
        pool_index = self.pool_list.currentRow()
        if len(keys) != 1 or not 0 <= pool_index < len(self.unassigned):
            return
        self.boards, self.unassigned = assign_from_pool(
            self.boards, self.unassigned, pool_index, keys[0]
        )
        self._changed()

    def delete_selected_pool_board(self) -> None:
        """Remove the selected unassigned board.

        Returns:
            ``None``.
        """
        pool_index = self.pool_list.currentRow()
        if 0 <= pool_index < len(self.unassigned):
            del self.unassigned[pool_index]
            self._changed()

    def _reconcile(self) -> bool:
        """Move boards for games not in a valid plan to the pool.

        Returns:
            Whether any board moved.
        """
        if self._plan is None or not self._plan.valid:
            return False
        before = len(self.unassigned)
        self.boards, self.unassigned = reconcile_boards(
            self._game_keys, self.boards, self.unassigned
        )
        return len(self.unassigned) != before

    def _changed(self) -> None:
        """Redraw, keeping the selection, and report the change."""
        selected = set(self.selected_keys())
        self._redraw()
        for row, key in enumerate(self._game_keys):
            if key in selected:
                self.table.selectionModel().select(
                    self.table.model().index(row, 0),
                    self.table.selectionModel().SelectionFlag.Select
                    | self.table.selectionModel().SelectionFlag.Rows,
                )
        self.games_changed.emit()

    def _redraw(self) -> None:
        """Redraw the games table, the pool, and the summary."""
        games = plan_games(self._plan) if self._plan is not None else []
        self.table.setRowCount(len(games))
        missing_boards = 0
        no_media = []
        for row, (key, _bracket_round, game) in enumerate(games):
            board = self.boards.get(key)
            missing = self.missing_media(board) if board is not None else []
            if board is None:
                missing_boards += 1
                media_text = ""
            elif missing:
                no_media.append(key)
                media_text = "None for " + ", ".join(missing)
            else:
                media_text = "Yes"
            cells = (
                key,
                "; ".join(game.seats),
                board.label if board is not None else NO_BOARD_TEXT,
                media_text,
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if column == COLUMN_BOARD and board is None:
                    item.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(row, column, item)

        self.pool_list.clear()
        for board in self.unassigned:
            self.pool_list.addItem(board.label)
        self.pool_label.setText(f"Unassigned boards ({len(self.unassigned)}):")

        if self._plan is None or not self._plan.valid:
            self._show_status(
                "Fix the bracket on the Bracket tab to see its games.", problem=True
            )
        else:
            lines = [
                f"{len(games) - missing_boards} of {len(games)} games have a board."
            ]
            if no_media:
                lines.append("No question media: " + ", ".join(no_media) + ".")
            lines += shared_board_warnings(self._game_keys, self.boards)
            self._show_status("\n".join(lines))
        self._update_buttons()

    def _update_buttons(self) -> None:
        """Enable the buttons that apply to the current selection."""
        keys = self.selected_keys()
        self.set_board_button.setEnabled(len(keys) == 1)
        self.swap_button.setEnabled(
            len(keys) == SWAP_GAME_COUNT and any(key in self.boards for key in keys)
        )
        self.unassign_button.setEnabled(any(key in self.boards for key in keys))
        pool_selected = bool(self.pool_list.selectedItems())
        self.assign_pool_button.setEnabled(pool_selected and len(keys) == 1)
        self.delete_pool_button.setEnabled(pool_selected)

    def _show_status(self, message: str, problem: bool = False) -> None:
        """Show ``message`` above the table, in red for problems."""
        self.summary_label.setStyleSheet(PROBLEM_STYLE if problem else "")
        self.summary_label.setText(message)
