"""Edit one tournament: its players, bracket, games, and logo.

:class:`TournamentEditor` puts the roster (:mod:`.tournament_roster`), the
bracket designer (:mod:`.tournament`), and board assignments
(:mod:`.tournament_games`) on tabs, and saves them together to the
tournament's folder.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyleFactory,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.roster import PlayerSlot, roster_name_problem
from jparty.domain.tournament import TournamentPlan
from jparty.domain.tournament_dropouts import (
    Dropout,
    apply_dropouts,
    field_size,
)
from jparty.domain.tournament_play import played_game_keys
from jparty.domain.tournament_setup import TournamentBoard, forget_removed_players
from jparty.domain.tournament_store import (
    LOGO_SUFFIXES,
    TournamentFileError,
    TournamentSettings,
    load_dropouts,
    load_results,
    logo_problem,
    save_tournament,
    tournament_name_problem,
)
from jparty.services.game_sources import GameSourceFetcher
from jparty.ui.widgets.tournament import BracketDesigner
from jparty.ui.widgets.tournament_games import (
    GamesEditor,
    dropped_played_games_problem,
    missing_media_ids,
)
from jparty.ui.widgets.tournament_roster import RosterEditor

LAYOUT_SPACING = 8
LOGO_PREVIEW_SIZE = 48
TAB_PLAYERS = 0
TAB_BRACKET = 1
TAB_GAMES = 2
PROBLEM_STYLE = "QLabel { color: #b00020; }"


class TournamentEditor(QWidget):
    """A tournament's players, bracket, and games, saved together.

    Attributes:
        settings: Settings for the tournament being edited.
        creating: Whether this tournament hasn't been saved yet.
        saved_folder: The tournament folder once saved, else ``None``.
        logo_source: A newly chosen logo, copied into the folder on save.
    """

    saved = pyqtSignal(object)
    close_requested = pyqtSignal()
    # The tournament folder, when the host clicks Play Games.
    play_requested = pyqtSignal(object)

    def __init__(
        self,
        root: Path,
        settings: TournamentSettings | None = None,
        slots: Sequence[PlayerSlot] | None = None,
        parent: QWidget | None = None,
        fetcher: GameSourceFetcher | None = None,
        run_async: Callable[[Callable[[], None]], object] | None = None,
        pick_board: Callable[
            [str, TournamentBoard | None, QWidget | None], TournamentBoard | None
        ]
        | None = None,
        missing_media: Callable[[TournamentBoard], list[str]] = missing_media_ids,
    ) -> None:
        """Build the editor for a new tournament or a loaded one.

        Args:
            root: The tournaments folder.
            settings: A loaded tournament's settings, or ``None`` to create
                a new tournament.
            slots: A loaded tournament's roster.
            parent: Optional parent widget.
            fetcher: Sheet fetcher; tests pass a fake.
            run_async: Runs a callable off the UI thread; tests pass one that
                runs it inline.
            pick_board: Asks the host for a game's board; ``None`` uses
                the board picker dialog. Tests pass a fake.
            missing_media: Returns a board's source ids without question
                media; tests pass a fake.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.root = Path(root)
        self.creating = settings is None
        self.settings = settings or TournamentSettings(name="")
        self.saved_folder: Path | None = None
        self.logo_source: Path | None = None
        self._logo_file = self.settings.logo_file
        # Players who dropped out, from the play panel. Those who dropped
        # out before playing aren't in the bracket, and a play-in game
        # needs a board like any other game.
        self.dropouts = self._load_dropouts()

        self.name_edit = QLineEdit(self.settings.name, self)
        self.name_edit.setPlaceholderText("e.g. Family Fun 2026")
        self.name_edit.setReadOnly(not self.creating)
        self.logo_preview = QLabel(self)
        self.logo_preview.setFixedSize(LOGO_PREVIEW_SIZE, LOGO_PREVIEW_SIZE)
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.choose_logo_button = QPushButton("Choose Logo...", self)
        self.choose_logo_button.setToolTip(
            "Copied into the tournament's folder when you save, so it stays out of git."
        )
        self.choose_logo_button.clicked.connect(self.choose_logo)
        self.remove_logo_button = QPushButton("Remove Logo", self)
        self.remove_logo_button.clicked.connect(self.remove_logo)
        logo_layout = QHBoxLayout()
        logo_layout.addWidget(self.logo_preview)
        logo_layout.addWidget(self.choose_logo_button)
        logo_layout.addWidget(self.remove_logo_button)
        logo_layout.addStretch(1)
        form = QFormLayout()
        form.setSpacing(LAYOUT_SPACING)
        form.addRow("Tournament name:", self.name_edit)
        form.addRow("Logo:", logo_layout)

        self.roster = RosterEditor(
            self.settings, slots, self, fetcher=fetcher, run_async=run_async
        )
        self.bracket = BracketDesigner(self, roster_sets_players=True)
        games_options = {} if pick_board is None else {"pick_board": pick_board}
        self.games = GamesEditor(self, missing_media=missing_media, **games_options)
        self.tabs = QTabWidget(self)
        # JParty's app style draws tabs as plain text with no sign of the
        # current one, so use Fusion for the tab bar and its frame only.
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            fusion.setParent(self.tabs)
            self.tabs.setStyle(fusion)
            self.tabs.tabBar().setStyle(fusion)
        self.tabs.addTab(self.roster, "Players")
        self.tabs.addTab(self.bracket, "Bracket")
        self.tabs.addTab(self.games, "Games")

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Close,
            self,
        )
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.close_requested)
        self.play_button = self.buttons.addButton(
            "Play Games", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.play_button.setToolTip(
            "Save, then choose and start this tournament's games on the welcome screen."
        )
        self.play_button.clicked.connect(self.play)

        layout = QVBoxLayout(self)
        layout.setSpacing(LAYOUT_SPACING)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.buttons)

        self.bracket.set_player_count(self._field_size())
        self.bracket.set_bracket_settings(self.settings.bracket)
        self.games.set_players(self._roster_players())
        self.games.set_boards(self.settings.boards, self.settings.unassigned_boards)
        self.games.set_plan(self._played_plan())
        self.games.set_played(self._played_game_keys())
        self.roster.roster_changed.connect(self._on_roster_changed)
        self.bracket.plan_changed.connect(self._on_plan_changed)
        self.games.games_changed.connect(self._update_tab_titles)
        self._update_logo_preview()
        self._update_tab_titles()
        self._saved_state = self._state()

    def title(self) -> str:
        """Return a window title for this tournament."""
        name = self.name_edit.text().strip()
        return f"Tournament: {name}" if name else "New Tournament"

    def has_unsaved_changes(self) -> bool:
        """Whether anything changed since opening or saving."""
        return self._state() != self._saved_state

    def save(self) -> None:
        """Check the tournament and save its folder.

        A bracket that doesn't work yet is still saved, with a warning, so
        the host can finish the roster later.

        Returns:
            ``None``.
        """
        name = self.name_edit.text()
        problem = tournament_name_problem(name)
        if problem is None and self.creating and (self.root / name).exists():
            problem = f'A tournament named "{name}" already exists.'
        if problem is None:
            problem = roster_name_problem(self.roster.slots)
        if problem is None:
            # Saving would move a played game's board to the pool and leave
            # its results matching no game.
            dropped = self.games.dropped_played_games()
            if dropped:
                problem = dropped_played_games_problem(dropped)
        if problem:
            self._show_status(problem, True)
            return
        self.settings.name = name
        self.settings.sheet_url = self.roster.sheet_link()
        self.settings.bracket = self.bracket.bracket_settings()
        # Players removed from the roster no longer need to sit boards out.
        boards, unassigned = forget_removed_players(
            self.games.boards,
            self.games.unassigned,
            (slot.player_id for slot in self.roster.slots),
        )
        self.games.set_boards(boards, unassigned)
        self.settings.boards = boards
        self.settings.unassigned_boards = unassigned
        self.settings.logo_file = self._logo_file
        try:
            self.saved_folder = save_tournament(
                self.root, self.settings, self.roster.slots, self.logo_source
            )
        except (OSError, TournamentFileError) as exc:
            QMessageBox.warning(self, "Couldn't save tournament", str(exc))
            return
        logging.info("Saved tournament %s", name)
        self.creating = False
        self.name_edit.setReadOnly(True)
        self.logo_source = None
        self._logo_file = self.settings.logo_file
        self._saved_state = self._state()
        self._update_logo_preview()
        plan = self.bracket.plan
        if plan is not None and not plan.valid:
            self._show_status(
                "Saved. The bracket won't work yet; see the Bracket tab.", True
            )
        else:
            self._show_status("Saved.")
        self.saved.emit(self.saved_folder)

    def play(self) -> None:
        """Save if needed, then ask to play the tournament's games.

        Nothing is played while the bracket doesn't work, or if saving
        fails.

        Returns:
            ``None``.
        """
        plan = self.bracket.plan
        if plan is None or not plan.valid:
            self._show_status(
                "Fix the bracket before playing; see the Bracket tab.", True
            )
            return
        if self.creating or self.has_unsaved_changes():
            self.save()
            if self.creating or self.has_unsaved_changes():
                return
        self.play_requested.emit(self.root / self.settings.name)

    def confirm_discard(self) -> bool:
        """Ask before throwing away unsaved changes.

        A sheet fetch still running is dropped once the host agrees, so its
        result can't open the match dialog for a closed tournament.

        Returns:
            Whether it's fine to close the tournament.
        """
        if self.has_unsaved_changes():
            answer = QMessageBox.question(
                self,
                "Discard changes?",
                "Close without saving? Your changes to this tournament will be lost.",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return False
        self.roster.drop_pending_fetch()
        return True

    def choose_logo(self) -> None:
        """Pick a logo image; it is copied into the folder on save.

        Returns:
            ``None``.
        """
        patterns = " ".join(f"*{suffix}" for suffix in LOGO_SUFFIXES)
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Tournament Logo", "", f"Images ({patterns})"
        )
        if not path:
            return
        problem = logo_problem(Path(path))
        if problem:
            self._show_status(problem, True)
            return
        self.logo_source = Path(path)
        self._update_logo_preview()

    def remove_logo(self) -> None:
        """Drop the logo; the file is removed from the folder on save.

        Returns:
            ``None``.
        """
        self.logo_source = None
        self._logo_file = ""
        self._update_logo_preview()

    def _logo_path(self) -> Path | None:
        """Return the logo to preview: a new pick, else the saved one."""
        if self.logo_source is not None:
            return self.logo_source
        if self._logo_file and self.settings.name:
            return self.root / self.settings.name / self._logo_file
        return None

    def _update_logo_preview(self) -> None:
        """Show the logo thumbnail, or "No logo"."""
        path = self._logo_path()
        pixmap = QPixmap(str(path)) if path is not None else QPixmap()
        if pixmap.isNull():
            self.logo_preview.setPixmap(QPixmap())
            self.logo_preview.setText("No logo")
        else:
            self.logo_preview.setPixmap(
                pixmap.scaled(
                    LOGO_PREVIEW_SIZE,
                    LOGO_PREVIEW_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.remove_logo_button.setEnabled(path is not None)

    def refresh_played(self) -> None:
        """Lock the boards of games played since the editor opened.

        Returns:
            ``None``.
        """
        self.games.set_played(self._played_game_keys())

    def _played_game_keys(self) -> set[str]:
        """Return the keys of games with saved results, so their boards lock."""
        if self.creating:
            return set()
        try:
            return played_game_keys(load_results(self.root / self.settings.name))
        except TournamentFileError as exc:
            logging.error("Couldn't read tournament results: %s", exc)
            return set()

    def _roster_players(self) -> list[tuple[str, str]]:
        """Return ``(player_id, name)`` for each named player, in roster order."""
        return [
            (slot.player_id, slot.actual_name.strip())
            for slot in self.roster.slots
            if slot.actual_name.strip()
        ]

    def _on_roster_changed(self) -> None:
        """Re-plan the bracket for the roster's size and refresh player names."""
        self.games.set_players(self._roster_players())
        self.bracket.set_player_count(self._field_size())

    def _field_size(self) -> int:
        """Return the bracket's player count: the roster, less early dropouts."""
        return field_size(self.roster.slots, self.dropouts)

    def _played_plan(self) -> TournamentPlan | None:
        """Return the bracket with any play-in games added for dropouts."""
        plan = self.bracket.plan
        return plan if plan is None else apply_dropouts(plan, self.dropouts)

    def _load_dropouts(self) -> list[Dropout]:
        """Return the tournament's dropouts, or none if it can't be read."""
        if self.creating:
            return []
        try:
            return load_dropouts(self.root / self.settings.name)
        except TournamentFileError as exc:
            logging.error("Couldn't read tournament dropouts: %s", exc)
            return []

    def _on_plan_changed(self) -> None:
        """Show the new bracket's games and update the tab titles."""
        self.games.set_plan(self._played_plan())
        self._update_tab_titles()

    def _update_tab_titles(self) -> None:
        """Mark tabs that need attention."""
        plan = self.bracket.plan
        valid = plan is not None and plan.valid
        self.tabs.setTabText(TAB_PLAYERS, f"Players ({len(self.roster.slots)})")
        self.tabs.setTabText(TAB_BRACKET, "Bracket" if valid else "Bracket (!)")
        unassigned = f"{len(self.games.unassigned)} unassigned"
        if valid:
            assigned = len(self.games.boards)
            self.tabs.setTabText(
                TAB_GAMES,
                f"Games ({assigned}/{plan.total_games} boards, {unassigned})",
            )
        else:
            self.tabs.setTabText(TAB_GAMES, f"Games ({unassigned})")

    def _state(self) -> tuple:
        """Return what Save would write, to spot unsaved changes."""
        return (
            self.name_edit.text(),
            self.roster.sheet_link(),
            tuple(self.roster.slots),
            tuple(self.settings.ignored_sign_ups),
            self.bracket.bracket_settings(),
            dict(self.games.boards),
            list(self.games.unassigned),
            self.logo_source,
            self._logo_file,
        )

    def _show_status(self, message: str, problem: bool = False) -> None:
        """Show ``message`` above the buttons, in red for problems."""
        self.status_label.setStyleSheet(PROBLEM_STYLE if problem else "")
        self.status_label.setText(message)
