"""Lobby and startup widgets for game selection and buzzer joining.

This module contains the welcome-screen widgets used to choose or resume a
game, plus the QR-code display shown on the audience screen so players can join
the buzzer web app.
"""

import logging
from functools import partial
from pathlib import Path

import qrcode
from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QFont, QImage, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jparty import __version__ as version
from jparty.app.helptext import helpmsg
from jparty.app.paths import GAME_STATES_DIR, TOURNAMENTS_DIR
from jparty.domain.models import GameData
from jparty.domain.tournament_store import TournamentFileError
from jparty.services.game_loader import (
    RANDOM_GAME_MAX_ATTEMPTS,
    build_game_from_board_selection_configs,
    compose_game_from_resolved_board_selections,
    describe_source_round,
    get_game,
    original_board_selection,
)
from jparty.services.question_media import (
    detect_question_media,
    import_question_media,
    is_local_media_path,
    local_media_questions,
)
from jparty.ui.board_sources import (
    composed_board_summary_text,
    composed_session_game_id,
    find_random_game_with_media,
    game_warning_lines,
    is_playable_game_data,
    random_game_failure_text,
)
from jparty.ui.styles import WINDOWPAL
from jparty.ui.welcome_loader import LatestRequest, WelcomeLoader
from jparty.ui.welcome_presenter import WelcomePresenter
from jparty.ui.widgets.advanced_boards import AdvancedBoardEditor
from jparty.ui.widgets.common import (
    DynamicButton,
    DynamicLabel,
    add_shadow,
    choose_question_media_path,
    resource_path,
)
from jparty.ui.widgets.tournament_play import TournamentPlayPanel
from jparty.ui.widgets.tournament_window import TournamentWindow

ROUND_CHECKBOX_STYLE = """
QCheckBox {
    color: black;
    spacing: 0px;
    font-size: 24px;
    font-weight: 600;
}
QCheckBox::indicator {
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}
"""

ROUNDS_LABEL_STYLE = """
QLabel {
    color: black;
    font-size: 22px;
    font-weight: 700;
}
"""


class Image(qrcode.image.base.BaseImage):
    """Adapter that renders QR codes into Qt image objects.

    ``qrcode.image.base.BaseImage.__init__`` stores ``border``, ``width``,
    ``box_size`` and ``pixel_size`` (all in whole pixels or modules), then calls
    :meth:`new_image` to build the drawing surface.
    """

    def new_image(self, **kwargs: object) -> QImage:
        """Create the blank QR image buffer.

        Args:
            **kwargs: Extra image options from ``qrcode``; unused.

        Returns:
            A square ``QImage`` filled with the window background color.
        """
        image = QImage(self.pixel_size, self.pixel_size, QImage.Format.Format_RGB16)
        image.fill(WINDOWPAL.color(QPalette.ColorRole.Window))
        return image

    def pixmap(self) -> object:
        """Return the rendered QR code as a ``QPixmap``.

        Returns:
            ``QPixmap`` representation of the QR code image.
        """
        return QPixmap.fromImage(self._img)

    def drawrect(self, row: object, col: object) -> None:
        """Fill one QR module rectangle.

        Args:
            row: Row index of the QR module to fill.
            col: Column index of the QR module to fill.

        Returns:
            ``None``.
        """
        painter = QPainter(self._img)
        painter.fillRect(
            (col + self.border) * self.box_size,
            (row + self.border) * self.box_size,
            self.box_size,
            self.box_size,
            Qt.GlobalColor.black,
        )
        painter.end()

    def save(self, stream: object, kind: object = None) -> None:
        """Satisfy the qrcode image interface without saving to disk.

        Args:
            stream: Ignored output stream parameter required by the interface.
            kind: Ignored output kind parameter required by the interface.

        Returns:
            ``None``.
        """
        pass


