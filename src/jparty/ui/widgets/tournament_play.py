"""Choosing and fixing a tournament's games from the welcome screen.

:class:`TournamentPlayPanel` replaces the welcome screen's game id and round
controls while a tournament is being played. It lists the bracket's games
and the roster, and has one player picker per podium. It reads the
tournament folder but never touches a game object: it emits
:attr:`TournamentPlayPanel.selection_changed`, and the welcome screen reads
the chosen board and players from it.

:class:`TournamentResultsDialog` lets the host fix ``results.csv`` after a
game.
"""

from __future__ import annotations

import logging
from base64 import urlsafe_b64decode
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStyleFactory,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.models import SIGNATURE_NAME_PREFIX
from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament import PLAYERS_PER_GAME, TournamentPlan, plan_tournament
from jparty.domain.tournament_play import (
    RESULTS,
    Eligibility,
    GameResult,
    TournamentGameRef,
    eligible_players,
    introduction_lines,
    played_game_keys,
    played_player_ids,
    results_by_game,
    seating_problem,
    slots_by_id,
)
from jparty.domain.tournament_setup import TournamentBoard, plan_games
from jparty.domain.tournament_store import (
    TournamentFileError,
    TournamentSettings,
    load_results,
    load_tournament,
    save_results,
)

LAYOUT_SPACING = 8
PLAYED_COLOR = QColor("#8a8a8a")
PROBLEM_STYLE = "QLabel { color: #b00020; }"
PROBLEM_COLOR = "#b00020"
NO_PHONE_TEXT = "no phone yet"
SIGNED_NAME_TEXT = "signed name"
CHOOSE_PLAYER_TEXT = "Choose a player"
# A podium's signature is this many lines of text tall.
SIGNATURE_LINES = 3


def phone_label(name: object) -> str:
    """Return how a connected phone's player name is shown next to a podium.

    Args:
        name: A player's name, or ``None`` for an empty podium.

    Returns:
        The name, ``"signed name"`` for a handwritten one, or ``"no phone
        yet"``.
    """
    if name is None:
        return NO_PHONE_TEXT
    text = str(name)
    if text.startswith(SIGNATURE_NAME_PREFIX):
        return SIGNED_NAME_TEXT
    return text


def signature_pixmap(name: object) -> QPixmap | None:
    """Return a phone's handwritten name as an image, or ``None``.

    Args:
        name: A player's name, which phones send as a PNG data URL when the
            player signs it.

    Returns:
        The signature, or ``None`` if ``name`` isn't one or can't be read.
    """
    text = str(name or "")
    if not text.startswith(SIGNATURE_NAME_PREFIX):
        return None
    image = QImage()
    try:
        data = urlsafe_b64decode(text[len(SIGNATURE_NAME_PREFIX) + 1 :])
    except ValueError:
        return None
    if not image.loadFromData(data, "PNG"):
        return None
    return QPixmap.fromImage(image)


def _grey(item: QListWidgetItem) -> None:
    """Show a list item as played."""
    item.setForeground(QBrush(PLAYED_COLOR))


def _disable(item: QListWidgetItem) -> None:
    """Make a list item impossible to pick."""
    item.setFlags(
        item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled
    )


