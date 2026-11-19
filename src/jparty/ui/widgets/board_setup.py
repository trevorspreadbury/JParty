"""Choose a tournament game's board with the welcome screen's board tools.

:class:`BoardSetupWidget` is the welcome screen itself, regular and Advanced
Options modes included, with the parts that only make sense for starting a
game hidden. It sets up boards in a :class:`BoardSetupSession` instead of the
real game, so choosing a tournament board never touches the game the host
may be setting up on the welcome screen. :class:`BoardPickerDialog` wraps it
with "Use This Board" and Cancel.
"""

from __future__ import annotations

from copy import deepcopy

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.tournament_setup import TournamentBoard, board_from_selections
from jparty.ui.widgets.welcome import Welcome

LAYOUT_SPACING = 8
# The welcome screen gives its game-id row 5 and summary 7; the advanced rows
# get twice the summary here.
ADVANCED_ROWS_STRETCH = 14


class BoardSetupSession:
    """Holds a board being set up, in place of the game engine.

    :class:`jparty.ui.widgets.welcome.Welcome` stores its board setup on its
    game object. This keeps the same board state as
    :class:`jparty.domain.game_engine.GameEngine`, without players, buzzers,
    or saved games.

    Attributes:
        data: The loaded or composed game, or ``None``.
    """

    def __init__(self) -> None:
        """Start with no board.

        Returns:
            ``None``.
        """
        self.data = None
        self._selected_round_indices: list[int] | None = None
        self._board_selection_configs: list[dict] | None = None
        self._composed_board_selection_configs: list[dict] | None = None
        self._composed_game_data = None
        self._session_game_id = ""

    def valid_game(self) -> bool:
        """Return whether a game with at least one round is loaded."""
        return self.data is not None and bool(self.data.rounds)

    def startable(self) -> bool:
        """Return whether the board can be used; no players are needed."""
        return self.valid_game()

    def selected_round_indices(self) -> list[int]:
        """Return the rounds picked in regular mode."""
        return list(self._selected_round_indices or [])

    def set_selected_round_indices(self, indices: object) -> None:
        """Store the rounds picked in regular mode.

        Args:
            indices: Round indices, or ``None`` to clear them.

        Returns:
            ``None``.
        """
        self._selected_round_indices = (
            None if indices is None else sorted({int(index) for index in indices})
        )

    def set_board_selection_configs(self, configs: object) -> None:
        """Store the board selections the welcome screen built.

        Args:
            configs: ``board_selections`` entries, or ``None`` to clear them.

        Returns:
            ``None``.
        """
        if configs is None:
            self._board_selection_configs = None
            self._composed_board_selection_configs = None
            self._composed_game_data = None
            return
        self._board_selection_configs = deepcopy(list(configs))
        if self._composed_board_selection_configs != self._board_selection_configs:
            self._composed_board_selection_configs = None
            self._composed_game_data = None

    def board_selection_configs(self) -> list[dict]:
        """Return a copy of the current board selections."""
        return deepcopy(self._board_selection_configs or [])

    def set_composed_game_data(
        self, configs: object, composed_game_data: object | None
    ) -> None:
        """Store the game composed from ``configs``.

        Args:
            configs: The selections the game was composed from.
            composed_game_data: The composed game.

        Returns:
            ``None``.
        """
        self._composed_board_selection_configs = (
            deepcopy(list(configs)) if configs is not None else None
        )
        self._composed_game_data = composed_game_data

    def matching_composed_game_data(self, configs: object) -> object | None:
        """Return the composed game if it was built from ``configs``."""
        normalized = deepcopy(list(configs)) if configs is not None else None
        if normalized != self._composed_board_selection_configs:
            return None
        return self._composed_game_data

    def set_session_game_id(self, game_id: object) -> None:
        """Store the board's game id.

        Args:
            game_id: Game id, or ``frankenstein-...`` for a mixed board.

        Returns:
            ``None``.
        """
        self._session_game_id = str(game_id or "").strip()

    def current_game_id(self) -> str:
        """Return the board's game id, or ``""``."""
        return self._session_game_id

    def clear_resume_state(self) -> None:
        """Forget the board setup, as the engine does for a fresh game.

        Returns:
            ``None``.
        """
        self._selected_round_indices = None
        self._board_selection_configs = None
        self._composed_board_selection_configs = None
        self._composed_game_data = None
        self._session_game_id = ""

    def start_game(self) -> None:
        """Do nothing: boards chosen here are played later, from the tournament.

        Returns:
            ``None``.
        """

    def close(self) -> None:
        """Do nothing: the dialog, not the welcome screen, closes the picker.

        Returns:
            ``None``.
        """


