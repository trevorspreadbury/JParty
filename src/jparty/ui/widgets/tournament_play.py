"""Choosing and fixing a tournament's games from the welcome screen.

:class:`TournamentPlayPanel` replaces the welcome screen's game id and round
controls while a tournament is being played. It lists the bracket's games
and the roster, and has one player picker per podium. It reads the
tournament folder but never touches a game object: it emits
:attr:`TournamentPlayPanel.selection_changed`, and the welcome screen reads
the chosen board and players from it.

:class:`TournamentResultsDialog` lets the host fix ``results.csv`` after a
game.

The panel's Drop Player button marks the selected player as dropped out
(see :mod:`jparty.domain.tournament_dropouts`), and Undo Drop takes a
dropout back.

A game that stopped part way shows as in progress, and Resume Saved Game
asks the welcome screen to resume its save (see
:mod:`jparty.domain.tournament_saves`). Rankings shows every player's
place so far, and Edit Tournament opens the tournament in the Tournament
window.
"""

from __future__ import annotations

import logging
from base64 import urlsafe_b64decode
from collections.abc import Callable
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

from jparty.app.paths import GAME_STATES_DIR
from jparty.domain.models import SIGNATURE_NAME_PREFIX
from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament import PLAYERS_PER_GAME, TournamentPlan
from jparty.domain.tournament_advancement import (
    Eligibility,
    Tiebreak,
    TiebreakerSession,
    TieForSpot,
    advancement_conflicts,
    eligible_players,
    open_ties,
    player_statuses,
    seating_problem,
    tie_spot_text,
    tie_text,
    tournament_standings,
)
from jparty.domain.tournament_drop_choices import (
    TournamentData,
    apply_drop,
    drop_situation,
    dropout_text,
    undo_drop,
    undo_problem,
)
from jparty.domain.tournament_dropouts import (
    DROP_REPLACE,
    Dropout,
    dropped_ids,
    effective_plan,
)
from jparty.domain.tournament_play import (
    RESULTS,
    GameResult,
    TournamentGameRef,
    introduction_lines,
    played_game_keys,
    results_by_game,
    slots_by_id,
)
from jparty.domain.tournament_rankings import PlayerRanking, tournament_rankings
from jparty.domain.tournament_saves import (
    TournamentSave,
    find_tournament_saves,
    resume_problem,
)
from jparty.domain.tournament_setup import TournamentBoard, plan_games
from jparty.domain.tournament_store import (
    TournamentFileError,
    TournamentSettings,
    load_dropouts,
    load_results,
    load_tiebreaks,
    load_tournament,
    load_tournament_data,
    save_results,
    save_tournament_data,
)
from jparty.ui.board_sources import composed_session_game_id
from jparty.ui.widgets.tournament_dropouts import ask_drop, ask_undo
from jparty.ui.widgets.tournament_rankings import RankingsDialog