class StartWidget(QWidget):
    """Base widget for startup screens with the shared JParty logo area."""

    def __init__(self, parent: object = None) -> None:
        """Initialize shared startup-screen visuals.

        Args:
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.icon = QPixmap(resource_path("icon.png"))
        self.icon_label = DynamicLabel("", 0, self)
        add_shadow(self, radius=0.2)
        self.setPalette(WINDOWPAL)
        self.icon_layout = QHBoxLayout()
        self.icon_layout.addStretch()
        self.icon_layout.addWidget(self.icon_label)
        self.icon_layout.addStretch()

    def paintEvent(self, event: object) -> None:
        """Paint the startup widget background.

        Args:
            event: Qt paint event object.

        Returns:
            ``None``.
        """
        qp = QPainter()
        qp.begin(self)
        qp.setBrush(QBrush(WINDOWPAL.color(QPalette.ColorRole.Window)))
        qp.drawRect(self.rect())

    def resizeEvent(self, event: object) -> None:
        """Scale the startup icon to match the current layout.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        icon_size = self.icon_label.height()
        self.icon_label.setPixmap(
            self.icon.scaled(
                icon_size,
                icon_size,
                transformMode=Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.icon_label.setMaximumWidth(icon_size)


class Welcome(StartWidget):
    """Host-side lobby screen for choosing, previewing, and resuming games."""

    summary_trigger = pyqtSignal(str)
    # (request_id, game_id, data, error, media_status, from_random)
    summary_load_result_trigger = pyqtSignal(int, str, object, object, object, bool)
    # (request_id, selected_dir, loaded_save, error)
    saved_game_result_trigger = pyqtSignal(int, str, object, object)
    # (request_id, game_key, data, error) for a tournament game's board
    tournament_board_result_trigger = pyqtSignal(int, str, object, object)

    def __init__(self, game: object, parent: object = None) -> None:
        """Initialize the welcome screen and its lobby controls.

        Args:
            game: Active game instance being configured.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.game = game
        self.presenter = WelcomePresenter(game)
        self.loader = WelcomeLoader()
        self.resume_path = None
        self._base_summary_text = ""
        self._loading_summary = False
        # Newest single-game load (typed id, Random, Load Saved). Results
        # from older requests are dropped.
        self._summary_request = LatestRequest()
        # Request id of a reload started by a media import, or ``None``.
        self._media_reload_request_id = None
        # Shown in the summary after a failed media reload or Random kept the
        # old game.
        self._media_reload_warning = ""
        # Id of the game currently in ``game.data`` in regular mode, or "".
        self._loaded_summary_game_id = ""
        self._question_media_status = None
        self.round_checkboxes = []
        self._advanced_mode_summary_text = ""
        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.title_font = QFont()
        self.title_font.setBold(True)
        self.title_label = DynamicLabel("JParty!", lambda: self.height() * 0.1, self)
        self.title_label.setFont(self.title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label = DynamicLabel(
            f"version {version}", lambda: self.height() * 0.03
        )
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setStyleSheet("QLabel { color : grey}")
        self.regular_workflow_widget = QWidget(self)
        select_layout = QHBoxLayout()
        self.regular_workflow_widget.setLayout(select_layout)
        template_url = "https://docs.google.com/spreadsheets/d/1_vBBsWn-EVc7npamLnOKHs34Mc2iAmd9hOGSzxHQX0Y/edit#gid=0"
        gameid_text = f'Game ID (from J-Archive URL)<br>or <a href="{template_url}">GSheet ID for custom game</a>'
        self.gameid_label = DynamicLabel(gameid_text, lambda: self.height() * 0.1, self)
        self.gameid_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.gameid_label.setOpenExternalLinks(True)
        self.debounce_timer = QTimer(self)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self.debounced_show_summary)
        self.textbox = QLineEdit(self)
        self.textbox.textChanged.connect(self.start_debounce_timer)
        f = self.textbox.font()
        self.textbox.setFont(f)
        button_layout = QVBoxLayout()
        self.start_button = DynamicButton("Start!", self)
        self.start_button.clicked.connect(self.on_start_clicked)
        self.start_button.setEnabled(False)
        self.load_media_button = DynamicButton("Load Question Media", self)
        self.load_media_button.clicked.connect(self.load_question_media)
        self.resume_button = DynamicButton("Load Saved", self)
        self.resume_button.clicked.connect(self.load_saved_game)
        self.rand_button = DynamicButton("Random", self)
        self.rand_button.clicked.connect(self.random)
        button_layout.addWidget(self.start_button, 10)
        button_layout.addStretch(1)
        button_layout.addWidget(self.load_media_button, 10)
        button_layout.addStretch(1)
        button_layout.addWidget(self.resume_button, 10)
        button_layout.addStretch(1)
        button_layout.addWidget(self.rand_button, 10)
        select_layout.addStretch(5)
        select_layout.addWidget(self.gameid_label, 40)
        select_layout.addStretch(2)
        select_layout.addWidget(self.textbox, 40)
        select_layout.addStretch(2)
        select_layout.addLayout(button_layout, 20)
        select_layout.addStretch(5)
        self.summary_label = DynamicLabel("", lambda: self.height() * 0.072, self)
        self.summary_label.setWordWrap(True)
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self.rounds_widget = QWidget(self)
        self.rounds_layout = QVBoxLayout()
        self.rounds_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rounds_layout.setSpacing(12)
        self.rounds_widget.setLayout(self.rounds_layout)
        self.rounds_widget.setVisible(False)
        self.advanced_options_checkbox = QCheckBox("Advanced Options", self)
        self.advanced_options_checkbox.stateChanged.connect(
            self.toggle_advanced_options
        )
        # Late-bound, so the editor always uses this screen's current loader
        # and media chooser, even if either is replaced after construction.
        self.advanced_boards = AdvancedBoardEditor(
            self,
            run_async=lambda work: self.loader.run_async(work),
            choose_media_path=lambda: self.select_question_media_path(),
        )
        self.advanced_boards.setVisible(False)
        self.advanced_start_button = DynamicButton("Start!", self.advanced_boards)
        self.advanced_start_button.clicked.connect(self.on_start_clicked)
        self.advanced_start_button.setEnabled(False)
        self.advanced_boards.add_header_widget(self.advanced_start_button)
        self.advanced_boards.setup_changed.connect(self.sync_active_configuration)
        self.reveal_answers_radio = QRadioButton(
            "Reveal Answers after Triple Stumper", self
        )
        self.reveal_answers_radio.setChecked(
            bool(
                getattr(
                    self.game,
                    "reveal_answers_after_triple_stumper_enabled",
                    lambda: False,
                )()
            )
        )
        self.reveal_answers_radio.toggled.connect(
            self.update_reveal_answers_after_triple_stumper
        )
        self.quit_button = DynamicButton("Quit", self)
        self.quit_button.clicked.connect(self.game.close)
        self.help_button = DynamicButton("Show help", self)
        self.help_button.clicked.connect(self.show_help)
        self.tournament_button = DynamicButton("Tournament", self)
        self.tournament_button.clicked.connect(self.show_tournament_window)
        self.tournament_window = None
        # While a tournament is played, this panel replaces the game id and
        # round controls; see enter_tournament_mode.
        self.tournament_mode = False
        self.tournament_panel = TournamentPlayPanel(self)
        self.tournament_panel.setVisible(False)
        self.tournament_start_button = DynamicButton("Start!", self.tournament_panel)
        self.tournament_start_button.setEnabled(False)
        self.tournament_start_button.clicked.connect(self.on_start_clicked)
        self.tournament_panel.layout().addWidget(
            self.tournament_start_button, 0, Qt.AlignmentFlag.AlignHCenter
        )
        self.tournament_panel.selection_changed.connect(
            self.on_tournament_selection_changed
        )
        self.tournament_panel.leave_requested.connect(self.leave_tournament_mode)
        self.tournament_panel.results_changed.connect(self.check_start)
        # Newest board load for the chosen tournament game.
        self._tournament_request = LatestRequest()
        # Key of the tournament game whose board is in ``game.data``, or None.
        self._tournament_board_key = None
        self._tournament_summary_text = ""
        # Whether the chosen tournament game can start; see
        # _check_tournament_start.
        self._tournament_ready = False
        footer_layout = QHBoxLayout()
        footer_layout.addStretch(5)
        footer_layout.addWidget(self.quit_button, 3)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.help_button, 3)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.tournament_button, 3)
        footer_layout.addStretch(5)
        main_layout.addStretch(3)
        main_layout.addLayout(self.icon_layout, 6)
        main_layout.addWidget(self.title_label, 3)
        main_layout.addWidget(self.version_label, 1)
        main_layout.addStretch(1)
        main_layout.addWidget(self.regular_workflow_widget, 5)
        main_layout.addWidget(self.tournament_panel, 16)
        main_layout.addStretch(1)
        main_layout.addWidget(self.summary_label, 7)
        main_layout.addWidget(self.rounds_widget, 4)
        main_layout.addWidget(self.advanced_options_checkbox, 1)
        main_layout.addWidget(self.advanced_boards, 7)
        main_layout.addWidget(self.reveal_answers_radio, 2)
        main_layout.addLayout(footer_layout, 3)
        main_layout.addStretch(3)
        self.summary_trigger.connect(self.set_summary)
        self.summary_load_result_trigger.connect(self.handle_summary_load_result)
        self.saved_game_result_trigger.connect(self.handle_saved_game_result)
        self.tournament_board_result_trigger.connect(
            self.handle_tournament_board_result
        )
        self.setLayout(main_layout)
        self.update_reveal_answers_after_triple_stumper(
            self.reveal_answers_radio.isChecked()
        )
        self.resizeEvent(None)
        self.sync_active_configuration()
        self.show()

    def show_help(self) -> None:
        """Show the built-in help dialog.

        Returns:
            ``None``.
        """
        logging.info("Showing help")
        msgbox = QMessageBox(
            QMessageBox.Icon.NoIcon,
            "JParty Help",
            helpmsg,
            QMessageBox.StandardButton.Ok,
            self,
        )
        msgbox.exec()

    def show_tournament_window(self) -> None:
        """Open the Tournament window, reusing it if already open.

        Returns:
            ``None``.
        """
        logging.info("Showing tournament window")
        if self.tournament_window is None:
            self.tournament_window = TournamentWindow(TOURNAMENTS_DIR, self)
            self.tournament_window.play_requested.connect(self.enter_tournament_mode)
        self.tournament_window.show()
        self.tournament_window.raise_()
        self.tournament_window.activateWindow()

    def resizeEvent(self, event: object) -> None:
        """Resize the game-id textbox to match the current layout.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        super().resizeEvent(event)
        textbox_height = int(self.gameid_label.height() * 0.8)
        self.textbox.setMinimumSize(QSize(0, textbox_height))
        f = self.textbox.font()
        f.setPixelSize(int(textbox_height * 0.9))
        self.textbox.setFont(f)
        checkbox_font_size = max(int(self.height() * 0.026), 22)
        checkbox_style = f"""
QCheckBox {{
    color: black;
    spacing: 0px;
    font-size: {checkbox_font_size}px;
    font-weight: 600;
}}
QCheckBox::indicator {{
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}}
"""
        rounds_label_font_size = max(int(self.height() * 0.022), 18)
        rounds_label_style = f"""
QLabel {{
    color: black;
    font-size: {rounds_label_font_size}px;
    font-weight: 700;
}}
"""
        radio_font_size = max(int(self.height() * 0.024), 18)
        self.reveal_answers_radio.setStyleSheet(
            f"""
QRadioButton {{
    color: black;
    font-size: {radio_font_size}px;
    font-weight: 600;
}}
"""
        )
        self.advanced_options_checkbox.setStyleSheet(
            f"""
QCheckBox {{
    color: black;
    font-size: {radio_font_size}px;
    font-weight: 700;
}}
"""
        )
        advanced_start_width = max(int(self.width() * 0.11), 150)
        self.advanced_start_button.setMinimumWidth(advanced_start_width)
        self.summary_label.setMaximumHeight(
            int(
                self.height()
                * (0.16 if self.advanced_options_checkbox.isChecked() else 0.28)
            )
        )
        self.advanced_boards.scroll.setMinimumHeight(int(self.height() * 0.26))
        self.advanced_boards.scroll.setMaximumHeight(int(self.height() * 0.42))
        for index in range(self.rounds_layout.count()):
            widget = self.rounds_layout.itemAt(index).widget()
            if isinstance(widget, QCheckBox):
                widget.setStyleSheet(checkbox_style)
            elif isinstance(widget, QLabel):
                widget.setStyleSheet(rounds_label_style)
        self.advanced_boards.apply_scale(self.height(), self.width())
        self.tournament_panel.apply_scale(self.height())
        self._size_footer_buttons()
        self.tournament_start_button.setMinimumSize(
            max(int(self.width() * 0.14), 150), max(int(self.height() * 0.06), 36)
        )

    def enter_tournament_mode(self, folder: object) -> bool:
        """Show a tournament's games in place of the regular game controls.

        Any prepared resume or loaded regular game is dropped. The host picks
        a game and its players on the panel, and Start plays that game.

        Args:
            folder: The tournament's folder.

        Returns:
            Whether the tournament could be read.
        """
        try:
            self.tournament_panel.load(Path(folder))
        except TournamentFileError as exc:
            logging.error("Couldn't open tournament %s: %s", folder, exc)
            QMessageBox.warning(self, "Couldn't open tournament", str(exc))
            return False
        logging.info("Playing tournament %s", folder)
        self.debounce_timer.stop()
        self._summary_request.cancel()
        self._loading_summary = False
        self.advanced_options_checkbox.setChecked(False)
        self.resume_path = None
        self.game.clear_resume_state()
        self.clear_round_selector()
        self.tournament_mode = True
        self._show_tournament_controls(True)
        self._clear_tournament_board()
        self.on_tournament_selection_changed()
        return True

    def leave_tournament_mode(self) -> None:
        """Go back to choosing a regular game.

        Returns:
            ``None``.
        """
        logging.info("Leaving tournament mode")
        self.tournament_mode = False
        self._tournament_request.cancel()
        self._clear_tournament_board()
        self.game.clear_resume_state()
        self._show_tournament_controls(False)
        self.show_summary(self)

    def _show_tournament_controls(self, shown: bool) -> None:
        """Swap the regular game controls for the tournament panel."""
        self.tournament_panel.setVisible(shown)
        self.regular_workflow_widget.setVisible(not shown)
        self.advanced_options_checkbox.setVisible(not shown)
        if shown:
            self.rounds_widget.setVisible(False)
            self.advanced_boards.setVisible(False)
        self.tournament_button.setEnabled(not shown)
        # Tournament games always reveal the answer after a triple stumper,
        # so every game is played the same way. Leaving restores the choice.
        self.reveal_answers_radio.setVisible(not shown)
        self.update_reveal_answers_after_triple_stumper(
            True if shown else self.reveal_answers_radio.isChecked()
        )
        self._size_footer_buttons()

    def _size_footer_buttons(self) -> None:
        """Keep the footer buttons readable while the tournament panel is up.

        The panel takes most of the screen's height, which would otherwise
        leave Quit, Show help, and Tournament only a few pixels tall.
        """
        height = max(int(self.height() * 0.045), 32) if self.tournament_mode else 0
        for button in (self.quit_button, self.help_button, self.tournament_button):
            button.setMinimumHeight(height)

    def _clear_tournament_board(self) -> None:
        """Forget any tournament board pushed into the game."""
        self._tournament_board_key = None
        self._tournament_summary_text = ""
        self.game.data = None
        if hasattr(self.game, "set_board_selection_configs"):
            self.game.set_board_selection_configs(None)
        if hasattr(self.game, "set_tournament_game"):
            self.game.set_tournament_game(None)

    def on_tournament_selection_changed(self) -> None:
        """Load the chosen game's board, then update Start.

        The board loads on a worker thread, since its source games may come
        from the network. Start stays off until it is in the game.

        Returns:
            ``None``.
        """
        if not self.tournament_mode:
            return
        key = self.tournament_panel.selected_key()
        board = self.tournament_panel.selected_board()
        if key is None or board is None:
            self._tournament_request.cancel()
            self._clear_tournament_board()
        elif key != self._tournament_board_key:
            self._clear_tournament_board()
            self._tournament_summary_text = "Loading the board..."
            request_id = self._tournament_request.begin()
            selections = [dict(selection) for selection in board.board_selections]
            self.loader.run_async(
                partial(self._load_tournament_board, request_id, key, selections)
            )
        self.check_start()

    def _load_tournament_board(
        self, request_id: int, key: str, selections: list[dict]
    ) -> None:
        """Build a tournament board's game on a worker thread."""
        try:
            data = build_game_from_board_selection_configs(selections)
            error = None
        except Exception as exc:  # noqa: BLE001 - shown to the host
            logging.exception("Couldn't load the board for %s", key)
            data, error = None, exc
        self.tournament_board_result_trigger.emit(request_id, key, data, error)

    def handle_tournament_board_result(
        self, request_id: int, key: str, data: object, error: object
    ) -> None:
        """Push a loaded tournament board into the game, if still wanted.

        Args:
            request_id: The load's request id.
            key: The game the board belongs to.
            data: The built game, or ``None`` if it couldn't be built.
            error: The error, if loading raised one.

        Returns:
            ``None``.
        """
        if not self.tournament_mode or not self._tournament_request.is_current(
            request_id
        ):
            return
        board = self.tournament_panel.selected_board()
        if self.tournament_panel.selected_key() != key or board is None:
            return
        if data is None or not data.rounds:
            detail = f": {error}" if error else ""
            self._tournament_summary_text = f"Couldn't load this game's board{detail}."
            self.check_start()
            return
        selections = [dict(selection) for selection in board.board_selections]
        self._push_composed_board(
            selections, data, composed_session_game_id(selections) or board.label
        )
        self._tournament_board_key = key
        daily_double_counts = [
            selection.get("daily_double_count")
            for selection in selections
            if selection.get("board_type") != "final"
        ]
        # A board taken as it aired has no counts; check it like a regular
        # game instead.
        if None in daily_double_counts:
            daily_double_counts = None
        self._tournament_summary_text = composed_board_summary_text(
            selections, data, daily_double_counts
        )
        self.check_start()

    def _tournament_phone_names(self) -> list[object]:
        """Return each connected phone's player name, in podium order."""
        players = sorted(
            getattr(self.game, "players", []) or [],
            key=lambda player: player.player_number,
        )
        return [player.name for player in players]

    def _check_tournament_start(self) -> None:
        """Enable Start once the chosen game, board, and phones are ready."""
        names = self._tournament_phone_names()
        self.tournament_panel.set_phones(names)
        problem = self.tournament_panel.problem(len(names))
        board_ready = (
            self._tournament_board_key is not None
            and self._tournament_board_key == self.tournament_panel.selected_key()
        )
        startable = bool(getattr(self.game, "startable", lambda: False)())
        enabled = problem is None and board_ready and startable
        # Kept apart from the button: the host window disables the whole
        # welcome screen while the introduction shows, and a button in a
        # disabled widget always reports itself disabled.
        self._tournament_ready = enabled
        self.tournament_start_button.setEnabled(enabled)
        if problem is None and not board_ready:
            problem = "Loading the board..."
        self.tournament_panel.show_status(problem or "Ready to start.", not enabled)
        self.summary_label.setText(self._tournament_summary_text)

    def start_tournament_game(self) -> None:
        """Start the chosen tournament game, after the introduction.

        The local-media preview opens first if the board has local media.
        Each step checks the game is still ready, since phones can join or
        leave while the introduction or preview is up.

        Returns:
            ``None``.
        """
        if not self._tournament_still_ready():
            return
        preview_questions = self.preview_questions()
        parent = self.parent()
        if preview_questions and hasattr(parent, "load_question_media_preview"):
            parent.load_question_media_preview(
                preview_questions, on_start=self._seat_and_start_tournament_game
            )
            return
        self._seat_and_start_tournament_game()

    def _seat_and_start_tournament_game(self) -> None:
        """Seat the chosen players on the phones and start the game.

        Podium ``i`` is the ``i``-th phone.
        """
        if not self._tournament_still_ready():
            return
        self.game.set_tournament_game(
            self.tournament_panel.game_ref(), self.tournament_panel.chosen_players()
        )
        self.update_reveal_answers_after_triple_stumper(True)
        self.game.start_game()

    def _tournament_still_ready(self) -> bool:
        """Re-check Start, and go back to the welcome screen if it's off.

        The lobby stays open until the game starts, so a phone may have
        joined or dropped since Start! was clicked. Seating then would log
        results under the wrong players. The status line says what's wrong.

        Returns:
            Whether the game can still start.
        """
        self.check_start()
        if self._tournament_ready:
            return True
        logging.warning(
            "Not starting the tournament game: %s",
            self.tournament_panel.status_label.text(),
        )
        parent = self.parent()
        if hasattr(parent, "show_welcome_from_preview"):
            parent.show_welcome_from_preview()
        return False

    def _begin_summary_request(self, loading: bool) -> int:
        """Invalidate any single-game load in flight and return a new request id.

        Every load result carries the id it was started with, and
        ``handle_summary_load_result`` drops results whose id is no longer
        current. Typing, Random, Load Saved, and toggling Advanced all call
        this, so a slow load can never overwrite newer state.

        Args:
            loading: Whether a new load is about to start or is waiting on the
                debounce timer. Start stays disabled while this is true.

        Returns:
            The new request id.
        """
        request_id = self._summary_request.begin()
        self._media_reload_warning = ""
        self._loading_summary = loading
        self.presenter.set_loading(loading)
        return request_id

    def _load_random_game(self, request_id: int) -> None:
        """Pick and load a random game on a worker thread.

        The worker only computes. It never touches ``self.game`` or widgets;
        ``handle_summary_load_result`` applies the result on the UI thread.
        It tries at most ``RANDOM_GAME_MAX_ATTEMPTS`` games and stops early
        once a newer request has replaced this one.

        Args:
            request_id: Id of the request this load belongs to.

        Returns:
            ``None``.
        """
        game_id, data, media_status = find_random_game_with_media(
            is_playable_game_data,
            lambda: not self._summary_request.is_current(request_id),
            RANDOM_GAME_MAX_ATTEMPTS,
        )
        error = None
        if not game_id:
            error = LookupError(
                random_game_failure_text(
                    "playable random game", RANDOM_GAME_MAX_ATTEMPTS
                )
            )
        self.summary_load_result_trigger.emit(
            request_id, game_id, data, error, media_status, True
        )

    def random(self, checked: object) -> None:
        """Begin asynchronously loading a random game.

        Args:
            checked: Button checked state supplied by Qt and otherwise ignored.

        Returns:
            ``None``.
        """
        self.debounce_timer.stop()
        self._clear_prepared_resume()
        request_id = self._begin_summary_request(loading=True)
        self.clear_round_selector()
        self.summary_trigger.emit("Loading...")
        self.check_start()
        self.loader.run_async(partial(self._load_random_game, request_id))

    def _load_summary_game(self, request_id: int, game_id: str) -> None:
        """Load one typed game id on a worker thread.

        The worker only computes. It never touches ``self.game`` or widgets;
        ``handle_summary_load_result`` applies the result on the UI thread.
        A failure is returned as a value and never cached, so the same id can
        be retried.

        Args:
            request_id: Id of the request this load belongs to.
            game_id: Game id to load.

        Returns:
            ``None``.
        """
        data = None
        error = None
        try:
            data = get_game(game_id)
        except Exception as exc:
            logging.error(exc)
            error = exc
        # Detect after parsing so a media zip that failed to extract during
        # the parse is reported to the host.
        media_status = detect_question_media(game_id)
        self.summary_load_result_trigger.emit(
            request_id, game_id, data, error, media_status, False
        )

    def reload_summary_game(self, game_id: str) -> None:
        """Parse the loaded regular-mode game again on a worker thread.

        Unlike ``show_summary``, the round selector is kept, so the host's
        round choices survive the reload. If the reload fails, the game that
        was already loaded is kept (see ``handle_summary_load_result``).

        Args:
            game_id: Game id to reload. It matches the textbox.

        Returns:
            ``None``.
        """
        self.debounce_timer.stop()
        request_id = self._begin_summary_request(loading=True)
        self._media_reload_request_id = request_id
        self.check_start()
        self.loader.run_async(partial(self._load_summary_game, request_id, game_id))

    def handle_summary_load_result(
        self,
        request_id: int,
        game_id: str,
        data: object,
        error: object,
        media_status: object,
        from_random: bool,
    ) -> None:
        """Apply a single-game load result on the UI thread if it is still current.

        Args:
            request_id: Id the load was started with.
            game_id: Game id that was loaded.
            data: Loaded game data, or ``None`` when the load failed.
            error: Exception raised by the load, or ``None``.
            media_status: Local question-media status for ``game_id``.
            from_random: Whether the load came from the Random button. If so,
                the textbox is updated to show the picked id.

        Returns:
            ``None``.
        """
        if not self._summary_request.is_current(request_id):
            return
        if self.advanced_options_checkbox.isChecked():
            return
        game_id = str(game_id).strip()
        if from_random and not game_id:
            self._handle_failed_random_load(error)
            return
        if from_random:
            if game_id:
                # Block signals so showing the picked id doesn't start a reload.
                self.textbox.blockSignals(True)
                self.textbox.setText(game_id)
                self.textbox.blockSignals(False)
        elif game_id != self.textbox.text().strip():
            return
        if self._keep_game_after_failed_media_reload(
            request_id, game_id, data, error, media_status
        ):
            return
        self._apply_summary_game(game_id, data, error, media_status)

    def _handle_failed_random_load(self, error: object) -> None:
        """Show that Random found no game, keeping the loaded game if any.

        Like advanced Random (#88), the game the textbox still names stays
        loaded and startable. Without one, the summary explains the failure.

        Args:
            error: Exception describing why no game was found.

        Returns:
            ``None``.
        """
        message = str(error or "Could not find a random game. Try again.")
        kept_game_id = self._loaded_summary_game_id
        if (
            kept_game_id
            and kept_game_id == self.textbox.text().strip()
            and self.game.valid_game()
        ):
            # Kept until the next load or action, like the media reload
            # warning, so round toggles (which rebuild the summary) keep it.
            self._media_reload_warning = f"{message} Kept game {kept_game_id}."
            self.set_summary(self.build_summary_text())
            self.check_start()
            return
        self._apply_summary_game("", None, None, None)
        self.set_summary(message)
        self.check_start()

    def _keep_game_after_failed_media_reload(
        self,
        request_id: int,
        game_id: str,
        data: object,
        error: object,
        media_status: object,
    ) -> bool:
        """Keep the loaded game when the reload after a media import fails.

        A media import reparses the loaded game to pick up the new image
        paths. For a Google Sheets game that means fetching the sheet again,
        and a network blip there must not throw away a game that already
        loaded (#66). The old game stays startable; it just won't show the
        new media until the host reloads it.

        Args:
            request_id: Id the load was started with.
            game_id: Game id that was loaded.
            data: Loaded game data, or ``None`` when the load failed.
            error: Exception raised by the load, or ``None``.
            media_status: Local question-media status for ``game_id``.

        Returns:
            ``True`` if the failed reload was handled by keeping the old game.
        """
        if request_id != self._media_reload_request_id:
            return False
        self._media_reload_request_id = None
        if error is None and is_playable_game_data(data):
            return False
        if game_id != self._loaded_summary_game_id or not self.game.valid_game():
            return False
        self._question_media_status = media_status
        # Kept until the next load or action, so round toggles (which rebuild
        # the summary) don't drop it.
        self._media_reload_warning = (
            "WARNING: Imported question media, but the game could not be "
            "reloaded to show it. Import the media again or re-enter the game "
            "id to retry."
        )
        self.set_summary(self.build_summary_text())
        self.check_start()
        return True

    def _apply_summary_game(
        self, game_id: str, data: object, error: object, media_status: object
    ) -> None:
        """Make one loaded (or failed) game the current regular-mode game.

        A failed or unplayable load clears ``game.data``, so the previous game
        can't be started under the new id.

        Args:
            game_id: Game id that was loaded, or ``""`` for an empty textbox.
            data: Loaded game data, or ``None``.
            error: Exception raised by the load, or ``None``.
            media_status: Local question-media status for ``game_id``.

        Returns:
            ``None``.
        """
        playable = error is None and is_playable_game_data(data)
        self.game.data = data if playable else None
        self._loaded_summary_game_id = game_id if playable else ""
        if hasattr(self.game, "set_session_game_id"):
            self.game.set_session_game_id(game_id if playable else "")
        self._question_media_status = media_status
        media_text = self.question_media_summary_text(game_id) if game_id else ""
        if not game_id:
            summary = ""
        elif error is not None:
            summary = "\n\n".join(["Cannot get game", media_text])
        elif not playable:
            summary = "\n\n".join(["Cannot load game", media_text])
        else:
            summary = self.build_summary_text()
        self.set_summary(summary)
        self.check_start()

    def _clear_prepared_resume(self) -> None:
        """Discard a prepared Load Saved resume and reset the Start button.

        Returns:
            ``None``.
        """
        if self.resume_path is None:
            return
        self.resume_path = None
        self.presenter.set_resume_path(None)
        self.game.clear_resume_state()
        self.start_button.setText("Start!")

    def build_summary_text(self) -> str:
        """Build the current welcome summary including load warnings.

        Returns:
            Summary text for the loaded game, including missing-clue warnings.
        """
        summary_data = self.summary_game_data()
        if not summary_data:
            return ""
        summary_lines = [summary_data.date, summary_data.comments]
        for warning in game_warning_lines(
            summary_data, self._summary_daily_double_counts()
        ):
            summary_lines.extend(["", warning])
        media_status = self.question_media_summary_text()
        if media_status:
            summary_lines.extend(["", media_status])
        if self._media_reload_warning:
            summary_lines.extend(["", self._media_reload_warning])
        return "\n".join(str(line) for line in summary_lines if line is not None)

    def _summary_daily_double_counts(self) -> list[int] | None:
        """Return the Daily Double counts the regular-mode summary expects.

        Each selected round is held to the count for its place in the source
        game, so unticking Jeopardy! still expects two in Double Jeopardy!.

        Returns:
            Expected counts for the selected standard rounds, or ``None`` in
            advanced mode or when the source game can't say.
        """
        data = getattr(self.game, "data", None)
        if not data or self.advanced_options_checkbox.isChecked():
            return None
        source_counts = getattr(data, "source_daily_double_counts", None)
        if source_counts is None:
            return None
        return source_counts(self.current_round_selection_indices())

    def summary_game_data(self) -> object:
        """Return the current game data shaped for welcome-screen summaries."""
        data = getattr(self.game, "data", None)
        if not data:
            return None
        if self.advanced_options_checkbox.isChecked():
            return data
        selected_indices = self.current_round_selection_indices()
        if not selected_indices:
            return GameData([], data.date, data.comments)
        selected_rounds = [
            data.rounds[index]
            for index in selected_indices
            if 0 <= index < len(data.rounds)
        ]
        return GameData(selected_rounds, data.date, data.comments)

    def current_round_selection_indices(self) -> list[int]:
        """Return the currently selected round indices from the checkbox UI."""
        if self.round_checkboxes:
            return [
                index
                for index, checkbox in enumerate(self.round_checkboxes)
                if checkbox.isChecked()
            ]
        selected_indices = getattr(self.game, "selected_round_indices", lambda: [])()
        if selected_indices:
            return selected_indices
        data = getattr(self.game, "data", None)
        if data is None:
            return []
        return list(range(len(data.rounds)))

    def question_media_summary_text(self, game_id: object = None) -> str:
        """Return a status line describing local question-media availability."""
        game_id = str(game_id if game_id is not None else self.textbox.text()).strip()
        if not game_id:
            return ""
        status = self._question_media_status
        if status is None:
            status = detect_question_media(game_id)
            if game_id == self.textbox.text().strip():
                self._question_media_status = status
        return status.summary_text()

    def set_summary(self, text: object) -> None:
        """Update the summary text shown on the welcome screen.

        Args:
            text: Summary text to display.

        Returns:
            ``None``.
        """
        self._base_summary_text = text
        self.presenter.set_summary_text(str(text))
        self.summary_label.setText(text)
        if text == "Loading...":
            return
        self._loading_summary = False
        self.presenter.set_loading(False)
        if self.advanced_options_checkbox.isChecked():
            self.rounds_widget.setVisible(False)
            return
        if self.resume_path is None and self.game.valid_game():
            self.configure_round_selector()
        elif self.resume_path is None:
            self.clear_round_selector()

    def toggle_advanced_options(self, _: object = None) -> None:
        """Show or hide the advanced Frankenstein-board controls."""
        enabled = self.advanced_options_checkbox.isChecked()
        self.presenter.set_advanced_enabled(enabled)
        # A single-game load in flight belongs to the mode being left.
        self.debounce_timer.stop()
        self._begin_summary_request(loading=False)
        # A prepared resume belongs to the regular-mode save. Advanced mode
        # builds a new board, so starting it must not write into that save.
        self._clear_prepared_resume()
        if not enabled:
            self.clear_advanced_configuration()
        self.advanced_boards.setVisible(enabled)
        self.regular_workflow_widget.setVisible(not enabled)
        if enabled:
            self.rounds_widget.setVisible(False)
        else:
            self.rounds_widget.setVisible(bool(self.round_checkboxes))
            if self.round_checkboxes:
                self.rounds_widget.show()
        if enabled:
            self.summary_label.setWordWrap(True)
            self.summary_label.setMaximumHeight(int(self.height() * 0.16))
        else:
            self.summary_label.setMaximumHeight(int(self.height() * 0.28))
        self.resizeEvent(None)
        self.sync_active_configuration()

    def clear_advanced_configuration(self) -> None:
        """Discard advanced configuration and reset the welcome screen."""
        self._advanced_mode_summary_text = ""
        self.advanced_boards.reset()
        self.resume_path = None
        self._loading_summary = False
        self._question_media_status = None
        self._base_summary_text = ""
        self.summary_label.setText("")
        self.textbox.blockSignals(True)
        self.textbox.setText("")
        self.textbox.blockSignals(False)
        self.game.data = None
        self.start_button.setText("Start!")
        self.start_button.setEnabled(False)
        self.clear_round_selector()
        self.rounds_widget.setVisible(False)
        self.game.clear_resume_state()
        if hasattr(self.game, "set_board_selection_configs"):
            self.game.set_board_selection_configs(None)
        if hasattr(self.game, "set_session_game_id"):
            self.game.set_session_game_id("")

    def sync_active_configuration(self) -> None:
        """Push either the regular or advanced startup config into the game.

        In tournament mode the chosen tournament board is already in the
        game, so only Start is updated.
        """
        if self.tournament_mode:
            self.check_start()
            return
        if self.advanced_options_checkbox.isChecked():
            self.sync_advanced_configuration()
            return
        self.sync_regular_configuration()

    def sync_regular_configuration(self) -> None:
        """Persist the standard single-game startup selection as board configs.

        The game is composed here from the already-loaded ``game.data`` and
        cached with ``set_composed_game_data``, so Start never fetches or
        parses the source game again on the UI thread.
        """
        if self.resume_path is not None:
            return
        game_id = self.textbox.text().strip()
        if not game_id or not getattr(self.game, "data", None):
            if hasattr(self.game, "set_board_selection_configs"):
                self.game.set_board_selection_configs(None)
            if hasattr(self.game, "set_session_game_id"):
                self.game.set_session_game_id(game_id)
            return
        selected_indices = getattr(self.game, "selected_round_indices", lambda: [])()
        if not selected_indices:
            if hasattr(self.game, "set_board_selection_configs"):
                self.game.set_board_selection_configs(None)
            return
        source_data = self.game.data
        board_selections = []
        resolved_boards = []
        for round_index in (int(index) for index in selected_indices):
            if not 0 <= round_index < len(source_data.rounds):
                continue
            selection = original_board_selection(game_id, source_data, round_index)
            board_selections.append(selection)
            resolved_boards.append(
                (selection, source_data, source_data.rounds[round_index])
            )
        if hasattr(self.game, "set_board_selection_configs"):
            self.game.set_board_selection_configs(board_selections)
        if hasattr(self.game, "set_composed_game_data"):
            self.game.set_composed_game_data(
                board_selections,
                compose_game_from_resolved_board_selections(resolved_boards),
            )
        if hasattr(self.game, "set_session_game_id"):
            self.game.set_session_game_id(game_id)

    def sync_advanced_configuration(self) -> None:
        """Push the advanced editor's board into the game and the summary."""
        setup = self.advanced_boards.current_setup()
        board_selections = list(setup.board_selections)
        # A partial board set is never a playable game, so ``game.data`` stays
        # empty until every row is filled.
        self._push_composed_board(
            board_selections,
            setup.composed_data,
            self.compose_session_game_id(board_selections),
            complete=setup.complete,
        )
        if setup.ready:
            self._advanced_mode_summary_text = setup.summary_text()
            self.summary_label.setText(self._advanced_mode_summary_text)
        elif self.advanced_options_checkbox.isChecked():
            self._advanced_mode_summary_text = (
                "Fill every board slot before starting the Frankenstein game."
            )
            self.summary_label.setText(self._advanced_mode_summary_text)
        self.check_start()

    def _push_composed_board(
        self,
        board_selections: list[dict],
        data: object,
        session_game_id: str,
        complete: bool = True,
    ) -> None:
        """Put a composed board into the game, ready for Start.

        Used by both advanced mode and tournament games, so Start sees the
        same game state whichever built the board.

        Args:
            board_selections: The board's selections, one per round.
            data: The composed game, or ``None`` if it isn't built yet.
            session_game_id: The id saves and logs use for this board.
            complete: Whether every selection is filled. An incomplete set
                is kept out of the game's board configuration.

        Returns:
            ``None``.
        """
        configs = board_selections if complete else None
        if hasattr(self.game, "set_board_selection_configs"):
            self.game.set_board_selection_configs(configs)
        if hasattr(self.game, "set_session_game_id"):
            self.game.set_session_game_id(session_game_id)
        if hasattr(self.game, "set_selected_round_indices"):
            self.game.set_selected_round_indices(list(range(len(board_selections))))
        self.game.data = data
        if hasattr(self.game, "set_composed_game_data"):
            self.game.set_composed_game_data(configs, data)

    def compose_session_game_id(self, board_selections: list[dict]) -> str:
        """Return the save/log identifier for the current board composition."""
        return composed_session_game_id(board_selections) or self.textbox.text().strip()

    def start_debounce_timer(self, text: object) -> None:
        """Start the debounce timer whenever the text changes."""
        if self.advanced_options_checkbox.isChecked():
            return
        self._clear_prepared_resume()
        # Typing invalidates any load in flight and keeps Start disabled until
        # the typed id has loaded.
        self._begin_summary_request(loading=True)
        self._question_media_status = None
        self.clear_round_selector()
        self.check_start()
        self.debounce_timer.start(2000)

    def debounced_show_summary(self) -> None:
        """Call show_summary with the current text after debounce period."""
        self.show_summary(self.textbox.text())

    def show_summary(self, text: object = None) -> None:
        """Begin asynchronously loading the current game's summary information.

        Args:
            text: Optional text value from the signal connection; ignored
                because the textbox state is read directly.

        Returns:
            ``None``.
        """
        if self.advanced_options_checkbox.isChecked():
            self.sync_active_configuration()
            return
        self.debounce_timer.stop()
        self._clear_prepared_resume()
        game_id = self.textbox.text().strip()
        self.clear_round_selector()
        if not game_id:
            self._begin_summary_request(loading=False)
            self._apply_summary_game("", None, None, None)
            return
        request_id = self._begin_summary_request(loading=True)
        self.summary_trigger.emit("Loading...")
        self.check_start()
        self.loader.run_async(partial(self._load_summary_game, request_id, game_id))

    def on_start_clicked(self, checked: object = False) -> None:
        """Start the game or open the local-media preview when available.

        The configuration is synced again first, and nothing happens unless
        Start is enabled for the current mode afterwards. So a click that
        lands while a row reloads, a load is pending, or a point value is
        invalid can't start a partial game.
        """
        self.sync_active_configuration()
        self.check_start()
        if self.tournament_mode:
            if not self._tournament_ready:
                return
            parent = self.parent()
            if hasattr(parent, "load_contestant_intro"):
                parent.load_contestant_intro(
                    self.tournament_panel.intro_lines(), self.start_tournament_game
                )
                return
            self.start_tournament_game()
            return
        active_start_button = (
            self.advanced_start_button
            if self.advanced_options_checkbox.isChecked()
            else self.start_button
        )
        if not active_start_button.isEnabled():
            return
        if self.resume_path is None:
            preview_questions = self.preview_questions()
            if preview_questions and hasattr(
                self.parent(), "load_question_media_preview"
            ):
                self.parent().load_question_media_preview(preview_questions)
                return
        self.game.start_game()

    def load_question_media(self, checked: object = False) -> None:
        """Import question media for the currently typed game id."""
        game_id = self.textbox.text().strip()
        if not game_id:
            QMessageBox.warning(
                self,
                "Question Media",
                "Enter a game id before loading question media.",
            )
            return
        selected_path = self.select_question_media_path()
        if not selected_path:
            return
        try:
            import_question_media(selected_path, game_id)
        except Exception as e:
            logging.error(e)
            QMessageBox.warning(self, "Question Media", str(e))
            return
        self._question_media_status = detect_question_media(game_id)
        if self._loading_summary and not self._summary_request.is_current(
            self._media_reload_request_id
        ):
            # A load (or the debounce before one) is pending, and ``game.data``
            # still holds the previous game. Show only the new media status;
            # ``set_summary`` would end the loading state and let Start play
            # the previous game under this id (#72). The pending load detects
            # the media again when it finishes.
            loading_text = "\n\n".join(
                text
                for text in ["Loading...", self.question_media_summary_text(game_id)]
                if text
            )
            self._base_summary_text = loading_text
            self.summary_label.setText(loading_text)
            self.check_start()
            return
        if (
            self.resume_path is None
            and not self.advanced_options_checkbox.isChecked()
            and game_id == self._loaded_summary_game_id
        ):
            # Image paths are set when the game is parsed, and Start reuses the
            # loaded game, so parse it again to pick up the new media.
            self.reload_summary_game(game_id)
            return
        if self.game.valid_game():
            self.set_summary(self.build_summary_text())
        else:
            self.set_summary(self.question_media_summary_text(game_id))

    def select_question_media_path(self) -> str:
        """Open a dialog that allows choosing a directory or zip file."""
        return choose_question_media_path(self)

    def load_saved_game(self, checked: object = False) -> None:
        """Prompt for a saved game folder and read it on a worker thread.

        Reading a save can fetch its game from J-Archive or Google Sheets, so
        it runs through ``self.loader`` like the other loads, and
        ``handle_saved_game_result`` applies it on the UI thread.

        Args:
            checked: Button checked state supplied by Qt and otherwise ignored.

        Returns:
            ``None``.
        """
        selected_dir = QFileDialog.getExistingDirectory(
            self, "Select Saved Game Folder", str(GAME_STATES_DIR)
        )
        if not selected_dir:
            return
        # Drop any single-game load in flight so it can't replace this resume,
        # and keep Start off until the save has loaded.
        self.debounce_timer.stop()
        self._clear_prepared_resume()
        request_id = self._begin_summary_request(loading=True)
        self.clear_round_selector()
        self.summary_trigger.emit("Loading...")
        self.check_start()
        self.loader.run_async(partial(self._read_saved_game, request_id, selected_dir))

    def _read_saved_game(self, request_id: int, selected_dir: str) -> None:
        """Read one saved game folder on a worker thread.

        The worker only reads. ``Game.read_saved_game`` never changes the
        game, and ``handle_saved_game_result`` applies the save on the UI
        thread.

        Args:
            request_id: Id of the request this load belongs to.
            selected_dir: Saved game folder picked by the host.

        Returns:
            ``None``.
        """
        loaded = None
        error = None
        try:
            loaded = self.game.read_saved_game(selected_dir)
        except Exception as exc:
            logging.error(exc)
            error = exc
        self.saved_game_result_trigger.emit(request_id, selected_dir, loaded, error)

    def handle_saved_game_result(
        self, request_id: int, selected_dir: str, loaded: object, error: object
    ) -> None:
        """Apply a Load Saved result on the UI thread if it is still current.

        A failed read leaves the game untouched, so the screen is refreshed
        from the textbox like any other load.

        Args:
            request_id: Id the load was started with.
            selected_dir: Saved game folder picked by the host.
            loaded: Save returned by ``Game.read_saved_game``, or ``None``.
            error: Exception raised while reading the save, or ``None``.

        Returns:
            ``None``.
        """
        if not self._summary_request.is_current(request_id):
            return
        if self.advanced_options_checkbox.isChecked():
            return
        if error is None:
            try:
                resume_state = self.game.apply_saved_game(loaded)
            except Exception as exc:
                logging.error(exc)
                error = exc
        if error is not None:
            QMessageBox.warning(self, "Saved Game Error", str(error))
            self.show_summary()
            return
        self._loading_summary = False
        # The save replaced the game the textbox named, so it no longer
        # counts as loaded (a failed Random must not "keep" it as that id).
        self._loaded_summary_game_id = ""
        self.resume_path = selected_dir
        self.presenter.set_resume_path(selected_dir)
        self.start_button.setText("Resume!")
        saved_players = resume_state["general_state"].get("players", [])
        self.reveal_answers_radio.setChecked(
            bool(
                resume_state["general_state"].get(
                    "reveal_answers_after_triple_stumper", False
                )
            )
        )
        # Use the indices the game loaded, which point into its rounds.
        self.configure_round_selector(
            selected_indices=self.game.selected_round_indices(), enabled=True
        )
        self._base_summary_text = "\n".join(
            [
                f"Resume game {resume_state['game_id']} from:",
                selected_dir,
                "",
                self.game.data.date,
                self.game.data.comments,
                "",
                f"Saved players: {len(saved_players)}",
            ]
        )
        self.check_start()

    def check_start(self) -> None:
        """Enable or disable the start button based on current readiness.

        Returns:
            ``None``.
        """
        if self.tournament_mode:
            self._check_tournament_start()
            return
        self.presenter.set_advanced_enabled(self.advanced_options_checkbox.isChecked())
        self.presenter.set_resume_path(self.resume_path)
        self.presenter.set_summary_text(self._base_summary_text)
        self.presenter.set_loading(self._loading_summary)
        state = self.presenter.sync_from_game()
        if state.status_text:
            self.summary_label.setText(state.status_text)
        self.start_button.setEnabled(state.start_enabled)
        self.advanced_start_button.setEnabled(state.start_enabled)

    def restart(self) -> None:
        """Reset the welcome screen to its initial fresh-game state.

        Returns:
            ``None``.
        """
        self.resume_path = None
        self._base_summary_text = ""
        self._question_media_status = None
        self.game.clear_resume_state()
        self.start_button.setText("Start!")
        self.advanced_options_checkbox.setChecked(False)
        self.clear_round_selector()
        if self.tournament_mode:
            # Back from a tournament game: show what's been played since.
            self._clear_tournament_board()
            self.tournament_panel.reload()
            self.on_tournament_selection_changed()
            return
        self.show_summary(self)

    def update_reveal_answers_after_triple_stumper(self, checked: bool) -> None:
        """Push the triple-stumper reveal option into the active game object."""
        setter = getattr(self.game, "set_reveal_answers_after_triple_stumper", None)
        if setter is not None:
            setter(checked)

    def clear_round_selector(self) -> None:
        """Remove any existing round-selection checkboxes.

        Returns:
            ``None``.
        """
        while self.rounds_layout.count():
            item = self.rounds_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.round_checkboxes = []
        self.rounds_widget.setVisible(False)
        if hasattr(self.game, "set_selected_round_indices"):
            self.game.set_selected_round_indices(None)

    def configure_round_selector(
        self, selected_indices: object = None, enabled: bool = True
    ) -> None:
        """Populate the round-selection UI from the loaded game data.

        Args:
            selected_indices: Optional iterable of selected round indices.
            enabled: Whether the host can edit the round selection.

        Returns:
            ``None``.
        """
        if selected_indices is None:
            if self.round_checkboxes:
                selected_indices = [
                    index
                    for index, checkbox in enumerate(self.round_checkboxes)
                    if checkbox.isChecked()
                ]
            else:
                selected_indices = getattr(
                    self.game, "selected_round_indices", lambda: []
                )()
                if not selected_indices and getattr(self.game, "data", None):
                    selected_indices = list(range(len(self.game.data.rounds)))
        self.clear_round_selector()
        if not getattr(self.game, "data", None):
            return
        if selected_indices is None:
            selected_indices = list(range(len(self.game.data.rounds)))
        selected_indices = {int(index) for index in selected_indices}
        rounds_label = QLabel("Rounds to play:", self.rounds_widget)
        rounds_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rounds_label.setStyleSheet(ROUNDS_LABEL_STYLE)
        self.rounds_layout.addWidget(rounds_label)
        saved_labels = self.resumed_board_labels()
        for index in range(len(self.game.data.rounds)):
            checkbox = QCheckBox("", self.rounds_widget)
            checkbox.setProperty(
                "round_label",
                saved_labels[index]
                if saved_labels
                else describe_source_round(self.game.data, index),
            )
            checkbox.setStyleSheet(ROUND_CHECKBOX_STYLE)
            checkbox.setChecked(index in selected_indices)
            checkbox.setEnabled(enabled)
            checkbox.stateChanged.connect(self.update_selected_rounds)
            self.rounds_layout.addWidget(checkbox)
            self.round_checkboxes.append(checkbox)
        self.rounds_widget.setVisible(True)
        self.update_selected_rounds()

    def resumed_board_labels(self) -> list[str] | None:
        """Return source-round labels for a resumed regular-mode subset save.

        Such a save resumes on the game built from its ticked rounds, so
        position labels would call a Double Jeopardy board "Jeopardy!" when
        Jeopardy was skipped. Each saved board selection records the label
        of the source round it came from.

        Returns:
            One label per loaded round when resuming a save whose board
            selections are the loaded rounds, all from the saved game, or
            ``None`` to label rounds by position.
        """
        if self.resume_path is None or not getattr(self.game, "data", None):
            return None
        selections = getattr(self.game, "board_selection_configs", lambda: [])()
        if not selections or len(selections) != len(self.game.data.rounds):
            return None
        game_id = str(getattr(self.game, "current_game_id", lambda: "")()).strip()
        labels = []
        for selection in selections:
            label = selection.get("source_round_label")
            if not label or str(selection.get("game_id", "")).strip() != game_id:
                return None
            labels.append(str(label))
        return labels

    def update_selected_rounds(self) -> None:
        """Push the current checkbox selection into the game object.

        Returns:
            ``None``.
        """
        for checkbox in self.round_checkboxes:
            round_label = checkbox.property("round_label") or checkbox.text()
            checkbox.setText(f"[{'x' if checkbox.isChecked() else ' '}] {round_label}")
        selected_indices = [
            index
            for index, checkbox in enumerate(self.round_checkboxes)
            if checkbox.isChecked()
        ]
        if hasattr(self.game, "set_selected_round_indices"):
            self.game.set_selected_round_indices(selected_indices)
        self.sync_regular_configuration()
        summary_text = self.build_summary_text()
        self._base_summary_text = summary_text
        self.presenter.set_summary_text(summary_text)
        self.summary_label.setText(summary_text)
        self.check_start()

    def preview_questions(self) -> list[tuple[int, object]]:
        """Return local-media-backed questions from the selected rounds."""
        if self.advanced_options_checkbox.isChecked():
            return local_media_questions(self.game, range(len(self.game.data.rounds)))
        return local_media_questions(self.game, self.game.selected_round_indices())


class ContestantIntro(StartWidget):
    """The host's introduction of a tournament game's players.

    Shown on the host screen after Start, before the game begins, so the
    host can read each player's introduction aloud.
    """

    def __init__(
        self,
        lines: list[str],
        on_back: object,
        on_start: object,
        parent: object = None,
    ) -> None:
        """Show ``lines``: a heading, then one line per player.

        Args:
            lines: The introduction, heading first.
            on_back: Called by Back, to return to the welcome screen.
            on_start: Called by Start Game.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.lines = list(lines)
        main_layout = QVBoxLayout()
        main_layout.addStretch(1)
        main_layout.addLayout(self.icon_layout, 3)
        heading = self.lines[0] if self.lines else ""
        self.title_label = DynamicLabel(heading, lambda: self.height() * 0.07, self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.title_label, 2)
        self.line_labels = []
        for line in self.lines[1:]:
            label = DynamicLabel(line, lambda: self.height() * 0.045, self)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            main_layout.addWidget(label, 2)
            self.line_labels.append(label)
        button_layout = QHBoxLayout()
        button_layout.addStretch(3)
        self.back_button = DynamicButton("Back", self)
        self.back_button.clicked.connect(on_back)
        button_layout.addWidget(self.back_button, 2)
        button_layout.addStretch(1)
        self.start_button = DynamicButton("Start Game", self)
        self.start_button.clicked.connect(on_start)
        button_layout.addWidget(self.start_button, 2)
        button_layout.addStretch(3)
        main_layout.addLayout(button_layout, 2)
        main_layout.addStretch(1)
        self.setLayout(main_layout)


class QuestionMediaPreview(StartWidget):
    """Host-side preview of imported local question media before game start."""

    def __init__(
        self,
        game: object,
        preview_questions: list[tuple[int, object]],
        on_back: object,
        on_start: object,
        parent: object = None,
    ) -> None:
        """Initialize the preview widget."""
        super().__init__(parent)
        self.game = game
        self.preview_questions = preview_questions
        self.on_back = on_back
        self.on_start = on_start
        self.cards = []
        self.setPalette(WINDOWPAL)
        main_layout = QVBoxLayout()
        main_layout.addStretch(1)
        main_layout.addLayout(self.icon_layout, 3)
        self.title_label = DynamicLabel(
            "Question Media Preview", lambda: self.height() * 0.08, self
        )
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.title_label, 1)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            """
QScrollArea {
    background: #f7f7f7;
    border: 1px solid #d8d8d8;
}
QScrollArea > QWidget > QWidget {
    background: #f7f7f7;
}
QScrollBar:vertical {
    background: #e0e0e0;
    width: 18px;
    margin: 0px;
    border-left: 1px solid #c6c6c6;
}
QScrollBar::handle:vertical {
    background: #9a9a9a;
    min-height: 36px;
    border-radius: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background: #7f7f7f;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: #e0e0e0;
    height: 0px;
}
"""
        )
        self.scroll_container = QWidget(self.scroll_area)
        self.scroll_container.setAutoFillBackground(True)
        self.scroll_container.setPalette(WINDOWPAL)
        self.grid_layout = QGridLayout(self.scroll_container)
        self.grid_layout.setSpacing(18)
        self.scroll_area.setWidget(self.scroll_container)
        self.populate_cards()
        main_layout.addWidget(self.scroll_area, 10)
        button_layout = QHBoxLayout()
        button_layout.addStretch(3)
        self.back_button = DynamicButton("Back", self)
        self.back_button.clicked.connect(self.on_back)
        button_layout.addWidget(self.back_button, 2)
        button_layout.addStretch(1)
        self.start_button = DynamicButton("Start Game", self)
        self.start_button.clicked.connect(self.on_start)
        button_layout.addWidget(self.start_button, 2)
        button_layout.addStretch(3)
        main_layout.addLayout(button_layout, 2)
        main_layout.addStretch(1)
        self.setLayout(main_layout)

    def populate_cards(self) -> None:
        """Render the preview grid."""
        column_count = 3
        for item_index, (_, question) in enumerate(self.preview_questions):
            row = item_index // column_count
            column = item_index % column_count
            card = self.build_card(question)
            self.cards.append(card)
            self.grid_layout.addWidget(card, row, column)

    def build_card(self, question: object) -> QWidget:
        """Create one preview card containing the image and answer."""
        card = QWidget(self.scroll_container)
        card.setAutoFillBackground(True)
        card.setPalette(WINDOWPAL)
        layout = QVBoxLayout()
        image_label = QLabel(card)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setMinimumHeight(180)
        image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        if is_local_media_path(question.image_url):
            pixmap = QPixmap(str(question.image_url))
            if not pixmap.isNull():
                image_label.setPixmap(
                    pixmap.scaled(
                        320,
                        220,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                image_label.setText(Path(question.image_url).name)
        else:
            image_label.setText("Missing local media")
        answer_label = QLabel(question.answer, card)
        answer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        answer_label.setWordWrap(True)
        answer_label.setStyleSheet("QLabel { color: black; font-size: 18px; }")
        layout.addWidget(image_label, 6)
        layout.addWidget(answer_label, 2)
        card.setLayout(layout)
        return card


class QRWidget(StartWidget):
    """Audience-side startup screen that shows the buzzer join QR code."""

    def __init__(self, host: object, parent: object = None) -> None:
        """Initialize the QR join screen.

        Args:
            host: Hostname or address players should visit to join.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.font = QFont()
        self.font.setPointSize(30)
        main_layout = QVBoxLayout()
        self.hint_label = DynamicLabel("Scan for Buzzer:", self.start_fontsize, self)
        self.hint_label.setFont(self.font)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qrlabel = QLabel(self)
        self.qrlabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.url = "http://" + host
        self.url_label = DynamicLabel(self.url, self.start_fontsize, self)
        self.url_label.setFont(self.font)
        self.url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addStretch(1)
        main_layout.addLayout(self.icon_layout, 5)
        main_layout.addWidget(self.hint_label, 2)
        main_layout.addWidget(self.qrlabel, 5)
        main_layout.addWidget(self.url_label, 2)
        main_layout.addStretch(1)
        self.setLayout(main_layout)
        self.show()

    def start_fontsize(self) -> object:
        """Return the starting font size for QR-screen labels.

        Returns:
            A font size derived from the current widget width.
        """
        return 0.1 * self.width()

    def resizeEvent(self, event: object) -> None:
        """Regenerate the QR code pixmap to fit the current widget size.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        super().resizeEvent(event)
        self.qrlabel.setPixmap(
            qrcode.make(
                self.url, image_factory=Image, box_size=max(self.height() // 50, 1)
            ).pixmap()
        )

    def restart(self) -> None:
        """Reset the QR screen state when returning to the lobby.

        Returns:
            ``None``.
        """
        pass
