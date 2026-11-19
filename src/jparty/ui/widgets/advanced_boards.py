"""The advanced board editor: build a board from rounds of any games.

:class:`AdvancedBoardEditor` holds one row per board slot. Each row loads a
source game (typed, or picked with Random) on a worker thread, offers that
game's matching rounds, and sets the slot's point values and Daily Doubles.
The welcome screen shows it under Advanced Options, and the tournament board
picker shows it on its own.

The editor never touches a game object. It emits :attr:`setup_changed`
whenever the rows change, and :meth:`AdvancedBoardEditor.current_setup`
returns the board they describe, as ``board_selections`` and the composed
game. Each caller decides what to do with it.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.models import GameData
from jparty.services.game_loader import (
    QUESTION_INDEX_PART_COUNT,
    advanced_standard_board_selection,
    compose_game_from_resolved_board_selections,
    default_board_row_values,
    describe_source_round,
    final_board_selection,
    get_game,
    round_matches_board_type,
)
from jparty.services.question_media import (
    detect_question_media,
    import_question_media,
)
from jparty.ui.board_sources import (
    ADVANCED_RANDOM_MAX_ATTEMPTS,
    composed_board_summary_text,
    composed_session_game_id,
    find_random_game_with_media,
    random_game_failure_text,
    source_game_summary_text,
)
from jparty.ui.welcome_loader import LatestRequest, WelcomeLoader
from jparty.ui.widgets.common import DynamicButton, choose_question_media_path

ADVANCED_BOARD_SLOT_COUNT_MIN = 1
ADVANCED_BOARD_SLOT_COUNT_MAX = 5
ADVANCED_STANDARD_VALUE_COUNT = 5
ADVANCED_FINAL_BOARD_SLOT_COUNT_MIN = 0
ADVANCED_DAILY_DOUBLE_COUNT_MIN = 0
ADVANCED_DAILY_DOUBLE_COUNT_MAX = 6
ADVANCED_ROW_DEBOUNCE_MS = 2000
DEFAULT_STANDARD_BOARD_COUNT = 2
DEFAULT_FINAL_BOARD_COUNT = 1


@dataclass(frozen=True)
class AdvancedBoardSetup:
    """The board the advanced rows describe.

    Attributes:
        board_selections: A ``board_selections`` entry for each row that is
            ready, in play order.
        slot_count: Number of rows.
        composed_data: The game composed from every row, or ``None`` until
            every row is ready.
        requested_daily_double_counts: Daily Doubles asked for on each ready
            standard row, in order.
    """

    board_selections: tuple[dict, ...]
    slot_count: int
    composed_data: GameData | None = None
    requested_daily_double_counts: tuple[int, ...] = ()

    @property
    def complete(self) -> bool:
        """Return whether every row is ready."""
        return len(self.board_selections) == self.slot_count

    @property
    def ready(self) -> bool:
        """Return whether every row is ready and the game was composed."""
        return self.complete and self.composed_data is not None

    @property
    def session_game_id(self) -> str:
        """Return the save and log id for this board, or ``""``."""
        return composed_session_game_id(list(self.board_selections))

    def summary_text(self) -> str:
        """Return the composed board's summary, or ``""`` until it is ready."""
        if not self.ready:
            return ""
        return composed_board_summary_text(
            list(self.board_selections),
            self.composed_data,
            list(self.requested_daily_double_counts),
        )


def snapshots_from_board_selections(
    board_selections: Sequence[dict],
) -> dict[str, list[dict]]:
    """Return row snapshots that show saved board selections for editing.

    Args:
        board_selections: ``board_selections`` entries, in play order.

    Returns:
        Row snapshots, grouped like :meth:`AdvancedBoardEditor.snapshot_rows`.
    """
    snapshots: dict[str, list[dict]] = {"standard": [], "final": []}
    for selection in board_selections:
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


def expected_board_type_label(board_type: str) -> str:
    """Return the host-facing name of a board slot type."""
    return "Final Jeopardy board" if board_type == "final" else "Jeopardy board"