def board_snapshots(board: TournamentBoard) -> dict[str, list[dict]]:
    """Return advanced-row snapshots that show ``board`` for editing.

    The welcome screen restores advanced rows from these, as it does when
    the host changes the number of board slots.

    Args:
        board: A saved tournament board.

    Returns:
        Row snapshots grouped by ``"standard"`` and ``"final"``.
    """
    snapshots: dict[str, list[dict]] = {"standard": [], "final": []}
    for selection in board.board_selections:
        round_index = selection.get("source_round_index")
        snapshot = {
            "game_id": str(selection.get("game_id", "")),
            "selected_round_index": round_index,
            "values": [],
            "daily_double_count": None,
            "daily_double_indices": [],
            "daily_double_source_round_index": None,
        }
        if selection.get("board_type") == "final":
            snapshots["final"].append(snapshot)
            continue
        snapshot["values"] = [str(value) for value in selection.get("row_values", [])]
        snapshot["daily_double_count"] = selection.get("daily_double_count")
        snapshot["daily_double_indices"] = [
            list(index) for index in selection.get("daily_double_indices", [])
        ]
        snapshot["daily_double_source_round_index"] = round_index
        snapshots["standard"].append(snapshot)
    return snapshots


class BoardSetupWidget(Welcome):
    """The welcome screen's board setup, for choosing a tournament board.

    It opens in Advanced Options mode. Unchecking Advanced Options gives the
    regular one-game setup.
    """

    board_ready_changed = pyqtSignal(bool)

    def __init__(
        self, parent: QWidget | None = None, board: TournamentBoard | None = None
    ) -> None:
        """Build the board setup, showing ``board`` if one is given.

        Args:
            parent: Optional parent widget.
            board: A board to edit, or ``None`` to start empty.

        Returns:
            ``None``.
        """
        super().__init__(BoardSetupSession(), parent)
        for widget in (
            self.icon_label,
            self.title_label,
            self.version_label,
            self.start_button,
            self.advanced_start_button,
            self.resume_button,
            self.reveal_answers_radio,
            self.quit_button,
            self.help_button,
            self.tournament_button,
        ):
            widget.hide()
        self._collapse_spacers()
        self.advanced_options_checkbox.setChecked(True)
        if board is not None:
            self.show_board(board)

    def is_board_ready(self) -> bool:
        """Return whether a complete board is set up."""
        return bool(self.presenter.state.start_enabled)

    def check_start(self) -> None:
        """Update readiness and tell the dialog whether a board is ready.

        Returns:
            ``None``.
        """
        super().check_start()
        self.board_ready_changed.emit(self.is_board_ready())

    def show_board(self, board: TournamentBoard) -> None:
        """Fill the advanced rows from a saved board, so it can be edited.

        Each row loads its source game again, from the cache when it can.

        Args:
            board: The board to show.

        Returns:
            ``None``.
        """
        snapshots = board_snapshots(board)
        for spinbox, rows in (
            (self.standard_board_count_spinbox, snapshots["standard"]),
            (self.final_board_count_spinbox, snapshots["final"]),
        ):
            spinbox.setValue(max(spinbox.minimum(), min(len(rows), spinbox.maximum())))
        self.restore_advanced_rows(snapshots)

    def current_board(self) -> TournamentBoard | None:
        """Return the board set up here, or ``None`` if it isn't complete."""
        self.sync_active_configuration()
        # Regular-mode sync doesn't recompute readiness; advanced-mode sync does.
        self.check_start()
        if not self.is_board_ready():
            return None
        selections = self.game.board_selection_configs()
        if not selections:
            return None
        return board_from_selections(
            self.compose_session_game_id(selections), selections
        )

    def _collapse_spacers(self) -> None:
        """Drop the welcome screen's spacing and hidden rows.

        The game-id, summary, and round rows keep the welcome screen's
        proportions. The advanced rows get extra room, since they are the
        main tool here.
        """
        layout = self.layout()
        hidden_rows = (
            self.icon_layout,
            self.title_label,
            self.version_label,
            self.reveal_answers_radio,
        )
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if isinstance(item, QSpacerItem):
                item.changeSize(0, 0)
                layout.setStretch(index, 0)
            elif item.widget() in hidden_rows or item.layout() in hidden_rows:
                layout.setStretch(index, 0)
            elif (
                item.layout() is not None
                and item.layout().indexOf(self.quit_button) >= 0
            ):
                # The footer row: Quit, Show help, and Tournament.
                layout.setStretch(index, 0)
        layout.setStretch(
            layout.indexOf(self.advanced_controls_widget), ADVANCED_ROWS_STRETCH
        )
        layout.invalidate()


class BoardPickerDialog(QDialog):
    """Choose or edit the board for one tournament game.

    Attributes:
        board: The chosen board once accepted, else ``None``.
    """

    def __init__(
        self,
        game_key: str,
        board: TournamentBoard | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build the dialog for ``game_key``.

        Args:
            game_key: The tournament game, shown in the title.
            board: The game's current board, to edit, or ``None``.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.setWindowTitle(f"Board for {game_key}")
        self.resize(1150, 820)
        self.board: TournamentBoard | None = None
        self.setup = BoardSetupWidget(self, board)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.use_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.use_button.setText("Use This Board")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.setup.board_ready_changed.connect(self.use_button.setEnabled)
        self.use_button.setEnabled(self.setup.is_board_ready())

        layout = QVBoxLayout(self)
        layout.setSpacing(LAYOUT_SPACING)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING * 2,) * 4)
        layout.addWidget(self.setup, 1)
        layout.addWidget(self.buttons)

    def accept(self) -> None:
        """Keep the board and close, if a complete board is set up.

        Returns:
            ``None``.
        """
        board = self.setup.current_board()
        if board is None:
            self.use_button.setEnabled(False)
            return
        self.board = board
        super().accept()


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