LAYOUT_SPACING = 8
PLAYED_COLOR = QColor("#8a8a8a")
PROBLEM_STYLE = "QLabel { color: #b00020; }"
PROBLEM_COLOR = "#b00020"
NO_PHONE_TEXT = "no phone yet"
SIGNED_NAME_TEXT = "signed name"
CHOOSE_PLAYER_TEXT = "Choose a player"
IN_PROGRESS_TEXT = "in progress"
RESUME_TOOLTIP = (
    "Pick up the selected game where it stopped. The players' phones claim"
    " their saved players."
)
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
        dropouts: Every player who dropped out.
        plan: The bracket actually played, after dropouts.
        before_change: Returns why the tournament can't be changed right
            now, or ``None``. The welcome screen sets it, so a drop isn't
            lost under unsaved edits in the Tournament window.
        ask_drop: Asks the host what happens to a dropped player's spot;
            tests replace it.
        ask_undo: Asks the host which dropout to take back; tests replace
            it.
        states_dir: The saved games folder, searched for half-played games.
        saves: The newest save of each unplayed game that has one, by game
            key.
        rankings_dialog: The open Rankings window, or ``None``.
    """

    selection_changed = pyqtSignal()
    leave_requested = pyqtSignal()
    # The host wants to change the tournament in the Tournament window.
    edit_requested = pyqtSignal()
    # The TournamentSave of the selected game, to resume.
    resume_requested = pyqtSignal(object)
    results_changed = pyqtSignal()
    # A dropout changed the roster, boards, or bracket on disk.
    tournament_changed = pyqtSignal()

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
        # Tiebreakers played to settle ties for wildcards, chasers, and byes.
        self.tiebreaks: list[Tiebreak] = []
        # The open tie shown on each tiebreaker row of the games list.
        self._row_ties: dict[int, TieForSpot] = {}
        self.dropouts: list[Dropout] = []
        self.plan: TournamentPlan | None = None
        self.before_change: Callable[[], str | None] | None = None
        self.ask_drop = ask_drop
        self.ask_undo = ask_undo
        # Why the last reload failed, or None. The results shown are then
        # out of date, so no game can start until a reload works.
        self.load_error: str | None = None
        self._game_keys: list[str] = []
        self._eligibility = Eligibility()
        self._phone_names: list[object] = []
        self._font_pixels = 16
        self.states_dir = GAME_STATES_DIR
        self.saves: dict[str, TournamentSave] = {}
        self.rankings_dialog: RankingsDialog | None = None

        self.title_label = QLabel(self)
        title_font = QFont()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.fix_results_button = QPushButton("Fix Results...", self)
        self.fix_results_button.setToolTip("Change a played game's scores or winner.")
        self.fix_results_button.clicked.connect(self.fix_results)
        self.rankings_button = QPushButton("Rankings...", self)
        self.rankings_button.setToolTip("Show every player's place so far.")
        self.rankings_button.clicked.connect(self.show_rankings)
        self.edit_button = QPushButton("Edit Tournament...", self)
        self.edit_button.setToolTip(
            "Change the players, bracket, or boards in the Tournament window."
        )
        self.edit_button.clicked.connect(self.edit_requested)
        self.leave_button = QPushButton("Leave Tournament", self)
        self.leave_button.setToolTip("Go back to choosing a regular game.")
        self.leave_button.clicked.connect(self.leave_requested)
        header = QHBoxLayout()
        header.addWidget(self.title_label, 1)
        header.addWidget(self.rankings_button)
        header.addWidget(self.edit_button)
        header.addWidget(self.fix_results_button)
        header.addWidget(self.leave_button)

        self.games_list = QListWidget(self)
        self.games_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.games_list.currentRowChanged.connect(self._on_game_changed)
        self.players_list = QListWidget(self)
        self.players_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.players_list.currentRowChanged.connect(self._update_drop_buttons)
        self.drop_button = QPushButton("Drop Player...", self)
        self.drop_button.setToolTip(
            "Mark the selected player as dropped out, and choose who takes their spot."
        )
        self.drop_button.clicked.connect(self.drop_selected_player)
        self.undo_drop_button = QPushButton("Undo Drop...", self)
        self.undo_drop_button.setToolTip("Take back a dropout.")
        self.undo_drop_button.clicked.connect(self.undo_dropout)
        drop_buttons = QHBoxLayout()
        drop_buttons.addWidget(self.drop_button)
        drop_buttons.addWidget(self.undo_drop_button)
        drop_buttons.addStretch(1)
        lists = QGridLayout()
        lists.addWidget(QLabel("Games:", self), 0, 0)
        lists.addWidget(QLabel("Players:", self), 0, 1)
        lists.addWidget(self.games_list, 1, 0)
        lists.addWidget(self.players_list, 1, 1)
        lists.addLayout(drop_buttons, 2, 1)
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
        self.resume_button = QPushButton("Resume Saved Game", self)
        self.resume_button.setToolTip(RESUME_TOOLTIP)
        self.resume_button.clicked.connect(self.resume_selected)
        podiums.addWidget(
            self.resume_button,
            PLAYERS_PER_GAME,
            0,
            1,
            4,
            Qt.AlignmentFlag.AlignLeft,
        )

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        # Results fixed after a later game was played, so that game's
        # players no longer all advanced into it. Hidden when there are none.
        self.conflicts_label = QLabel(self)
        self.conflicts_label.setWordWrap(True)
        self.conflicts_label.setStyleSheet(PROBLEM_STYLE)
        self.conflicts_label.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setSpacing(LAYOUT_SPACING)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING,) * 4)
        layout.addLayout(header)
        layout.addWidget(self.conflicts_label)
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
        tiebreaks = load_tiebreaks(Path(folder))
        dropouts = load_dropouts(Path(folder))
        self.folder = Path(folder)
        self.settings = settings
        self.slots = slots
        self.results = results
        self.tiebreaks = tiebreaks
        self.dropouts = dropouts
        self.load_error = None
        self.plan = effective_plan(settings.bracket, slots, dropouts)
        self.saves = self._find_saves()
        self.title_label.setText(f"Tournament: {settings.name}")
        self._redraw()

    def _find_saves(self) -> dict[str, TournamentSave]:
        """Return the newest save of each unplayed game with a board."""
        if self.settings is None:
            return {}
        played = played_game_keys(self.results)
        game_ids = {
            key: composed_session_game_id(list(board.board_selections)) or board.label
            for key, board in self.settings.boards.items()
            if key not in played
        }
        return find_tournament_saves(self.states_dir, self.settings.name, game_ids)

    def selected_save(self) -> TournamentSave | None:
        """Return the selected game's save, if it was started and not finished."""
        key = self.selected_key()
        return self.saves.get(key) if key is not None else None

    def resume_problem(self) -> str | None:
        """Return why the selected game's save can't be resumed, or ``None``.

        See :func:`jparty.domain.tournament_saves.resume_problem`. Starting
        the game again with new players still works.

        Returns:
            A message for the host, or ``None``.
        """
        save = self.selected_save()
        if save is None:
            return "This game has no saved game to resume."
        if self.load_error:
            return self.load_error
        return resume_problem(
            save, self._eligibility, self.dropouts, self._names(), self.results
        )

    def with_resume_note(self, message: str) -> str:
        """Return ``message``, plus why the selected save can't be resumed.

        Args:
            message: The status for starting the game.

        Returns:
            ``message``, with a "Can't resume" line when the selected game
            has a save that can't be resumed.
        """
        if self.selected_save() is None:
            return message
        problem = self.resume_problem()
        return f"{message}\nCan't resume: {problem}" if problem else message

    def resume_selected(self) -> None:
        """Ask the welcome screen to resume the selected game's save.

        Returns:
            ``None``.
        """
        save = self.selected_save()
        if save is not None and self.resume_problem() is None:
            logging.info(
                "Resuming tournament game %s from %s", save.game_key, save.path
            )
            self.resume_requested.emit(save)

    def rankings(self) -> list[PlayerRanking]:
        """Return every player's place so far, best first."""
        return tournament_rankings(
            self.plan, self.slots, self.results, self.tiebreaks, self.dropouts
        )

    def show_rankings(self) -> None:
        """Open the Rankings window, replacing one already open.

        Returns:
            ``None``.
        """
        if self.rankings_dialog is not None:
            self.rankings_dialog.close()
            self.rankings_dialog.deleteLater()
        name = self.settings.name if self.settings is not None else ""
        self.rankings_dialog = RankingsDialog(
            f"Rankings: {name}", self.rankings(), self
        )
        self.rankings_dialog.show()

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
        if not 0 <= row < len(self._game_keys) or row in self._row_ties:
            return None
        if not self.games_list.item(row).flags() & Qt.ItemFlag.ItemIsEnabled:
            return None
        return self._game_keys[row]

    def selected_tie(self) -> TieForSpot | None:
        """Return the tie on the selected tiebreaker row, or ``None``."""
        return self._row_ties.get(self.games_list.currentRow())

    def tiebreaker_session(self) -> TiebreakerSession | None:
        """Return the selected tie as a tiebreaker to play, or ``None``."""
        tie = self.selected_tie()
        if tie is None or self.settings is None:
            return None
        names = self._names()
        return TiebreakerSession(
            self.settings.name,
            tie,
            tuple((player_id, names.get(player_id, "")) for player_id in tie.players),
        )

    def selected_tie_text(self) -> str:
        """Return the message for the selected tie, or ``""``."""
        tie = self.selected_tie()
        return tie_text(tie, self._names()) if tie is not None else ""

    def _names(self) -> dict[str, str]:
        """Return each player's Actual Name, by player id."""
        return {slot.player_id: slot.actual_name.strip() for slot in self.slots}

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
        if key and key in self._game_keys:
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
        tie = self.selected_tie()
        if tie is not None:
            if connected_players == len(tie.players):
                return None
            names = self._names()
            order = ", ".join(names.get(p, p) for p in tie.players)
            return (
                f"Wait for {len(tie.players)} phones to join "
                f"({connected_players} so far), in this order: {order}."
            )
        key = self.selected_key()
        if key is None:
            return "Choose a game to play."
        if self.selected_board() is None:
            return "This game has no board. Set one on the Games tab."
        problem = seating_problem(self._eligibility, self.chosen_ids())
        if problem:
            return problem
        seats = self._eligibility.seats
        if connected_players != seats:
            return f"Wait for {seats} phones to join ({connected_players} so far)."
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
        by_game = results_by_game(self.results)
        by_id = slots_by_id(self.slots)
        names = {slot.player_id: slot.actual_name.strip() for slot in self.slots}
        standings = (
            tournament_standings(self.plan, self.results, self.tiebreaks, self.dropouts)
            if self.plan is not None and self.plan.valid
            else []
        )
        chasers = {
            key: chaser
            for standing in standings
            for key, chaser in standing.chasers.items()
        }
        self.games_list.blockSignals(True)
        self.games_list.clear()
        self._game_keys = []
        self._row_ties = {}
        # Open ties come first: the next games can't start until they're
        # settled.
        for tie in open_ties(standings):
            who = ", ".join(names.get(p) or p for p in tie.players)
            item = QListWidgetItem(
                f"Tiebreaker: {who} for {tie_spot_text(tie)} in the {tie.round_name}",
                self.games_list,
            )
            item.setToolTip(f"Tied at ${tie.score:,}. Their phones join in this order.")
            self._row_ties[self.games_list.count() - 1] = tie
            self._game_keys.append("")
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
                text = f"{key}: {board.label}"
                if key in chasers:
                    text += f" (chaser: {names.get(chasers[key]) or chasers[key]})"
                if key in self.saves:
                    text += f" ({IN_PROGRESS_TEXT})"
                item.setText(text)
            tooltip = "Players: " + ", ".join(game.seats)
            save = self.saves.get(key) if key not in played_games else None
            if save is not None:
                tooltip += "\nStarted with " + ", ".join(save.players)
            item.setToolTip(tooltip)
        self.games_list.setCurrentRow(-1)
        self.games_list.blockSignals(False)
        previous_player = self.selected_player_id()
        self.players_list.blockSignals(True)
        self.players_list.clear()
        statuses = (
            player_statuses(self.plan, standings, self.dropouts) if standings else {}
        )
        for slot in self.slots:
            name = slot.actual_name.strip()
            if not name:
                continue
            item = QListWidgetItem(name, self.players_list)
            item.setData(Qt.ItemDataRole.UserRole, slot.player_id)
            if slot.player_id == previous_player:
                self.players_list.setCurrentItem(item)
            if slot.player_id in statuses:
                status, waiting = statuses[slot.player_id]
                item.setText(f"{name} ({status})")
                if waiting:
                    _grey(item)
        self.players_list.blockSignals(False)
        self._update_drop_buttons()
        conflicts = (
            advancement_conflicts(
                self.plan, standings, self.results, names, self.dropouts
            )
            if standings
            else []
        )
        self.conflicts_label.setText(
            "\n".join(
                [
                    "Some results changed after later games were played:",
                    *conflicts,
                    "Fix those games' results, or delete them and play them again.",
                ]
            )
        )
        self.conflicts_label.setVisible(bool(conflicts))
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
                self.plan,
                key,
                self.slots,
                self.results,
                self.selected_board(),
                self.tiebreaks,
                self.dropouts,
            )
        else:
            self._eligibility = Eligibility()
        by_id = slots_by_id(self.slots)
        tie = self.selected_tie()
        if tie is not None:
            # A tiebreaker's players are fixed: show them in the order their
            # phones join.
            for index, combo in enumerate(self.podium_combos):
                combo.blockSignals(True)
                combo.clear()
                if index < len(tie.players):
                    player_id = tie.players[index]
                    slot = by_id.get(player_id)
                    combo.addItem(
                        slot.actual_name.strip() if slot else player_id, player_id
                    )
                else:
                    combo.addItem("-", None)
                combo.setEnabled(False)
                combo.blockSignals(False)
            self._on_podium_changed()
            return
        for combo in self.podium_combos:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(CHOOSE_PLAYER_TEXT, None)
            for player_id in self._eligibility.entrants:
                combo.addItem(by_id[player_id].actual_name.strip(), player_id)
            # A voided game's replacement is offered like a chaser.
            extra = "chaser" if self._eligibility.chase else "replacement"
            for player_id in self._eligibility.chasers:
                if player_id not in self._eligibility.entrants:
                    combo.addItem(
                        f"{by_id[player_id].actual_name.strip()} ({extra})", player_id
                    )
            combo.setEnabled(key is not None)
            combo.blockSignals(False)
        self._on_podium_changed()

    def selected_player_id(self) -> str | None:
        """Return the player selected in the players list, or ``None``."""
        item = self.players_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _update_drop_buttons(self, *_args: object) -> None:
        """Enable Drop Player for a selected player, and Undo Drop for dropouts."""
        player_id = self.selected_player_id()
        self.drop_button.setEnabled(
            player_id is not None and player_id not in dropped_ids(self.dropouts)
        )
        self.undo_drop_button.setEnabled(bool(self.dropouts))

    def _change_problem(self) -> str | None:
        """Return why the tournament can't be changed now, or ``None``."""
        if self.folder is None:
            return "No tournament is loaded."
        problem = self.before_change() if self.before_change is not None else None
        if problem:
            return problem
        self.reload()
        return self.load_error

    def drop_selected_player(self) -> None:
        """Mark the selected player as dropped out, as the host chooses.

        The host is shown where the player stands and what can happen to
        their spot. The choice is saved straight away.

        Returns:
            ``None``.
        """
        player_id = self.selected_player_id()
        if player_id is None:
            return
        problem = self._change_problem()
        if problem:
            QMessageBox.warning(self, "Can't drop player", problem)
            return
        settings, data = load_tournament_data(self.folder)
        situation = drop_situation(data, player_id)
        if situation.problem:
            QMessageBox.information(self, "Can't drop player", situation.problem)
            return
        answer = self.ask_drop(situation, self)
        if answer is None:
            return
        chosen, new_name = answer
        new_player = (
            PlayerSlot(new_name) if chosen.dropout.choice == DROP_REPLACE else None
        )
        logging.info(
            "Dropping tournament player %s: %s", player_id, chosen.dropout.choice
        )
        self._save_change(settings, apply_drop(data, chosen.dropout, new_player))

    def undo_dropout(self) -> None:
        """Take back a dropout the host picks, if it still fits the games played.

        Returns:
            ``None``.
        """
        problem = self._change_problem()
        if problem:
            QMessageBox.warning(self, "Can't undo drop", problem)
            return
        settings, data = load_tournament_data(self.folder)
        if not data.dropouts:
            return
        names = data.names()
        dropout = self.ask_undo(
            data.dropouts,
            [dropout_text(dropout, names) for dropout in data.dropouts],
            [undo_problem(data, dropout) for dropout in data.dropouts],
            self,
        )
        if dropout is None or undo_problem(data, dropout):
            return
        logging.info("Undoing tournament dropout of %s", dropout.player_id)
        self._save_change(settings, undo_drop(data, dropout))

    def _save_change(self, settings: TournamentSettings, data: TournamentData) -> None:
        """Save a dropout change, then show it."""
        try:
            save_tournament_data(self.folder, settings, data)
        except TournamentFileError as exc:
            QMessageBox.warning(self, "Couldn't save the dropout", str(exc))
        self.reload()
        self.tournament_changed.emit()
        self.results_changed.emit()

    def _on_podium_changed(self, *_args: object) -> None:
        """Report a change in the chosen game or players."""
        save = self.selected_save()
        resume_problem = self.resume_problem() if save is not None else None
        self.resume_button.setEnabled(save is not None and resume_problem is None)
        self.resume_button.setToolTip(resume_problem or RESUME_TOOLTIP)
        problem = self.problem(len(self._phone_names))
        message = problem or "Ready to start."
        if resume_problem:
            message += f"\nCan't resume: {resume_problem}"
        self.show_status(message, problem is not None)
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