class AdvancedBoardEditor(QWidget):
    """Board-slot rows that build a board from rounds of any games.

    Attributes:
        rows: One dictionary per row, standard boards first, holding its
            widgets and load state.
        standard_board_count_spinbox: Number of Jeopardy board rows.
        final_board_count_spinbox: Number of Final Jeopardy rows.
        header_layout: The row with the board counts; callers may add
            widgets with :meth:`add_header_widget`.
        scroll: Scroll area holding the rows.
    """

    setup_changed = pyqtSignal()
    # (row_index, request_id, game_id, data, media_status)
    row_load_result_trigger = pyqtSignal(int, int, object, object, object)
    row_random_result_trigger = pyqtSignal(int, int, object, object, object)

    def __init__(
        self,
        parent: QWidget | None = None,
        run_async: Callable[[Callable[[], None]], object] | None = None,
        choose_media_path: Callable[[], str] | None = None,
    ) -> None:
        """Build the board counts and one row per default slot.

        Args:
            parent: Optional parent widget.
            run_async: Runs a callable off the UI thread. The default uses a
                :class:`WelcomeLoader`.
            choose_media_path: Asks the host for a question-media zip or
                folder and returns its path, or ``""`` if cancelled.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.run_async = run_async or WelcomeLoader().run_async
        self.choose_media_path = choose_media_path or (
            lambda: choose_question_media_path(self)
        )
        self.rows: list[dict] = []
        self._game_cache: dict[str, object] = {}
        self._media_status_cache: dict[str, object] = {}
        # Each row tracks its newest load, with ids from this one counter so
        # a result can never match a rebuilt row.
        self._request_ids = itertools.count(1)
        self._resetting = False
        self._scale: tuple[int, int] | None = None

        self.standard_board_count_label = QLabel("Jeopardy Boards:", self)
        self.standard_board_count_spinbox = QSpinBox(self)
        self.standard_board_count_spinbox.setRange(
            ADVANCED_BOARD_SLOT_COUNT_MIN, ADVANCED_BOARD_SLOT_COUNT_MAX
        )
        self.standard_board_count_spinbox.setValue(DEFAULT_STANDARD_BOARD_COUNT)
        self.standard_board_count_spinbox.valueChanged.connect(self.rebuild_rows)
        self.final_board_count_label = QLabel("Final Boards:", self)
        self.final_board_count_spinbox = QSpinBox(self)
        self.final_board_count_spinbox.setRange(
            ADVANCED_FINAL_BOARD_SLOT_COUNT_MIN, ADVANCED_BOARD_SLOT_COUNT_MAX
        )
        self.final_board_count_spinbox.setValue(DEFAULT_FINAL_BOARD_COUNT)
        self.final_board_count_spinbox.valueChanged.connect(self.rebuild_rows)
        self.header_layout = QHBoxLayout()
        self.header_layout.addWidget(self.standard_board_count_label)
        self.header_layout.addWidget(self.standard_board_count_spinbox)
        self.header_layout.addSpacing(20)
        self.header_layout.addWidget(self.final_board_count_label)
        self.header_layout.addWidget(self.final_board_count_spinbox)
        self.header_layout.addSpacing(20)
        self.header_layout.addStretch(1)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.rows_widget = QWidget(self.scroll)
        # Don't stretch the rows to fill a tall scroll area; their auto-sized
        # buttons would grow with them.
        self.rows_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rows_widget.setLayout(self.rows_layout)
        self.scroll.setWidget(self.rows_widget)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.header_layout)
        layout.addWidget(self.scroll)

        self.row_load_result_trigger.connect(self.handle_row_load_result)
        self.row_random_result_trigger.connect(self.handle_row_random_result)
        self.rebuild_rows()

    def add_header_widget(self, widget: QWidget) -> None:
        """Add ``widget`` after the board counts, such as a Start button.

        Args:
            widget: Widget to add.

        Returns:
            ``None``.
        """
        # Keep the trailing stretch last.
        self.header_layout.insertWidget(self.header_layout.count() - 1, widget)

    def current_setup(self) -> AdvancedBoardSetup:
        """Return the board the rows describe, and refresh each row's summary.

        A standard row keeps the Daily Doubles chosen for it, so asking again
        doesn't move them.

        Returns:
            The board selections of the ready rows and, once every row is
            ready, the composed game.
        """
        board_selections = []
        resolved_boards = []
        requested_daily_double_counts = []
        for row in self.rows:
            game_id = row["gameid_edit"].text().strip()
            if not game_id or row["loaded_data"] is None:
                continue
            selected_round_index = self._selected_source_round(row)
            if selected_round_index is None:
                continue
            try:
                row_values = [int(edit.text()) for edit in row["value_edits"]]
            except ValueError:
                row["status_label"].setText(
                    "Point values must be whole numbers for this board slot."
                )
                continue
            source_round_label = describe_source_round(
                row["loaded_data"], selected_round_index
            )
            source_round = row["loaded_data"].rounds[selected_round_index]
            media_status = self._media_status_cache.get(game_id)
            row["status_label"].setText(
                "\n\n".join(
                    text
                    for text in [
                        source_game_summary_text(
                            game_id,
                            row["loaded_data"],
                            media_status,
                            selected_round_index=selected_round_index,
                        ),
                        row["notice"],
                    ]
                    if text
                )
            )
            if row["board_type"] == "final":
                selection = final_board_selection(
                    game_id, selected_round_index, source_round_label
                )
            else:
                existing_daily_double_indices = (
                    row.get("daily_double_indices")
                    if row.get("daily_double_source_round_index")
                    == selected_round_index
                    else None
                )
                requested_daily_double_count = row["daily_double_spinbox"].value()
                selection = advanced_standard_board_selection(
                    game_id,
                    source_round,
                    selected_round_index,
                    source_round_label,
                    row_values,
                    requested_daily_double_count,
                    existing_daily_double_indices=existing_daily_double_indices,
                )
                row["daily_double_indices"] = [
                    tuple(index) for index in selection["daily_double_indices"]
                ]
                row["daily_double_source_round_index"] = selected_round_index
                requested_daily_double_counts.append(requested_daily_double_count)
            board_selections.append(selection)
            resolved_boards.append((selection, row["loaded_data"], source_round))
        complete = len(board_selections) == len(self.rows)
        return AdvancedBoardSetup(
            board_selections=tuple(board_selections),
            slot_count=len(self.rows),
            # A partial board set is never a playable game.
            composed_data=(
                compose_game_from_resolved_board_selections(resolved_boards)
                if complete
                else None
            ),
            requested_daily_double_counts=tuple(requested_daily_double_counts),
        )

    def show_board_selections(self, board_selections: Sequence[dict]) -> None:
        """Set the rows to show saved board selections, for editing.

        Each row loads its source game again, from the cache when it can,
        and then re-applies its round, values, and Daily Doubles.

        Args:
            board_selections: ``board_selections`` entries, in play order.

        Returns:
            ``None``.
        """
        snapshots = snapshots_from_board_selections(board_selections)
        for spinbox, rows in (
            (self.standard_board_count_spinbox, snapshots["standard"]),
            (self.final_board_count_spinbox, snapshots["final"]),
        ):
            spinbox.setValue(max(spinbox.minimum(), min(len(rows), spinbox.maximum())))
        self.restore_rows(snapshots)

    def fill_all_slots(self, game_id: str) -> None:
        """Use one source game for every row.

        Each row loads it right away (this is a button, not typing) and
        picks its matching round, so a whole game can be played as it aired.

        Args:
            game_id: Source game id.

        Returns:
            ``None``.
        """
        for row in self.rows:
            # Block signals so setting the text doesn't start the typing
            # debounce; the row loads now instead.
            row["gameid_edit"].blockSignals(True)
            row["gameid_edit"].setText(game_id.strip())
            row["gameid_edit"].blockSignals(False)
            row["notice"] = ""
            self.reload_row(row["index"])

    def reset(self) -> None:
        """Clear every row and go back to the default board counts.

        Returns:
            ``None``.
        """
        self._resetting = True
        self._game_cache = {}
        self._media_status_cache = {}
        self.standard_board_count_spinbox.setValue(DEFAULT_STANDARD_BOARD_COUNT)
        self.final_board_count_spinbox.setValue(DEFAULT_FINAL_BOARD_COUNT)
        self.rebuild_rows()
        self._resetting = False

    def apply_scale(self, height: int, width: int) -> None:
        """Size fonts and fields for a screen of ``height`` by ``width``.

        Args:
            height: Height of the screen the editor is shown on.
            width: Its width.

        Returns:
            ``None``.
        """
        self._scale = (height, width)
        self._restyle()

    def rebuild_rows(self, _: object = None) -> None:
        """Recreate the rows for the chosen board counts, keeping their entries."""
        row_snapshots = (
            {"standard": [], "final": []} if self._resetting else self.snapshot_rows()
        )
        for old_row in self.rows:
            # A row Random's worker checks its own row's request id, so this
            # stops it before its next fetch.
            old_row["load_timer"].stop()
            old_row["request"].cancel()
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.rows = []
        standard_board_count = self.standard_board_count_spinbox.value()
        final_board_count = self.final_board_count_spinbox.value()
        for board_index in range(standard_board_count):
            self._add_row(
                board_index=board_index,
                board_count=standard_board_count,
                board_type="standard",
                display_index=board_index + 1,
            )
        for board_index in range(final_board_count):
            self._add_row(
                board_index=board_index,
                board_count=final_board_count,
                board_type="final",
                display_index=board_index + 1,
            )
        self.restore_rows(row_snapshots)
        self._restyle()
        self.setup_changed.emit()

    def snapshot_rows(self) -> dict[str, list[dict]]:
        """Return the current row entries grouped by slot type."""
        snapshots = {"standard": [], "final": []}
        for row in self.rows:
            board_type = row["board_type"]
            snapshots.setdefault(board_type, []).append(
                {
                    "game_id": row["gameid_edit"].text(),
                    # Untouched defaults are left out so the new board count's
                    # ladder applies to them.
                    "values": [
                        None if edit.text() == str(default) else edit.text()
                        for edit, default in zip(
                            row["value_edits"], row["default_values"], strict=False
                        )
                    ],
                    "daily_double_count": (
                        row["daily_double_spinbox"].value()
                        if row.get("daily_double_spinbox") is not None
                        else None
                    ),
                    **self.row_selection(row),
                }
            )
        return snapshots

    def restore_rows(self, snapshots: dict[str, list[dict]]) -> None:
        """Put snapshot entries back into the rows, in order per slot type."""
        row_positions = {"standard": 0, "final": 0}
        for row in self.rows:
            board_type = row["board_type"]
            snapshot_list = snapshots.get(board_type, [])
            position = row_positions.get(board_type, 0)
            row_positions[board_type] = position + 1
            if position >= len(snapshot_list):
                continue
            snapshot = snapshot_list[position]
            row["gameid_edit"].setText(snapshot.get("game_id", ""))
            if row.get("daily_double_spinbox") is not None:
                daily_double_count = snapshot.get("daily_double_count")
                if daily_double_count is not None:
                    row["daily_double_spinbox"].setValue(int(daily_double_count))
            for value_edit, value in zip(
                row["value_edits"], snapshot.get("values", [])
            ):
                if value is not None:
                    value_edit.setText(value)
            if row["gameid_edit"].text().strip():
                # Loading clears the row, so the round and Daily Doubles are
                # re-applied once the source game is back.
                self.reload_row(row["index"], snapshot)

    def row_selection(self, row: dict) -> dict:
        """Return one row's selected round and Daily Double layout.

        Args:
            row: Row state.

        Returns:
            A dictionary that :meth:`reload_row` can re-apply.
        """
        return {
            "selected_round_index": self._selected_source_round(row),
            "daily_double_indices": [
                list(index) for index in row.get("daily_double_indices", [])
            ],
            "daily_double_source_round_index": row.get(
                "daily_double_source_round_index"
            ),
        }

    def reload_row(self, row_index: int, selection: object = None) -> None:
        """Load one row's source game again on a worker thread.

        Args:
            row_index: Index of the row.
            selection: Optional result of :meth:`row_selection` (or a row
                snapshot) to re-apply once the game has loaded, so the row
                keeps its round and Daily Doubles.

        Returns:
            ``None``.
        """
        if not 0 <= row_index < len(self.rows):
            return
        row = self.rows[row_index]
        row["load_timer"].stop()
        self._clear_row_loaded_state(row)
        row["pending_selection"] = selection
        self.load_row_async(row_index)
        # The row is empty until its load finishes, so the board must stop
        # being ready now rather than wait for the next change.
        self.setup_changed.emit()

    def refresh_row(self, row_index: int) -> None:
        """Load one row's source game now (Enter key).

        Skips the debounce. The load runs on a worker thread unless the game
        is already cached.
        """
        if 0 <= row_index < len(self.rows):
            self.rows[row_index]["notice"] = ""
        self.reload_row(row_index)

    def load_row_async(self, row_index: int) -> None:
        """Load one row's source game on a worker thread."""
        if not 0 <= row_index < len(self.rows):
            return
        row = self.rows[row_index]
        game_id = row["gameid_edit"].text().strip()
        if not game_id:
            row["status_label"].setText("Enter a source game id.")
            self.setup_changed.emit()
            return
        request_id = row["request"].begin()
        row["loading"] = True
        row["status_label"].setText("Loading...")
        if game_id in self._game_cache and game_id in self._media_status_cache:
            row["loading"] = False
            self._apply_row_loaded_data(
                row_index,
                game_id,
                self._game_cache.get(game_id),
                self._media_status_cache.get(game_id),
            )
            return

        def _load() -> None:
            # The worker only computes; the UI thread caches the result.
            data = None
            try:
                data = get_game(game_id)
            except Exception as exc:
                logging.error(exc)
            media_status = detect_question_media(game_id)
            self.row_load_result_trigger.emit(
                row_index, request_id, game_id, data, media_status
            )

        self.run_async(_load)

    def handle_row_load_result(
        self,
        row_index: int,
        request_id: int,
        game_id: object,
        data: object,
        media_status: object,
    ) -> None:
        """Apply one row's load result if it is still current."""
        if not 0 <= row_index < len(self.rows):
            return
        row = self.rows[row_index]
        if not row["request"].is_current(request_id):
            return
        if str(game_id).strip() != row["gameid_edit"].text().strip():
            return
        row["loading"] = False
        self._cache_game(str(game_id).strip(), data, media_status)
        self._apply_row_loaded_data(row_index, str(game_id).strip(), data, media_status)

    def random_row(self, row_index: int, checked: object = False) -> None:
        """Load a random source game into one row on a worker thread.

        The worker tries at most ``ADVANCED_RANDOM_MAX_ATTEMPTS`` games and
        stops early once a newer load for the row has started. If every try
        fails, the game the row had loaded before is restored (see
        :meth:`handle_row_random_result`).
        """
        if not 0 <= row_index < len(self.rows):
            return
        row = self.rows[row_index]
        row["load_timer"].stop()
        previous_game_id = row["gameid_edit"].text().strip()
        row["random_fallback"] = (
            (previous_game_id, self.row_selection(row))
            if previous_game_id and row.get("loaded_data") is not None
            else None
        )
        self._clear_row_loaded_state(row)
        row["notice"] = ""
        request = row["request"]
        request_id = request.begin()
        row["loading"] = True
        row["status_label"].setText("Loading...")
        self.setup_changed.emit()
        board_type = row["board_type"]

        def _load() -> None:
            game_id, data, media_status = find_random_game_with_media(
                lambda candidate: any(
                    round_matches_board_type(round_data, board_type)
                    for round_data in candidate.rounds
                ),
                lambda: not request.is_current(request_id),
                ADVANCED_RANDOM_MAX_ATTEMPTS,
            )
            if not request.is_current(request_id):
                return
            self.row_random_result_trigger.emit(
                row_index, request_id, game_id, data, media_status
            )

        self.run_async(_load)

    def handle_row_random_result(
        self,
        row_index: int,
        request_id: int,
        game_id: object,
        data: object,
        media_status: object,
    ) -> None:
        """Apply one row's Random result on the UI thread if it is still current.

        Args:
            row_index: Index of the row.
            request_id: Id the load was started with.
            game_id: Picked game id, or ``""`` when every attempt failed.
            data: Loaded game data, or ``None``.
            media_status: Local question-media status for ``game_id``.

        Returns:
            ``None``.
        """
        if not 0 <= row_index < len(self.rows):
            return
        row = self.rows[row_index]
        if not row["request"].is_current(request_id):
            return
        row["loading"] = False
        fallback = row.pop("random_fallback", None)
        game_id = str(game_id).strip()
        if not game_id:
            expected_label = expected_board_type_label(row["board_type"])
            failure_text = random_game_failure_text(
                f"random game with a {expected_label}", ADVANCED_RANDOM_MAX_ATTEMPTS
            )
            if (
                fallback is not None
                and fallback[0] == row["gameid_edit"].text().strip()
            ):
                # Put back the game the row had before Random, keeping its
                # round and Daily Doubles. It is usually cached, so this is
                # immediate; otherwise it reloads on the worker thread.
                previous_game_id, selection = fallback
                # The note stays under the row's summary until the row
                # changes, so later updates don't wipe it.
                row["notice"] = f"{failure_text} Kept game {previous_game_id}."
                self.reload_row(row_index, selection)
                return
            row["status_label"].setText(failure_text)
            self.setup_changed.emit()
            return
        self._cache_game(game_id, data, media_status)
        # Block signals so showing the picked id doesn't start a reload.
        row["gameid_edit"].blockSignals(True)
        row["gameid_edit"].setText(game_id)
        row["gameid_edit"].blockSignals(False)
        self._apply_row_loaded_data(row_index, game_id, data, media_status)

    def load_question_media(self, row_index: int, checked: object = False) -> None:
        """Import question media for one row's source game id."""
        if not 0 <= row_index < len(self.rows):
            return
        row = self.rows[row_index]
        game_id = row["gameid_edit"].text().strip()
        if not game_id:
            QMessageBox.warning(
                self,
                "Question Media",
                "Enter a game id for this advanced board before loading question media.",
            )
            return
        selected_path = self.choose_media_path()
        if not selected_path:
            return
        try:
            import_question_media(selected_path, game_id)
        except Exception as exc:
            logging.error(exc)
            QMessageBox.warning(self, "Question Media", str(exc))
            return
        # Image paths are set when the game is parsed, so drop the cached copy
        # and reload every row using this game, keeping their selections.
        self._game_cache.pop(game_id, None)
        self._media_status_cache.pop(game_id, None)
        for other_row in self.rows:
            if other_row["gameid_edit"].text().strip() == game_id:
                self.reload_row(other_row["index"], self.row_selection(other_row))

    def default_values_for_board(self, board_index: int, board_count: int) -> list[int]:
        """Return the default clue values shown for one standard row."""
        return default_board_row_values(board_index, board_count)

    def _selected_source_round(self, row: dict) -> int | None:
        """Return the source round index picked in one row.

        Args:
            row: Row state.

        Returns:
            Index into the row's source game rounds, or ``None`` when no
            round is picked (or the row has not loaded).
        """
        return next(
            (
                int(radio.property("source_round_index"))
                for radio in row["board_radios"]
                if radio.isChecked()
            ),
            None,
        )

    def _add_row(
        self, board_index: int, board_count: int, board_type: str, display_index: int
    ) -> None:
        """Create one board-slot row."""
        row_widget = QWidget(self.rows_widget)
        row_layout = QVBoxLayout()
        row_widget.setLayout(row_layout)
        title_text = (
            f"Jeopardy Board {display_index}"
            if board_type == "standard"
            else f"Final Jeopardy Board {display_index}"
        )
        title_label = QLabel(title_text, row_widget)
        row_layout.addWidget(title_label)
        controls_layout = QGridLayout()
        controls_layout.setColumnStretch(0, 0)
        controls_layout.setColumnStretch(1, 0)
        controls_layout.setColumnStretch(2, 0)
        controls_layout.setColumnStretch(3, 1)
        controls_layout.addWidget(QLabel("Game ID", row_widget), 0, 0)
        gameid_edit = QLineEdit(row_widget)
        gameid_edit.setPlaceholderText("Enter game id")
        gameid_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        controls_layout.addWidget(gameid_edit, 0, 1)
        random_button = DynamicButton("Random", row_widget)
        load_media_button = DynamicButton("Load Media", row_widget)
        controls_layout.addWidget(random_button, 0, 2)
        controls_layout.addWidget(load_media_button, 0, 3)
        value_edits = []
        default_values = []
        daily_double_spinbox = None
        if board_type == "standard":
            default_values = self.default_values_for_board(board_index, board_count)
            controls_layout.addWidget(QLabel("Point Values", row_widget), 1, 0)
            values_widget = QWidget(row_widget)
            values_layout = QHBoxLayout()
            values_layout.setContentsMargins(0, 0, 0, 0)
            values_layout.setSpacing(8)
            values_widget.setLayout(values_layout)
            for value in default_values:
                value_edit = QLineEdit(str(value), row_widget)
                value_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
                value_edit.editingFinished.connect(self.setup_changed)
                values_layout.addWidget(value_edit)
                value_edits.append(value_edit)
            controls_layout.addWidget(values_widget, 1, 1, 1, 3)
            controls_layout.addWidget(QLabel("Daily Doubles", row_widget), 2, 0)
            daily_double_spinbox = QSpinBox(row_widget)
            daily_double_spinbox.setRange(
                ADVANCED_DAILY_DOUBLE_COUNT_MIN, ADVANCED_DAILY_DOUBLE_COUNT_MAX
            )
            daily_double_spinbox.setValue(min(board_index + 1, 2))
            daily_double_spinbox.valueChanged.connect(self.setup_changed)
            controls_layout.addWidget(daily_double_spinbox, 2, 1)
        row_layout.addLayout(controls_layout)
        board_radio_widget = QWidget(row_widget)
        board_radio_layout = QHBoxLayout()
        board_radio_layout.setContentsMargins(0, 0, 0, 0)
        board_radio_widget.setLayout(board_radio_layout)
        board_radio_group = QButtonGroup(row_widget)
        board_radio_group.setExclusive(True)
        load_timer = QTimer(row_widget)
        load_timer.setSingleShot(True)
        row_layout.addWidget(board_radio_widget)
        status_label = QLabel("Enter a source game id.", row_widget)
        status_label.setWordWrap(True)
        row_layout.addWidget(status_label)
        row = {
            "index": len(self.rows),
            "board_type": board_type,
            "widget": row_widget,
            "title_label": title_label,
            "gameid_edit": gameid_edit,
            "random_button": random_button,
            "load_media_button": load_media_button,
            "value_edits": value_edits,
            "default_values": default_values,
            "daily_double_spinbox": daily_double_spinbox,
            "daily_double_indices": [],
            "daily_double_source_round_index": None,
            "board_radio_widget": board_radio_widget,
            "board_radio_layout": board_radio_layout,
            "board_radio_group": board_radio_group,
            "board_radios": [],
            "load_timer": load_timer,
            "request": LatestRequest(self._request_ids),
            "loading": False,
            "status_label": status_label,
            "loaded_data": None,
            "pending_selection": None,
            # Note kept under the row's summary until the row changes, such
            # as "Kept game X" after a failed Random.
            "notice": "",
        }
        row_index = row["index"]
        load_timer.timeout.connect(partial(self.load_row_async, row_index))
        gameid_edit.textChanged.connect(partial(self._start_row_debounce, row_index))
        gameid_edit.returnPressed.connect(partial(self.refresh_row, row_index))
        random_button.clicked.connect(partial(self.random_row, row_index))
        load_media_button.clicked.connect(partial(self.load_question_media, row_index))
        self.rows.append(row)
        self.rows_layout.addWidget(row_widget)

    def _start_row_debounce(self, row_index: int, _: object = None) -> None:
        """Debounce a row's source-game load while the host types."""
        if not 0 <= row_index < len(self.rows):
            return
        row = self.rows[row_index]
        row["load_timer"].stop()
        self._clear_row_loaded_state(row)
        row["notice"] = ""
        # Typing drops any load in flight, including a row Random.
        row["request"].cancel()
        if not row["gameid_edit"].text().strip():
            row["status_label"].setText("Enter a source game id.")
            self.setup_changed.emit()
            return
        row["load_timer"].start(ADVANCED_ROW_DEBOUNCE_MS)
        row["status_label"].setText("Loading...")
        self.setup_changed.emit()

    def _clear_row_loaded_state(self, row: dict) -> None:
        """Clear one row's loaded selection state."""
        row["loaded_data"] = None
        row["loading"] = False
        row["daily_double_indices"] = []
        row["daily_double_source_round_index"] = None
        row["pending_selection"] = None
        self._clear_row_radios(row)

    def _cache_game(self, game_id: str, data: object, media_status: object) -> None:
        """Cache a successful source-game load for reuse by other rows.

        Failed loads are not cached, so the id can be retried.

        Args:
            game_id: Source game id.
            data: Loaded game data, or ``None`` when the load failed.
            media_status: Local question-media status for ``game_id``.

        Returns:
            ``None``.
        """
        if data is None:
            return
        self._game_cache[game_id] = data
        self._media_status_cache[game_id] = media_status

    def _apply_row_loaded_data(
        self, row_index: int, game_id: str, data: object, media_status: object
    ) -> None:
        """Apply loaded game data and rebuild one row's round choices."""
        if not 0 <= row_index < len(self.rows):
            return
        row = self.rows[row_index]
        pending_selection = row.get("pending_selection") or {}
        row["pending_selection"] = None
        if data is None:
            row["notice"] = ""
            row["status_label"].setText(
                "\n".join(
                    [
                        "Cannot load game",
                        media_status.summary_text() if media_status else "",
                    ]
                ).strip()
            )
            self.setup_changed.emit()
            return
        matching_rounds = [
            (round_index, round_data)
            for round_index, round_data in enumerate(data.rounds)
            if round_matches_board_type(round_data, row["board_type"])
        ]
        if not matching_rounds:
            row["notice"] = ""
            expected_label = expected_board_type_label(row["board_type"])
            row["status_label"].setText(
                "\n".join(
                    [
                        source_game_summary_text(game_id, data, media_status),
                        "",
                        f"No {expected_label} found in this source game.",
                    ]
                ).strip()
            )
            self.setup_changed.emit()
            return
        row["loaded_data"] = data
        default_selection = min(row_index, len(matching_rounds) - 1)
        kept_round_index = pending_selection.get("selected_round_index")
        for radio_index, (round_index, _) in enumerate(matching_rounds):
            if round_index == kept_round_index:
                default_selection = radio_index
        if row.get("daily_double_spinbox") is not None and pending_selection:
            row["daily_double_indices"] = [
                tuple(index)
                for index in pending_selection.get("daily_double_indices") or []
                if isinstance(index, list | tuple)
                and len(index) == QUESTION_INDEX_PART_COUNT
            ]
            row["daily_double_source_round_index"] = pending_selection.get(
                "daily_double_source_round_index"
            )
        for radio_index, (round_index, _) in enumerate(matching_rounds):
            radio = QRadioButton(
                describe_source_round(data, round_index),
                row["board_radio_widget"],
            )
            radio.setProperty("source_round_index", round_index)
            radio.setChecked(radio_index == default_selection)
            radio.clicked.connect(self.setup_changed)
            row["board_radio_group"].addButton(radio)
            row["board_radio_layout"].addWidget(radio)
            row["board_radios"].append(radio)
        row["status_label"].setText(
            source_game_summary_text(
                game_id,
                data,
                media_status,
                selected_round_index=matching_rounds[default_selection][0],
            )
        )
        self._restyle()
        self.setup_changed.emit()

    def _clear_row_radios(self, row: dict) -> None:
        """Remove any previous round choices from one row."""
        for radio in row["board_radios"]:
            row["board_radio_group"].removeButton(radio)
        while row["board_radio_layout"].count():
            item = row["board_radio_layout"].takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        row["board_radios"] = []

    def _restyle(self) -> None:
        """Apply the fonts and widths for the last :meth:`apply_scale` size."""
        if self._scale is None:
            return
        height, width = self._scale
        heading_font_size = max(int(height * 0.024), 18)
        status_font_size = max(int(height * 0.018), 14)
        value_font_size = max(int(height * 0.02), 14)
        gameid_width = min(max(int(width * 0.18), 180), 260)
        action_width = min(max(int(width * 0.11), 130), 180)
        value_width = min(max(int(width * 0.055), 60), 85)
        heading_style = (
            f"QLabel {{ color: black; font-size: {heading_font_size}px;"
            " font-weight: 700; }"
        )
        count_style = (
            f"QSpinBox {{ font-size: {heading_font_size}px;"
            f" min-height: {heading_font_size + 10}px; }}"
        )
        for label in (self.standard_board_count_label, self.final_board_count_label):
            label.setStyleSheet(heading_style)
        for spinbox in (
            self.standard_board_count_spinbox,
            self.final_board_count_spinbox,
        ):
            spinbox.setStyleSheet(count_style)
        for row in self.rows:
            row["title_label"].setStyleSheet(heading_style)
            row["status_label"].setStyleSheet(
                f"QLabel {{ color: #333333; font-size: {status_font_size}px; }}"
            )
            row["gameid_edit"].setStyleSheet(
                f"QLineEdit {{ font-size: {value_font_size}px; }}"
            )
            row["gameid_edit"].setMinimumWidth(gameid_width)
            row["gameid_edit"].setMaximumWidth(gameid_width)
            for button in (row["random_button"], row["load_media_button"]):
                button.setMinimumWidth(action_width)
                button.setMaximumWidth(action_width)
            for value_edit in row["value_edits"]:
                value_edit.setStyleSheet(
                    f"QLineEdit {{ font-size: {value_font_size}px;"
                    f" min-width: {value_width}px; }}"
                )
                value_edit.setMaximumWidth(value_width)
            if row["daily_double_spinbox"] is not None:
                row["daily_double_spinbox"].setStyleSheet(
                    f"QSpinBox {{ font-size: {value_font_size}px;"
                    f" min-height: {value_font_size + 10}px; }}"
                )
            for button in row["board_radios"]:
                button.setStyleSheet(
                    f"QRadioButton {{ color: black; font-size: {status_font_size}px;"
                    " font-weight: 600; }"
                )
