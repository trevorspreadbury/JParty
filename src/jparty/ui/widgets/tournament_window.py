"""The Tournament window: everything tournament-related in one place.

The welcome screen's Tournament button opens this window. Its home page
creates or loads a tournament, or opens the bracket designer to try formats.
A created or loaded tournament opens in a :class:`TournamentEditor`. Its
Play Games button hides the window and hands the tournament to the welcome
screen, which plays its games.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.tournament_setup import TournamentBoard
from jparty.domain.tournament_store import (
    TournamentFileError,
    list_tournaments,
    load_tournament,
)
from jparty.services.game_sources import GameSourceFetcher
from jparty.ui.widgets.tournament import BracketDesigner
from jparty.ui.widgets.tournament_editor import TournamentEditor
from jparty.ui.widgets.tournament_games import missing_media_ids

LAYOUT_SPACING = 8
WINDOW_TITLE = "Tournament"
PROBLEM_STYLE = "QLabel { color: #b00020; }"


class TournamentWindow(QDialog):
    """Create, load, and edit tournaments, or try bracket formats.

    Attributes:
        editor: The open tournament, or ``None`` on the home page.
    """

    # The tournament folder, when the host clicks Play Games.
    play_requested = pyqtSignal(object)

    def __init__(
        self,
        root: Path,
        parent: QWidget | None = None,
        pick_board: Callable[
            [str, TournamentBoard | None, QWidget | None], TournamentBoard | None
        ]
        | None = None,
        fetcher: GameSourceFetcher | None = None,
        run_async: Callable[[Callable[[], None]], object] | None = None,
        missing_media: Callable[[TournamentBoard], list[str]] = missing_media_ids,
    ) -> None:
        """Build the home and bracket designer pages.

        Args:
            root: The tournaments folder.
            parent: Optional parent widget.
            pick_board: Asks the host for a game's board; ``None`` uses
                the board picker dialog. Tests pass a fake.
            fetcher: Sheet fetcher; tests pass a fake.
            run_async: Runs a callable off the UI thread; tests pass one that
                runs it inline.
            missing_media: Returns a board's source ids without question
                media; tests pass a fake.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.root = Path(root)
        self.pick_board = pick_board
        self.fetcher = fetcher
        self.run_async = run_async
        self.missing_media = missing_media
        self.editor: TournamentEditor | None = None
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1100, 720)

        self.stack = QStackedWidget(self)
        self.home_page = self._build_home_page()
        self.designer_page = self._build_designer_page()
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.designer_page)

        layout = QVBoxLayout(self)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING * 2,) * 4)
        layout.addWidget(self.stack)
        self.show_home()

    def _build_home_page(self) -> QWidget:
        """Return the page with Create, Load, and Bracket Designer."""
        page = QWidget(self)
        title = QLabel("<h2>Tournaments</h2>", page)
        self.create_button = QPushButton("Create Tournament", page)
        self.create_button.setToolTip(
            "Start a new tournament from its Google Form sign-up sheet."
        )
        self.create_button.clicked.connect(self.create_tournament)
        self.designer_button = QPushButton("Bracket Designer", page)
        self.designer_button.setToolTip(
            "Try bracket formats for any number of players."
        )
        self.designer_button.clicked.connect(self.show_designer)
        top_buttons = QHBoxLayout()
        top_buttons.addWidget(self.create_button)
        top_buttons.addWidget(self.designer_button)
        top_buttons.addStretch(1)

        self.saved_list = QListWidget(page)
        self.saved_list.itemSelectionChanged.connect(self._update_home_buttons)
        self.saved_list.itemDoubleClicked.connect(self.load_selected)
        self.load_button = QPushButton("Load Tournament", page)
        self.load_button.clicked.connect(self.load_selected)
        self.home_status = QLabel(page)
        self.home_status.setWordWrap(True)

        layout = QVBoxLayout(page)
        layout.setSpacing(LAYOUT_SPACING)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(title)
        layout.addLayout(top_buttons)
        layout.addWidget(QLabel("Saved tournaments:", page))
        layout.addWidget(self.saved_list, 1)
        layout.addWidget(self.load_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.home_status)
        return page

    def _build_designer_page(self) -> QWidget:
        """Return the page with a free-standing bracket designer."""
        page = QWidget(self)
        self.designer = BracketDesigner(page)
        back = QPushButton("Back to Tournaments", page)
        back.clicked.connect(self.show_home)
        layout = QVBoxLayout(page)
        layout.setSpacing(LAYOUT_SPACING)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.designer, 1)
        layout.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        return page

    def show_home(self) -> bool:
        """Close any open tournament and show the home page.

        Returns:
            ``False`` if the host kept an open tournament with unsaved
            changes, else ``True``.
        """
        if not self._close_editor():
            return False
        self.refresh_saved_list()
        self.stack.setCurrentWidget(self.home_page)
        self.setWindowTitle(WINDOW_TITLE)
        return True

    def show_designer(self) -> None:
        """Show the free-standing bracket designer.

        Returns:
            ``None``.
        """
        self.stack.setCurrentWidget(self.designer_page)
        self.setWindowTitle(f"{WINDOW_TITLE}: Bracket Designer")

    def refresh_saved_list(self) -> None:
        """List the saved tournaments on the home page.

        Returns:
            ``None``.
        """
        self.saved_list.clear()
        names = list_tournaments(self.root)
        self.saved_list.addItems(names)
        if names:
            self.saved_list.setCurrentRow(0)
            self._show_home_status("")
        else:
            self._show_home_status(
                "No saved tournaments yet. Use Create Tournament to start one."
            )
        self._update_home_buttons()

    def create_tournament(self) -> None:
        """Open a new, unsaved tournament.

        Returns:
            ``None``.
        """
        logging.info("Creating a tournament")
        self._open_editor(None, None)

    def load_selected(self, *_args: object) -> None:
        """Open the tournament selected on the home page.

        Returns:
            ``None``.
        """
        item = self.saved_list.currentItem()
        if item is None:
            return
        name = item.text()
        try:
            settings, slots = load_tournament(self.root / name)
        except TournamentFileError as exc:
            self._show_home_status(f"Couldn't load {name}: {exc}", problem=True)
            return
        logging.info("Loaded tournament %s", name)
        self._open_editor(settings, slots)

    def reject(self) -> None:
        """Hide the window, asking first if a tournament has unsaved changes.

        Escape and the window's close button come here. A tournament without
        unsaved changes stays open, so reopening the window returns to it.

        Returns:
            ``None``.
        """
        if (
            self.isVisible()
            and self.editor is not None
            and self.editor.has_unsaved_changes()
            and not self.show_home()
        ):
            return
        super().reject()

    def _open_editor(self, settings: object, slots: object) -> None:
        """Replace any open tournament with a new editor and show it."""
        if not self._close_editor():
            return
        editor = TournamentEditor(
            self.root,
            settings,
            slots,
            self,
            fetcher=self.fetcher,
            run_async=self.run_async,
            pick_board=self.pick_board,
            missing_media=self.missing_media,
        )
        editor.close_requested.connect(self.show_home)
        editor.play_requested.connect(self._play)
        editor.saved.connect(lambda _folder: self._update_editor_title())
        editor.name_edit.textChanged.connect(self._update_editor_title)
        self.editor = editor
        self.stack.addWidget(editor)
        self.stack.setCurrentWidget(editor)
        self._update_editor_title()

    def showEvent(self, event: object) -> None:
        """Lock boards of games played while the window was hidden."""
        super().showEvent(event)
        if self.editor is not None:
            self.editor.refresh_played()

    def _play(self, folder: Path) -> None:
        """Hide the window and pass the tournament on to be played."""
        self.hide()
        self.play_requested.emit(folder)

    def _close_editor(self) -> bool:
        """Close the open tournament if the host agrees.

        Returns:
            Whether no tournament is open any more.
        """
        editor = self.editor
        if editor is None:
            return True
        if not editor.confirm_discard():
            self.stack.setCurrentWidget(editor)
            return False
        self.editor = None
        self.stack.removeWidget(editor)
        editor.deleteLater()
        return True

    def _update_editor_title(self, *_args: object) -> None:
        """Show the open tournament's name in the title bar."""
        if self.editor is not None:
            self.setWindowTitle(self.editor.title())

    def _update_home_buttons(self) -> None:
        """Enable Load only when a tournament is selected."""
        self.load_button.setEnabled(self.saved_list.currentItem() is not None)

    def _show_home_status(self, message: str, problem: bool = False) -> None:
        """Show ``message`` under the saved list, in red for problems."""
        self.home_status.setStyleSheet(PROBLEM_STYLE if problem else "")
        self.home_status.setText(message)
