"""A tournament's Games tab: which board each bracket game plays.

"Set Board..." (or double-clicking a game) opens the board picker
(:mod:`jparty.ui.widgets.board_setup`), which uses the same advanced board
editor as the welcome screen, to choose or edit a game's board. With no game
selected, the new board goes to the unassigned pool. "Can't Play..." picks
the players who must not play a board; they stay with the board wherever it
goes. Boards can be swapped between games, and boards whose game leaves the
bracket wait in the pool. The rules live in
:mod:`jparty.domain.tournament_setup`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
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
    edited_board,
    plan_games,
    reconcile_boards,
    shared_board_warnings,
    swap_boards,
    unassign_board,
    with_cant_play,
)
from jparty.services.question_media import detect_question_media
from jparty.ui.widgets.board_setup import pick_board

LAYOUT_SPACING = 8
COLUMN_GAME = 0
COLUMN_SEATS = 1
COLUMN_BOARD = 2
COLUMN_CANT_PLAY = 3
COLUMN_MEDIA = 4
TABLE_HEADERS = ("Game", "Players", "Board", "Can't Play", "Question media")
NO_BOARD_TEXT = "Unassigned"
NEW_POOL_BOARD_TARGET = "New unassigned board"
SWAP_GAME_COUNT = 2
PROBLEM_STYLE = "QLabel { color: #b00020; }"

# (player_id, name) for each named player on the roster, in roster order.
RosterPlayers = Sequence[tuple[str, str]]


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


class PlayerChecklistDialog(QDialog):
    """Tick the players who can't play a board."""

    def __init__(
        self,
        title: str,
        players: RosterPlayers,
        checked: Sequence[str],
        parent: QWidget | None = None,
    ) -> None:
        """Build a checklist of ``players`` with ``checked`` ticked.

        Args:
            title: Window title.
            players: ``(player_id, name)`` for each player, in roster order.
            checked: Ids of the players ticked to start with.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(360, 480)
        self.player_list = QListWidget(self)
        for player_id, name in players:
            item = QListWidgetItem(name, self.player_list)
            item.setData(Qt.ItemDataRole.UserRole, player_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if player_id in checked
                else Qt.CheckState.Unchecked
            )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING * 2,) * 4)
        layout.addWidget(QLabel("Players who can't play this board:", self))
        layout.addWidget(self.player_list, 1)
        layout.addWidget(buttons)

    def checked_ids(self) -> list[str]:
        """Return the ids of the ticked players, in roster order."""
        return [
            self.player_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.player_list.count())
            if self.player_list.item(row).checkState() == Qt.CheckState.Checked
        ]


def choose_cant_play(
    title: str,
    players: RosterPlayers,
    checked: Sequence[str],
    parent: QWidget | None = None,
) -> list[str] | None:
    """Ask the host which players can't play a board.

    Args:
        title: Window title.
        players: ``(player_id, name)`` for each player, in roster order.
        checked: Ids of the players who can't play it now.
        parent: Parent for the dialog.

    Returns:
        The ticked player ids, or ``None`` if the host cancelled.
    """
    dialog = PlayerChecklistDialog(title, players, checked, parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.checked_ids()
    return None


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
        choose_cant_play: Callable[
            [str, RosterPlayers, Sequence[str], QWidget | None], list[str] | None
        ] = choose_cant_play,
    ) -> None:
        """Build the games table and the unassigned pool.

        Args:
            parent: Optional parent widget.
            pick_board: Asks the host for a board, given what it is for and
                the current board; returns ``None`` if cancelled. Tests pass
                a fake.
            missing_media: Returns a board's source ids without question
                media; tests pass a fake.
            choose_cant_play: Asks the host which players can't play a
                board; returns ``None`` if cancelled. Tests pass a fake.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.pick_board = pick_board
        self.missing_media = missing_media
        self.choose_cant_play = choose_cant_play
        self.boards: dict[str, TournamentBoard] = {}
        self.unassigned: list[TournamentBoard] = []
        self._players: list[tuple[str, str]] = []
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
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)

        self.set_board_button = QPushButton("Set Board...", self)
        self.set_board_button.setToolTip(
            "Choose or edit the selected game's board. With no game selected,"
            " the new board goes to Unassigned. Double-clicking a game does"
            " the same as selecting it and clicking here."
        )
        self.set_board_button.clicked.connect(self.set_selected_board)
        self.cant_play_button = QPushButton("Can't Play...", self)
        self.cant_play_button.setToolTip(
            "Choose players who must not play the selected game's board, for"
            " example because they've seen it. They stay with the board if it"
            " moves. Double-clicking the Can't Play cell does the same."
        )
        self.cant_play_button.clicked.connect(self.set_selected_cant_play)
        self.swap_button = QPushButton("Swap Boards", self)
        self.swap_button.setToolTip("Swap the boards of the two selected games.")
        self.swap_button.clicked.connect(self.swap_selected)
        self.unassign_button = QPushButton("Unassign", self)
        self.unassign_button.setToolTip(
            "Move the selected games' boards to Unassigned."
        )
        self.unassign_button.clicked.connect(self.unassign_selected)
        game_buttons = QHBoxLayout()
        for button in (
            self.set_board_button,
            self.cant_play_button,
            self.swap_button,
            self.unassign_button,
        ):
            game_buttons.addWidget(button)
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

    def set_players(self, players: RosterPlayers) -> None:
        """Set the roster players offered for Can't Play, and show their names.

        Args:
            players: ``(player_id, name)`` for each named player, in roster
                order.

        Returns:
            ``None``.
        """
        self._players = list(players)
        self._redraw()

    def selected_keys(self) -> list[str]:
        """Return the keys of the selected games, in playing order."""
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [
            self._game_keys[row] for row in sorted(rows) if row < len(self._game_keys)
        ]

    def set_selected_board(self) -> None:
        """Set the selected game's board, or add a board to the pool.

        Returns:
            ``None``.
        """
        keys = self.selected_keys()
        if not keys:
            self.add_pool_board()
        elif len(keys) == 1:
            self.set_board(keys[0])

    def on_cell_double_clicked(self, row: int, column: int) -> None:
        """Edit the Can't Play players or the board of the game in ``row``.

        Args:
            row: Table row.
            column: Clicked column; the Can't Play column edits exclusions,
                any other edits the board.

        Returns:
            ``None``.
        """
        if not 0 <= row < len(self._game_keys):
            return
        key = self._game_keys[row]
        if column == COLUMN_CANT_PLAY and key in self.boards:
            self.set_cant_play(key)
        else:
            self.set_board(key)

    def set_board(self, key: str) -> None:
        """Ask the host for a game's board and store it.

        Editing a game's board replaces it, keeping who can't play it. A
        cancelled pick changes nothing.

        Args:
            key: The game's key.

        Returns:
            ``None``.
        """
        previous = self.boards.get(key)
        board = self.pick_board(key, previous, self)
        if board is None:
            return
        # An edit replaces the old version instead of keeping it in the pool.
        self.boards = {**self.boards, key: edited_board(previous, board)}
        self._changed()

    def add_pool_board(self) -> None:
        """Ask the host for a new board and add it to the pool.

        Returns:
            ``None``.
        """
        board = self.pick_board(NEW_POOL_BOARD_TARGET, None, self)
        if board is None:
            return
        self.unassigned = [*self.unassigned, board]
        self._changed()

    def set_selected_cant_play(self) -> None:
        """Choose who can't play the selected game's board.

        Returns:
            ``None``.
        """
        keys = self.selected_keys()
        if len(keys) == 1 and keys[0] in self.boards:
            self.set_cant_play(keys[0])

    def set_cant_play(self, key: str) -> None:
        """Ask the host who can't play a game's board, and store it.

        Args:
            key: The game's key; the game must have a board.

        Returns:
            ``None``.
        """
        board = self.boards[key]
        chosen = self.choose_cant_play(
            f"Can't Play: {key}", self._players, board.cant_play, self
        )
        if chosen is None:
            return
        self.boards = {**self.boards, key: with_cant_play(board, chosen)}
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

    def cant_play_text(self, board: TournamentBoard) -> str:
        """Return the names of the roster players who can't play ``board``."""
        names = dict(self._players)
        return ", ".join(
            names[player_id] for player_id in board.cant_play if player_id in names
        )

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
                self.cant_play_text(board) if board is not None else "",
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
            cant_play = self.cant_play_text(board)
            self.pool_list.addItem(
                f"{board.label} (can't play: {cant_play})" if cant_play else board.label
            )
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
        # No game selected adds a board to the pool; two or more is unclear.
        self.set_board_button.setEnabled(len(keys) <= 1)
        self.cant_play_button.setEnabled(len(keys) == 1 and keys[0] in self.boards)
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