class TournamentPlayPanel(QWidget):
    """Pick a tournament game and its players.

    Attributes:
        folder: The tournament's folder, or ``None`` before :meth:`load`.
        settings: The tournament's settings.
        slots: The roster.
        results: Every saved result.
        plan: The bracket.
    """

    selection_changed = pyqtSignal()
    leave_requested = pyqtSignal()
    results_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build an empty panel; :meth:`load` fills it.

        Args:
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.folder: Path | None = None
        self.settings: TournamentSettings | None = None
        self.slots: list[PlayerSlot] = []
        self.results: list[GameResult] = []
        self.plan: TournamentPlan | None = None
        # Why the last reload failed, or None. The results shown are then
        # out of date, so no game can start until a reload works.
        self.load_error: str | None = None
        self._game_keys: list[str] = []
        self._eligibility = Eligibility()
        self._phone_names: list[object] = []
        self._font_pixels = 16

        self.title_label = QLabel(self)
        title_font = QFont()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.fix_results_button = QPushButton("Fix Results...", self)
        self.fix_results_button.setToolTip("Change a played game's scores or winner.")
        self.fix_results_button.clicked.connect(self.fix_results)
        self.leave_button = QPushButton("Leave Tournament", self)
        self.leave_button.setToolTip("Go back to choosing a regular game.")
        self.leave_button.clicked.connect(self.leave_requested)
        header = QHBoxLayout()
        header.addWidget(self.title_label, 1)
        header.addWidget(self.fix_results_button)
        header.addWidget(self.leave_button)

        self.games_list = QListWidget(self)
        self.games_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.games_list.currentRowChanged.connect(self._on_game_changed)
        self.players_list = QListWidget(self)
        self.players_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        lists = QGridLayout()
        lists.addWidget(QLabel("Games:", self), 0, 0)
        lists.addWidget(QLabel("Players:", self), 0, 1)
        lists.addWidget(self.games_list, 1, 0)
        lists.addWidget(self.players_list, 1, 1)
        lists.setColumnStretch(0, 3)
        lists.setColumnStretch(1, 2)

        podiums = QGridLayout()
        self.podium_combos: list[QComboBox] = []
        self.phone_labels: list[QLabel] = []
        # JParty's app style can't draw combo boxes, so use Fusion for them.
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            fusion.setParent(self)
        for index in range(PLAYERS_PER_GAME):
            combo = QComboBox(self)
            if fusion is not None:
                combo.setStyle(fusion)
            combo.currentIndexChanged.connect(self._on_podium_changed)
            # Names come from phones, so never read them as rich text.
            phone = QLabel(self)
            phone.setTextFormat(Qt.TextFormat.PlainText)
            podiums.addWidget(QLabel(f"Podium {index + 1}:", self), index, 0)
            podiums.addWidget(combo, index, 1)
            podiums.addWidget(QLabel("Phone:", self), index, 2)
            podiums.addWidget(phone, index, 3)
            self.podium_combos.append(combo)
            self.phone_labels.append(phone)
        podiums.setColumnStretch(1, 2)
        podiums.setColumnStretch(3, 1)

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(LAYOUT_SPACING)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING,) * 4)
        layout.addLayout(header)
        layout.addLayout(lists, 1)
        layout.addLayout(podiums)
        layout.addWidget(self.status_label)
        self.set_phones([])

    def load(self, folder: Path) -> None:
        """Show the tournament in ``folder``.

        Args:
            folder: The tournament's folder.

        Raises:
            TournamentFileError: If the tournament or its results can't be
                read.
        """
        settings, slots = load_tournament(Path(folder))
        results = load_results(Path(folder))
        self.folder = Path(folder)
        self.settings = settings
        self.slots = slots
        self.results = results
        self.load_error = None
        self.plan = plan_tournament(settings.bracket.options(len(slots)))
        self.title_label.setText(f"Tournament: {settings.name}")
        self._redraw()

    def reload(self) -> None:
        """Read the tournament again, for example after a game ends.

        A problem reading it is kept in :attr:`load_error`, which
        :meth:`problem` reports until a reload works, since the games and
        players shown may no longer be up to date.

        Returns:
            ``None``.
        """
        if self.folder is None:
            return
        try:
            self.load(self.folder)
        except TournamentFileError as exc:
            logging.error("Couldn't reload tournament: %s", exc)
            self.load_error = (
                f"Couldn't read the tournament: {exc} Fix the file, then click "
                "Fix Results... to read it again."
            )
            self.show_status(self.load_error, True)

    def selected_key(self) -> str | None:
        """Return the selected game's key, or ``None``."""
        row = self.games_list.currentRow()
        if not 0 <= row < len(self._game_keys):
            return None
        if not self.games_list.item(row).flags() & Qt.ItemFlag.ItemIsEnabled:
            return None
        return self._game_keys[row]

    def selected_board(self) -> TournamentBoard | None:
        """Return the selected game's board, or ``None``."""
        key = self.selected_key()
        if key is None or self.settings is None:
            return None
        return self.settings.boards.get(key)

    def select_game(self, key: str) -> None:
        """Select the game ``key``, if it can be played.

        Args:
            key: A game key.

        Returns:
            ``None``.
        """
        if key in self._game_keys:
            self.games_list.setCurrentRow(self._game_keys.index(key))

    def chosen_ids(self) -> list[str | None]:
        """Return the player id picked on each podium, or ``None``."""
        return [combo.currentData() for combo in self.podium_combos]

    def choose(self, podium: int, player_id: str) -> None:
        """Pick ``player_id`` for a podium, if they are offered there.

        Args:
            podium: Podium index, from 0.
            player_id: Player id.

        Returns:
            ``None``.
        """
        combo = self.podium_combos[podium]
        index = combo.findData(player_id)
        if index >= 0:
            combo.setCurrentIndex(index)

    def chosen_players(self) -> list[tuple[str, str]]:
        """Return ``(player_id, actual name)`` for each picked podium, in order."""
        by_id = slots_by_id(self.slots)
        return [
            (player_id, by_id[player_id].actual_name.strip())
            for player_id in self.chosen_ids()
            if player_id in by_id
        ]

    def game_ref(self) -> TournamentGameRef | None:
        """Return the selected game, for the game to save, or ``None``."""
        key = self.selected_key()
        if key is None or self.settings is None:
            return None
        return TournamentGameRef(self.settings.name, key)

    def intro_lines(self) -> list[str]:
        """Return the host's introduction of the picked players."""
        by_id = slots_by_id(self.slots)
        return introduction_lines(
            [by_id[player_id] for player_id in self.chosen_ids() if player_id in by_id]
        )

    def problem(self, connected_players: int) -> str | None:
        """Return why the selected game can't start yet, or ``None``.

        Args:
            connected_players: Phones in the lobby.

        Returns:
            A message for the host, or ``None``.
        """
        if self.load_error:
            return self.load_error
        key = self.selected_key()
        if key is None:
            return "Choose a game to play."
        if self.selected_board() is None:
            return "This game has no board. Set one on the Games tab."
        problem = seating_problem(self._eligibility, self.chosen_ids())
        if problem:
            return problem
        if connected_players != PLAYERS_PER_GAME:
            return (
                f"Wait for {PLAYERS_PER_GAME} phones to join "
                f"({connected_players} so far)."
            )
        return None

    def set_phones(self, names: list[object]) -> None:
        """Show which phone is on each podium.

        Args:
            names: Each connected player's name, in podium order.

        Returns:
            ``None``.
        """
        self._phone_names = list(names)
        for index, label in enumerate(self.phone_labels):
            name = self._phone_names[index] if index < len(self._phone_names) else None
            pixmap = signature_pixmap(name)
            if pixmap is None:
                label.setText(phone_label(name))
                label.setToolTip("")
                continue
            # Show the signature the player logged in with, at about the
            # height of three lines of text, so the host can match them.
            label.setPixmap(
                pixmap.scaledToHeight(
                    self._font_pixels * SIGNATURE_LINES,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            label.setToolTip(SIGNED_NAME_TEXT)

    def apply_scale(self, height: int) -> None:
        """Size the panel's text for a welcome screen ``height`` pixels tall.

        Args:
            height: The welcome screen's height.

        Returns:
            ``None``.
        """
        self._font_pixels = max(12, int(height * 0.022))
        font = self.font()
        font.setPixelSize(self._font_pixels)
        self.setFont(font)
        title_font = self.title_label.font()
        title_font.setPixelSize(max(16, int(height * 0.035)))
        self.title_label.setFont(title_font)
        # Signatures are sized to the text, so redraw them at the new size.
        self.set_phones(self._phone_names)

    def fix_results(self) -> None:
        """Open the results editor, then show any changes.

        The tournament is read again first, so the editor never saves over
        results it couldn't read. If it still can't be read, the problem is
        shown instead.

        Returns:
            ``None``.
        """
        if self.folder is None:
            return
        had_error = self.load_error is not None
        self.reload()
        if had_error or self.load_error:
            # Start depends on whether the tournament could be read.
            self.results_changed.emit()
        if self.load_error:
            return
        dialog = TournamentResultsDialog(self.folder, self.results, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()
        if accepted:
            self.reload()
            self.results_changed.emit()

    def _redraw(self) -> None:
        """Fill the games and players lists from the loaded tournament."""
        previous = self.selected_key()
        played_games = played_game_keys(self.results)
        played_players = played_player_ids(self.results)
        by_game = results_by_game(self.results)
        by_id = slots_by_id(self.slots)
        self.games_list.blockSignals(True)
        self.games_list.clear()
        self._game_keys = []
        games = plan_games(self.plan) if self.plan is not None else []
        for key, _round, game in games:
            board = self.settings.boards.get(key) if self.settings else None
            item = QListWidgetItem(self.games_list)
            self._game_keys.append(key)
            if key in played_games:
                winners = [
                    result.player
                    or by_id.get(result.player_id, PlayerSlot()).actual_name
                    for result in by_game.get(key, [])
                    if result.won
                ]
                item.setText(f"{key}: played, won by {', '.join(winners) or 'nobody'}")
                _grey(item)
                _disable(item)
            elif board is None:
                item.setText(f"{key}: no board")
                _grey(item)
                _disable(item)
            else:
                item.setText(f"{key}: {board.label}")
            item.setToolTip("Players: " + ", ".join(game.seats))
        self.games_list.setCurrentRow(-1)
        self.games_list.blockSignals(False)
        self.players_list.clear()
        for slot in self.slots:
            name = slot.actual_name.strip()
            if not name:
                continue
            item = QListWidgetItem(name, self.players_list)
            if slot.player_id in played_players:
                item.setText(f"{name} (played)")
                _grey(item)
        if not games:
            self.show_status(
                "The bracket doesn't work yet. Fix it on the Bracket tab.", True
            )
        if previous is not None and previous not in played_games:
            self.select_game(previous)
        else:
            self._on_game_changed(self.games_list.currentRow())

    def _on_game_changed(self, _row: int) -> None:
        """Offer the selected game's eligible players on each podium."""
        key = self.selected_key()
        if key is not None and self.plan is not None:
            self._eligibility = eligible_players(
                self.plan, key, self.slots, self.results, self.selected_board()
            )
        else:
            self._eligibility = Eligibility()
        by_id = slots_by_id(self.slots)
        for combo in self.podium_combos:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(CHOOSE_PLAYER_TEXT, None)
            for player_id in self._eligibility.entrants:
                combo.addItem(by_id[player_id].actual_name.strip(), player_id)
            for player_id in self._eligibility.chasers:
                if player_id not in self._eligibility.entrants:
                    combo.addItem(
                        f"{by_id[player_id].actual_name.strip()} (chaser)", player_id
                    )
            combo.setEnabled(key is not None)
            combo.blockSignals(False)
        self._on_podium_changed()

    def _on_podium_changed(self, *_args: object) -> None:
        """Report a change in the chosen game or players."""
        problem = self.problem(len(self._phone_names))
        self.show_status(problem or "Ready to start.", problem is not None)
        self.selection_changed.emit()

    def show_status(self, message: str, problem: bool = False) -> None:
        """Show ``message`` under the podiums, in red for problems."""
        # A style sheet resets the label's font, so it sets the size too.
        color = f"color: {PROBLEM_COLOR};" if problem else ""
        self.status_label.setStyleSheet(
            f"QLabel {{ {color} font-size: {self._font_pixels}px; }}"
        )
        self.status_label.setText(message)


RESULT_COLUMNS = ("Game", "Player", "Score", "Coryat", "Result")
COLUMN_GAME, COLUMN_PLAYER, COLUMN_SCORE, COLUMN_CORYAT, COLUMN_RESULT = range(5)


class TournamentResultsDialog(QDialog):
    """Fix a tournament's saved results.

    Scores, Coryat scores, and who won can be changed. Deleting a game's
    rows makes it playable again.
    """

    def __init__(
        self, folder: Path, results: list[GameResult], parent: QWidget | None = None
    ) -> None:
        """Show ``results`` for editing.

        Args:
            folder: The tournament's folder, where Save writes.
            results: The saved results.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.folder = Path(folder)
        self.results = list(results)
        self.setWindowTitle("Fix Results")
        self.resize(760, 480)
        self.table = QTableWidget(0, len(RESULT_COLUMNS), self)
        self.table.setHorizontalHeaderLabels(RESULT_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.delete_button = QPushButton("Delete Game's Results", self)
        self.delete_button.setToolTip(
            "Remove every result of the selected row's game, so it can be played again."
        )
        self.delete_button.clicked.connect(self.delete_selected_game)
        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING * 2,) * 4)
        if not self.results:
            layout.addWidget(QLabel("No games have been played yet.", self))
        layout.addWidget(self.table, 1)
        layout.addWidget(self.delete_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.status_label)
        layout.addWidget(self.buttons)
        self._fill()

    def _fill(self) -> None:
        """Show :attr:`results` in the table."""
        self.table.setRowCount(len(self.results))
        fusion = QStyleFactory.create("Fusion")
        for row, result in enumerate(self.results):
            for column, text in (
                (COLUMN_GAME, result.game_key),
                (COLUMN_PLAYER, result.player),
            ):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
            self.table.setItem(row, COLUMN_SCORE, QTableWidgetItem(str(result.score)))
            self.table.setItem(
                row,
                COLUMN_CORYAT,
                QTableWidgetItem("" if result.coryat is None else str(result.coryat)),
            )
            combo = QComboBox(self.table)
            if fusion is not None:
                fusion.setParent(combo)
                combo.setStyle(fusion)
            combo.addItems(RESULTS)
            combo.setCurrentText(result.result)
            self.table.setCellWidget(row, COLUMN_RESULT, combo)

    def edited_results(self) -> list[GameResult]:
        """Return the results as edited in the table.

        Raises:
            ValueError: If a score or Coryat score isn't a whole number,
                naming the row.
        """
        edited = []
        for row, result in enumerate(self.results):
            score_text = self.table.item(row, COLUMN_SCORE).text().strip()
            coryat_text = self.table.item(row, COLUMN_CORYAT).text().strip()
            try:
                score = int(score_text)
                coryat = int(coryat_text) if coryat_text else None
            except ValueError:
                raise ValueError(
                    f"Row {row + 1} ({result.player}): scores must be whole numbers."
                ) from None
            outcome = self.table.cellWidget(row, COLUMN_RESULT).currentText()
            edited.append(
                GameResult(
                    game_key=result.game_key,
                    player_id=result.player_id,
                    player=result.player,
                    score=score,
                    coryat=coryat,
                    game=result.game,
                    result=outcome,
                    saved_game=result.saved_game,
                )
            )
        return edited

    def delete_selected_game(self) -> None:
        """Drop every row of the selected row's game.

        Returns:
            ``None``.
        """
        row = self.table.currentRow()
        if not 0 <= row < len(self.results):
            return
        key = self.results[row].game_key
        try:
            kept_rows = [
                result for result in self.edited_results() if result.game_key != key
            ]
        except ValueError as exc:
            self._show_problem(str(exc))
            return
        self.results = kept_rows
        self._fill()

    def save(self) -> None:
        """Save the edited results and close.

        Returns:
            ``None``.
        """
        try:
            results = self.edited_results()
        except ValueError as exc:
            self._show_problem(str(exc))
            return
        for key, rows in results_by_game(results).items():
            if not any(result.won for result in rows):
                self._show_problem(f"{key} needs a winner.")
                return
        try:
            save_results(self.folder, results)
        except TournamentFileError as exc:
            QMessageBox.warning(self, "Couldn't save results", str(exc))
            return
        logging.info("Saved fixed tournament results")
        self.results = results
        self.accept()

    def _show_problem(self, message: str) -> None:
        """Show ``message`` in red above the buttons."""
        self.status_label.setStyleSheet(PROBLEM_STYLE)
        self.status_label.setText(message)
