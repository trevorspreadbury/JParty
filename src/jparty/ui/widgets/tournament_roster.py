"""Tournament roster dialogs.

:class:`TournamentRosterDialog` creates or edits a tournament's roster from
its Google Form sign-up sheet. :class:`SignUpMatchDialog` steps the host
through placing new sign-ups after a refresh. Roster rules live in
:mod:`jparty.domain.roster`; files live in :mod:`jparty.domain.tournament_store`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from html import escape
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyleFactory,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.roster import (
    MATCH_ADD_PLAYER,
    MATCH_IGNORE,
    PlayerSlot,
    RosterError,
    SignUp,
    SignUpMatch,
    apply_matches,
    fill_blank_slots,
    new_sign_ups,
    open_slots,
    parse_sign_up_sheet,
    suggest_matches,
    update_linked_sign_ups,
)
from jparty.domain.tournament import MAX_TOURNAMENT_PLAYERS, MIN_TOURNAMENT_PLAYERS
from jparty.domain.tournament_store import (
    TournamentFileError,
    TournamentSettings,
    save_tournament,
    tournament_name_problem,
)
from jparty.services.game_sources import GameSourceFetcher, SheetAccessError
from jparty.ui.welcome_loader import WelcomeLoader

LAYOUT_SPACING = 8
DEFAULT_ROSTER_PLAYERS = 15
COLUMN_SLOT = 0
COLUMN_ACTUAL_NAME = 1
COLUMN_FULL_NAME = 2
COLUMN_OCCUPATION = 3
COLUMN_HOMETOWN = 4
TABLE_HEADERS = ("#", "Actual Name", "Full Name (sheet)", "Occupation", "Hometown")
PROBLEM_STYLE = "QLabel { color: #b00020; }"


class TournamentRosterDialog(QDialog):
    """Dialog to create a tournament, or edit a saved one's roster.

    Attributes:
        settings: Settings for the tournament being edited.
        slots: The roster as currently shown.
        saved_folder: The tournament folder once saved, else ``None``.
    """

    sheet_result_trigger = pyqtSignal(int, object, object)

    def __init__(
        self,
        root: Path,
        parent: QWidget | None = None,
        settings: TournamentSettings | None = None,
        slots: Sequence[PlayerSlot] | None = None,
        fetcher: GameSourceFetcher | None = None,
        run_async: Callable[[Callable[[], None]], object] | None = None,
    ) -> None:
        """Build the dialog for a new tournament or a loaded one.

        Args:
            root: The tournaments folder.
            parent: Optional parent widget.
            settings: A loaded tournament's settings, or ``None`` to create
                a new tournament.
            slots: A loaded tournament's roster.
            fetcher: Sheet fetcher; tests pass a fake.
            run_async: Runs a callable off the UI thread; tests pass one that
                runs it inline.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.root = Path(root)
        self.creating = settings is None
        self.settings = settings or TournamentSettings(name="")
        self.slots: list[PlayerSlot] = list(slots or [])
        if self.creating and not self.slots:
            self.slots = [PlayerSlot() for _ in range(DEFAULT_ROSTER_PLAYERS)]
        self.fetcher = fetcher or GameSourceFetcher()
        self.run_async = run_async or WelcomeLoader().run_async
        self.saved_folder: Path | None = None
        self._sheet_request = 0
        self._filling_table = False

        self.setWindowTitle(
            "Create Tournament"
            if self.creating
            else f"Tournament Players: {self.settings.name}"
        )
        self.resize(950, 650)

        self.name_edit = QLineEdit(self.settings.name, self)
        self.name_edit.setPlaceholderText("e.g. Family Fun 2026")
        self.name_edit.setReadOnly(not self.creating)
        self.sheet_edit = QLineEdit(self.settings.sheet_url, self)
        self.sheet_edit.setPlaceholderText(
            "https://docs.google.com/spreadsheets/d/.../edit"
        )
        self.sheet_edit.setToolTip(
            "The Google Form response sheet. Share it so anyone with the link"
            " can view it."
        )
        self.refresh_button = QPushButton("Refresh Sheet", self)
        self.refresh_button.clicked.connect(self.refresh_sheet)
        sheet_layout = QHBoxLayout()
        sheet_layout.addWidget(self.sheet_edit, 1)
        sheet_layout.addWidget(self.refresh_button)

        self.player_spinbox = QSpinBox(self)
        self.player_spinbox.setRange(MIN_TOURNAMENT_PLAYERS, MAX_TOURNAMENT_PLAYERS)
        self.player_spinbox.setValue(max(len(self.slots), MIN_TOURNAMENT_PLAYERS))
        self.player_spinbox.setToolTip(
            "Can be more than the sheet has rows. Type the names of players who"
            " haven't signed up yet."
        )
        self.player_spinbox.valueChanged.connect(self.set_player_count)

        form = QFormLayout()
        form.setSpacing(LAYOUT_SPACING)
        form.addRow("Tournament name:", self.name_edit)
        form.addRow("Sign-up sheet:", sheet_layout)
        form.addRow("Players:", self.player_spinbox)

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)

        self.table = QTableWidget(0, len(TABLE_HEADERS), self)
        self.table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            COLUMN_SLOT, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.itemChanged.connect(self.on_item_changed)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(LAYOUT_SPACING)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING * 2,) * 4)
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.buttons)

        self.sheet_result_trigger.connect(self.handle_sheet_result)
        self.set_player_count(self.player_spinbox.value())

    def set_player_count(self, count: int) -> None:
        """Add blank slots, or drop trailing blank slots, to reach ``count``.

        Slots with a name or sign-up are never dropped, so the count can't
        go below the last filled slot.

        Args:
            count: Requested number of player slots.

        Returns:
            ``None``.
        """
        while len(self.slots) < count:
            self.slots.append(PlayerSlot())
        while len(self.slots) > count and self.slots[-1].blank:
            self.slots.pop()
        self._sync_player_spinbox()
        self._fill_table()

    def on_item_changed(self, item: QTableWidgetItem) -> None:
        """Store an edited Actual Name in its slot.

        Args:
            item: The edited table cell.

        Returns:
            ``None``.
        """
        if self._filling_table or item.column() != COLUMN_ACTUAL_NAME:
            return
        row = item.row()
        if 0 <= row < len(self.slots):
            slot = self.slots[row]
            self.slots[row] = PlayerSlot(item.text().strip(), slot.sign_up)
            self._sync_player_spinbox()

    def refresh_sheet(self) -> None:
        """Fetch the sign-up sheet in the background.

        Returns:
            ``None``.
        """
        link = self.sheet_edit.text().strip()
        if not link:
            self._show_status("Paste the link to the sign-up sheet first.", True)
            return
        self._sheet_request += 1
        request = self._sheet_request
        self.refresh_button.setEnabled(False)
        self._show_status("Fetching the sign-up sheet...")
        logging.info("Fetching tournament sign-up sheet")

        def work() -> None:
            """Fetch and parse the sheet, then hand the result to the UI."""
            try:
                sign_ups = parse_sign_up_sheet(
                    self.fetcher.get_sheet_rows_from_link(link)
                )
            except (RosterError, SheetAccessError) as exc:
                self.sheet_result_trigger.emit(request, None, str(exc))
            except Exception as exc:  # network errors vary by platform
                logging.warning("Couldn't fetch sign-up sheet: %s", exc)
                self.sheet_result_trigger.emit(
                    request,
                    None,
                    "Couldn't reach the sign-up sheet. Check the link and your"
                    " connection.",
                )
            else:
                self.sheet_result_trigger.emit(request, sign_ups, None)

        self.run_async(work)

    def handle_sheet_result(
        self, request: int, sign_ups: list[SignUp] | None, error: str | None
    ) -> None:
        """Merge a fetched sheet into the roster, asking about new sign-ups.

        Args:
            request: Id of the fetch, so a stale result is dropped.
            sign_ups: Parsed rows, or ``None`` on error.
            error: Message for the host, or ``None`` on success.

        Returns:
            ``None``.
        """
        if request != self._sheet_request:
            return
        self.refresh_button.setEnabled(True)
        if error is not None or sign_ups is None:
            self._show_status(error or "Couldn't read the sign-up sheet.", True)
            return
        self.settings.sheet_url = self.sheet_edit.text().strip()
        self.slots = update_linked_sign_ups(self.slots, sign_ups)
        unplaced = new_sign_ups(self.slots, sign_ups, self.settings.ignored_sign_ups)
        self.slots, remaining = fill_blank_slots(self.slots, unplaced)
        placed = len(unplaced) - len(remaining)
        if remaining:
            dialog = SignUpMatchDialog(
                self.slots,
                suggest_matches(self.slots, remaining, sign_ups),
                open_slots(self.slots, sign_ups),
                self,
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.slots, ignored = apply_matches(self.slots, dialog.choices())
                self.settings.ignored_sign_ups.extend(ignored)
                placed += len(remaining) - len(ignored)
                remaining = []
        self._sync_player_spinbox()
        self._fill_table()
        message = f"Found {len(sign_ups)} sign-ups. {placed} new."
        if remaining:
            message += f" {len(remaining)} not placed yet; refresh again to place them."
        self._show_status(message)

    def save(self) -> None:
        """Check the roster and save the tournament folder.

        Returns:
            ``None``.
        """
        name = self.name_edit.text()
        problem = tournament_name_problem(name)
        if problem is None and self.creating and (self.root / name).exists():
            problem = f'A tournament named "{name}" already exists.'
        if problem is None:
            problem = duplicate_name_problem(self.slots)
        if problem:
            self._show_status(problem, True)
            return
        self.settings.name = name
        self.settings.sheet_url = self.sheet_edit.text().strip()
        try:
            self.saved_folder = save_tournament(self.root, self.settings, self.slots)
        except (OSError, TournamentFileError) as exc:
            QMessageBox.warning(self, "Couldn't save tournament", str(exc))
            return
        logging.info("Saved tournament %s", name)
        self.accept()

    def _sync_player_spinbox(self) -> None:
        """Match the player count to the roster and keep filled slots."""
        filled = max(
            (index + 1 for index, slot in enumerate(self.slots) if not slot.blank),
            default=0,
        )
        self.player_spinbox.blockSignals(True)
        self.player_spinbox.setMinimum(max(MIN_TOURNAMENT_PLAYERS, filled))
        self.player_spinbox.setMaximum(max(MAX_TOURNAMENT_PLAYERS, len(self.slots)))
        self.player_spinbox.setValue(len(self.slots))
        self.player_spinbox.blockSignals(False)

    def _fill_table(self) -> None:
        """Redraw the table from the roster."""
        self._filling_table = True
        self.table.setRowCount(len(self.slots))
        for row, slot in enumerate(self.slots):
            sign_up = slot.sign_up
            cells = (
                str(row + 1),
                slot.actual_name,
                sign_up.full_name if sign_up else "",
                sign_up.occupation if sign_up else "",
                sign_up.hometown if sign_up else "",
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column != COLUMN_ACTUAL_NAME:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if sign_up is not None:
                    item.setToolTip(sign_up_tooltip(sign_up))
                elif column != COLUMN_ACTUAL_NAME:
                    item.setToolTip("No sign-up linked yet")
                self.table.setItem(row, column, item)
        self._filling_table = False

    def _show_status(self, message: str, problem: bool = False) -> None:
        """Show ``message`` under the form, in red for problems."""
        self.status_label.setStyleSheet(PROBLEM_STYLE if problem else "")
        self.status_label.setText(message)


class SignUpMatchDialog(QDialog):
    """Step through new sign-ups and choose a slot for each.

    Each sign-up can be linked to an open slot, added as a new player, or
    ignored. A slot can only be chosen for one sign-up.
    """

    def __init__(
        self,
        slots: Sequence[PlayerSlot],
        matches: Sequence[SignUpMatch],
        open_slot_indices: Sequence[int],
        parent: QWidget | None = None,
    ) -> None:
        """Build the dialog, starting at the first sign-up.

        Args:
            slots: Current roster.
            matches: New sign-ups with their suggested slots.
            open_slot_indices: Slots a sign-up can be linked to, including
                slots whose linked row has left the sheet.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.setWindowTitle("Match New Sign-ups")
        self.slots = list(slots)
        self.matches = list(matches)
        self.open_slot_indices = list(open_slot_indices)
        # Start from the suggestions. If two suggest the same slot, the first
        # sign-up keeps it and the later one defaults to a new player.
        self.selected: list[int | str] = []
        for match in self.matches:
            slot = match.suggested_slot
            if slot is None or slot in self.selected:
                self.selected.append(MATCH_ADD_PLAYER)
            else:
                self.selected.append(slot)
        self.position = 0

        self.progress_label = QLabel(self)
        self.sign_up_label = QLabel(self)
        self.sign_up_label.setTextFormat(Qt.TextFormat.RichText)
        self.sign_up_label.setWordWrap(True)
        self.choice_combo = QComboBox(self)
        # JParty's app style can't draw combo boxes, so use Fusion for this one.
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            fusion.setParent(self.choice_combo)
            self.choice_combo.setStyle(fusion)
        self.choice_combo.activated.connect(self._remember_choice)

        self.back_button = QPushButton("Back", self)
        self.back_button.clicked.connect(self.go_back)
        self.next_button = QPushButton("Next", self)
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self.go_next)
        cancel_button = QPushButton("Cancel", self)
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(cancel_button)
        buttons.addStretch(1)
        buttons.addWidget(self.back_button)
        buttons.addWidget(self.next_button)

        layout = QVBoxLayout(self)
        layout.setSpacing(LAYOUT_SPACING)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING * 2,) * 4)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.sign_up_label)
        layout.addWidget(QLabel("This sign-up is:", self))
        layout.addWidget(self.choice_combo)
        layout.addLayout(buttons)
        self._show_position()

    def choices(self) -> list[tuple[SignUp, int | str]]:
        """Return each sign-up with the host's choice for it."""
        return [
            (match.sign_up, choice)
            for match, choice in zip(self.matches, self.selected, strict=True)
        ]

    def go_back(self) -> None:
        """Show the previous sign-up."""
        self._remember_choice()
        if self.position > 0:
            self.position -= 1
            self._show_position()

    def go_next(self) -> None:
        """Show the next sign-up, or finish after the last one."""
        self._remember_choice()
        if self.position + 1 < len(self.matches):
            self.position += 1
            self._show_position()
        else:
            self.accept()

    def _remember_choice(self, *_args: object) -> None:
        """Store the combo box's choice for the current sign-up."""
        if self.matches and self.choice_combo.currentIndex() >= 0:
            self.selected[self.position] = self.choice_combo.currentData()

    def _show_position(self) -> None:
        """Show the current sign-up and the slots still free for it."""
        if not self.matches:
            return
        match = self.matches[self.position]
        self.progress_label.setText(
            f"New sign-up {self.position + 1} of {len(self.matches)}"
        )
        self.sign_up_label.setText(sign_up_summary(match.sign_up))
        taken = {
            choice
            for position, choice in enumerate(self.selected)
            if position != self.position and isinstance(choice, int)
        }
        self.choice_combo.clear()
        for index in self.open_slot_indices:
            if index in taken:
                continue
            self.choice_combo.addItem(slot_choice_text(index, self.slots[index]), index)
        self.choice_combo.addItem("A new player (adds a slot)", MATCH_ADD_PLAYER)
        self.choice_combo.addItem("Not a player (ignore this response)", MATCH_IGNORE)
        current = self.selected[self.position]
        found = self.choice_combo.findData(current)
        if found < 0:
            found = self.choice_combo.findData(MATCH_ADD_PLAYER)
            self.selected[self.position] = MATCH_ADD_PLAYER
        self.choice_combo.setCurrentIndex(found)
        self.back_button.setEnabled(self.position > 0)
        self.next_button.setText(
            "Finish" if self.position + 1 == len(self.matches) else "Next"
        )


def slot_choice_text(index: int, slot: PlayerSlot) -> str:
    """Return how a slot reads in the match dialog's choices.

    Args:
        index: Slot index.
        slot: The slot.

    Returns:
        Text such as ``"Player 4: Jane Doe"``.
    """
    label = f"Player {index + 1}: {slot.actual_name or '(no name yet)'}"
    if slot.sign_up is not None:
        label += " (sign-up no longer in the sheet)"
    return label


def sign_up_summary(sign_up: SignUp) -> str:
    """Return rich text describing a sign-up for the match dialog."""
    lines = [f"<b>{escape(sign_up.full_name or '(no name)')}</b>"]
    details = ", ".join(part for part in (sign_up.occupation, sign_up.hometown) if part)
    if details:
        lines.append(escape(details))
    lines.append(f"<small>Signed up {escape(sign_up.timestamp)}</small>")
    return "<br>".join(lines)


def sign_up_tooltip(sign_up: SignUp) -> str:
    """Return a plain-text tooltip listing a sign-up's anecdotes."""
    anecdotes = [
        f"Anecdote #{number}: {text}"
        for number, text in enumerate(sign_up.anecdotes, start=1)
        if text
    ]
    return "\n".join([f"Signed up {sign_up.timestamp}", *anecdotes])


def duplicate_name_problem(slots: Sequence[PlayerSlot]) -> str | None:
    """Return a message if two slots share an Actual Name, else ``None``.

    Results are recorded by player name, so names must be unique.
    """
    seen: dict[str, int] = {}
    for index, slot in enumerate(slots):
        key = slot.actual_name.strip().casefold()
        if not key:
            continue
        if key in seen:
            return (
                f"Players {seen[key] + 1} and {index + 1} are both named"
                f' "{slot.actual_name}". Give each player a different name.'
            )
        seen[key] = index
    return None
