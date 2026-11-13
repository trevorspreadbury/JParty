"""Lobby and startup widgets for game selection and buzzer joining.

This module contains the welcome-screen widgets used to choose or resume a
game, plus the QR-code display shown on the audience screen so players can join
the buzzer web app.
"""

import logging
import time
from functools import partial
from pathlib import Path

import qrcode
from PyQt6.QtCore import QDir, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QFont, QImage, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from jparty import __version__ as version
from jparty.app.helptext import helpmsg
from jparty.app.paths import GAME_STATES_DIR
from jparty.domain.models import FinalBoard, GameData
from jparty.services.game_loader import (
    clone_round,
    compose_game_from_resolved_board_selections,
    default_board_row_values,
    get_game,
    get_random_game,
    normalize_standard_board_daily_doubles,
    original_board_row_values,
    round_matches_board_type,
    select_advanced_daily_double_indices,
    standard_board_daily_double_indices,
)
from jparty.services.question_media import (
    detect_question_media,
    import_question_media,
    is_local_media_path,
    local_media_questions,
)
from jparty.ui.styles import WINDOWPAL
from jparty.ui.welcome_loader import WelcomeLoader
from jparty.ui.welcome_presenter import WelcomePresenter
from jparty.ui.widgets.common import (
    DynamicButton,
    DynamicLabel,
    add_shadow,
    resource_path,
)

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

STANDARD_ROUND_LABELS = [
    "Jeopardy!",
    "Double Jeopardy!",
    "Triple Jeopardy!",
]

MISSING_DAILY_DOUBLE_WARNING = "CRITICAL: Missing Daily Double"
ADVANCED_BOARD_SLOT_COUNT_MIN = 1
ADVANCED_BOARD_SLOT_COUNT_MAX = 5
ADVANCED_STANDARD_VALUE_COUNT = 5
ADVANCED_FINAL_BOARD_SLOT_COUNT_MIN = 0
ADVANCED_DAILY_DOUBLE_COUNT_MIN = 0
ADVANCED_DAILY_DOUBLE_COUNT_MAX = 6
ADVANCED_ROW_DEBOUNCE_MS = 2000
# Random games a row's Random button tries before giving up.
ADVANCED_RANDOM_MAX_ATTEMPTS = 10
QUESTION_INDEX_PART_COUNT = 2


def _is_playable_game_data(data: object) -> bool:
    """Return whether loaded game data has at least one playable round."""
    return data is not None and bool(getattr(data, "rounds", None))


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
    # (row_index, request_id, game_id, data, media_status)
    advanced_row_load_result_trigger = pyqtSignal(int, int, object, object, object)
    advanced_row_random_result_trigger = pyqtSignal(int, int, object, object, object)
    # (request_id, game_id, data, error, media_status, from_random)
    summary_load_result_trigger = pyqtSignal(int, str, object, object, object, bool)

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
        self._summary_request_id = 0
        # Request id of a reload started by a media import, or ``None``.
        self._media_reload_request_id = None
        # Shown in the summary after a failed media reload kept the old game.
        self._media_reload_warning = ""
        # Id of the game currently in ``game.data`` in regular mode, or "".
        self._loaded_summary_game_id = ""
        self._question_media_status = None
        self.round_checkboxes = []
        self._advanced_rows = []
        self._advanced_game_cache = {}
        self._advanced_media_status_cache = {}
        # Shared by all rows, so a result can never match a rebuilt row.
        self._advanced_request_counter = 0
        self._advanced_mode_summary_text = ""
        self._resetting_advanced_configuration = False
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
        self.advanced_controls_widget = QWidget(self)
        self.advanced_controls_layout = QVBoxLayout()
        self.advanced_controls_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.advanced_controls_widget.setLayout(self.advanced_controls_layout)
        self.advanced_controls_widget.setVisible(False)
        advanced_header_layout = QHBoxLayout()
        self.standard_board_count_label = QLabel(
            "Jeopardy Boards:", self.advanced_controls_widget
        )
        self.standard_board_count_spinbox = QSpinBox(self.advanced_controls_widget)
        self.standard_board_count_spinbox.setRange(
            ADVANCED_BOARD_SLOT_COUNT_MIN, ADVANCED_BOARD_SLOT_COUNT_MAX
        )
        self.standard_board_count_spinbox.setValue(2)
        self.standard_board_count_spinbox.valueChanged.connect(
            self.rebuild_advanced_rows
        )
        self.final_board_count_label = QLabel(
            "Final Boards:", self.advanced_controls_widget
        )
        self.final_board_count_spinbox = QSpinBox(self.advanced_controls_widget)
        self.final_board_count_spinbox.setRange(
            ADVANCED_FINAL_BOARD_SLOT_COUNT_MIN, ADVANCED_BOARD_SLOT_COUNT_MAX
        )
        self.final_board_count_spinbox.setValue(1)
        self.final_board_count_spinbox.valueChanged.connect(self.rebuild_advanced_rows)
        advanced_header_layout.addWidget(self.standard_board_count_label)
        advanced_header_layout.addWidget(self.standard_board_count_spinbox)
        advanced_header_layout.addSpacing(20)
        advanced_header_layout.addWidget(self.final_board_count_label)
        advanced_header_layout.addWidget(self.final_board_count_spinbox)
        advanced_header_layout.addSpacing(20)
        self.advanced_start_button = DynamicButton(
            "Start!", self.advanced_controls_widget
        )
        self.advanced_start_button.clicked.connect(self.on_start_clicked)
        self.advanced_start_button.setEnabled(False)
        advanced_header_layout.addWidget(self.advanced_start_button)
        advanced_header_layout.addStretch(1)
        self.advanced_controls_layout.addLayout(advanced_header_layout)
        self.advanced_scroll = QScrollArea(self.advanced_controls_widget)
        self.advanced_scroll.setWidgetResizable(True)
        self.advanced_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.advanced_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.advanced_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.advanced_rows_widget = QWidget(self.advanced_scroll)
        self.advanced_rows_layout = QVBoxLayout()
        self.advanced_rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.advanced_rows_widget.setLayout(self.advanced_rows_layout)
        self.advanced_scroll.setWidget(self.advanced_rows_widget)
        self.advanced_controls_layout.addWidget(self.advanced_scroll)
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
        footer_layout = QHBoxLayout()
        footer_layout.addStretch(5)
        footer_layout.addWidget(self.quit_button, 3)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.help_button, 3)
        footer_layout.addStretch(5)
        main_layout.addStretch(3)
        main_layout.addLayout(self.icon_layout, 6)
        main_layout.addWidget(self.title_label, 3)
        main_layout.addWidget(self.version_label, 1)
        main_layout.addStretch(1)
        main_layout.addWidget(self.regular_workflow_widget, 5)
        main_layout.addStretch(1)
        main_layout.addWidget(self.summary_label, 7)
        main_layout.addWidget(self.rounds_widget, 4)
        main_layout.addWidget(self.advanced_options_checkbox, 1)
        main_layout.addWidget(self.advanced_controls_widget, 7)
        main_layout.addWidget(self.reveal_answers_radio, 2)
        main_layout.addLayout(footer_layout, 3)
        main_layout.addStretch(3)
        self.summary_trigger.connect(self.set_summary)
        self.advanced_row_load_result_trigger.connect(
            self.handle_advanced_row_load_result
        )
        self.advanced_row_random_result_trigger.connect(
            self.handle_advanced_row_random_result
        )
        self.summary_load_result_trigger.connect(self.handle_summary_load_result)
        self.setLayout(main_layout)
        self.update_reveal_answers_after_triple_stumper(
            self.reveal_answers_radio.isChecked()
        )
        self.rebuild_advanced_rows()
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
        self.standard_board_count_label.setStyleSheet(
            f"QLabel {{ color: black; font-size: {radio_font_size}px; font-weight: 700; }}"
        )
        self.standard_board_count_spinbox.setStyleSheet(
            f"QSpinBox {{ font-size: {radio_font_size}px; min-height: {radio_font_size + 10}px; }}"
        )
        self.final_board_count_label.setStyleSheet(
            f"QLabel {{ color: black; font-size: {radio_font_size}px; font-weight: 700; }}"
        )
        self.final_board_count_spinbox.setStyleSheet(
            f"QSpinBox {{ font-size: {radio_font_size}px; min-height: {radio_font_size + 10}px; }}"
        )
        advanced_start_width = max(int(self.width() * 0.11), 150)
        self.advanced_start_button.setMinimumWidth(advanced_start_width)
        self.summary_label.setMaximumHeight(
            int(
                self.height()
                * (0.16 if self.advanced_options_checkbox.isChecked() else 0.28)
            )
        )
        self.advanced_scroll.setMinimumHeight(int(self.height() * 0.26))
        self.advanced_scroll.setMaximumHeight(int(self.height() * 0.42))
        for index in range(self.rounds_layout.count()):
            widget = self.rounds_layout.itemAt(index).widget()
            if isinstance(widget, QCheckBox):
                widget.setStyleSheet(checkbox_style)
            elif isinstance(widget, QLabel):
                widget.setStyleSheet(rounds_label_style)
        advanced_status_font_size = max(int(self.height() * 0.018), 14)
        advanced_value_font_size = max(int(self.height() * 0.02), 14)
        advanced_gameid_width = min(max(int(self.width() * 0.18), 180), 260)
        advanced_action_width = min(max(int(self.width() * 0.11), 130), 180)
        advanced_value_width = min(max(int(self.width() * 0.055), 60), 85)
        for row in self._advanced_rows:
            row["title_label"].setStyleSheet(
                f"QLabel {{ color: black; font-size: {radio_font_size}px; font-weight: 700; }}"
            )
            row["status_label"].setStyleSheet(
                f"QLabel {{ color: #333333; font-size: {advanced_status_font_size}px; }}"
            )
            row["gameid_edit"].setStyleSheet(
                f"QLineEdit {{ font-size: {advanced_value_font_size}px; }}"
            )
            row["gameid_edit"].setMinimumWidth(advanced_gameid_width)
            row["gameid_edit"].setMaximumWidth(advanced_gameid_width)
            row["random_button"].setMinimumWidth(advanced_action_width)
            row["random_button"].setMaximumWidth(advanced_action_width)
            row["load_media_button"].setMinimumWidth(advanced_action_width)
            row["load_media_button"].setMaximumWidth(advanced_action_width)
            for value_edit in row["value_edits"]:
                value_edit.setStyleSheet(
                    f"QLineEdit {{ font-size: {advanced_value_font_size}px; min-width: {advanced_value_width}px; }}"
                )
                value_edit.setMaximumWidth(advanced_value_width)
            if row["daily_double_spinbox"] is not None:
                row["daily_double_spinbox"].setStyleSheet(
                    f"QSpinBox {{ font-size: {advanced_value_font_size}px; min-height: {advanced_value_font_size + 10}px; }}"
                )
            for button in row["board_radios"]:
                button.setStyleSheet(
                    f"QRadioButton {{ color: black; font-size: {advanced_status_font_size}px; font-weight: 600; }}"
                )

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
        self._summary_request_id += 1
        self._media_reload_warning = ""
        self._loading_summary = loading
        self.presenter.set_loading(loading)
        return self._summary_request_id

    def _load_random_game(self, request_id: int) -> None:
        """Pick and load a random game on a worker thread.

        The worker only computes. It never touches ``self.game`` or widgets;
        ``handle_summary_load_result`` applies the result on the UI thread.

        Args:
            request_id: Id of the request this load belongs to.

        Returns:
            ``None``.
        """
        game_id = ""
        data = None
        error = None
        try:
            # Stop picking games once a newer request has replaced this one.
            while request_id == self._summary_request_id:
                game_id = str(get_random_game())
                logging.info(f"GAMEID {game_id}")
                data = get_game(game_id)
                if _is_playable_game_data(data):
                    break
                time.sleep(0.25)
        except Exception as exc:
            logging.error(exc)
            data = None
            error = exc
        media_status = detect_question_media(game_id) if game_id else None
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
        if request_id != self._summary_request_id:
            return
        if self.advanced_options_checkbox.isChecked():
            return
        game_id = str(game_id).strip()
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
        if error is None and _is_playable_game_data(data):
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
        playable = error is None and _is_playable_game_data(data)
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
        missing_question_count = getattr(
            summary_data, "missing_question_count", lambda: 0
        )()
        if missing_question_count:
            summary_lines.extend(
                [
                    "",
                    f"WARNING: Missing {missing_question_count} question"
                    f"{'' if missing_question_count == 1 else 's'}",
                ]
            )
        has_missing_daily_double = getattr(
            summary_data, "has_missing_daily_double", lambda *_: False
        )(self._summary_daily_double_counts())
        if has_missing_daily_double:
            summary_lines.extend(["", MISSING_DAILY_DOUBLE_WARNING])
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
        self.advanced_controls_widget.setVisible(enabled)
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

    def rebuild_advanced_rows(self, _: object = None) -> None:
        """Recreate the advanced board rows for the selected board count."""
        row_snapshots = (
            {"standard": [], "final": []}
            if self._resetting_advanced_configuration
            else self.snapshot_advanced_rows()
        )
        while self.advanced_rows_layout.count():
            item = self.advanced_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._advanced_rows = []
        standard_board_count = self.standard_board_count_spinbox.value()
        final_board_count = self.final_board_count_spinbox.value()
        for board_index in range(standard_board_count):
            self._add_advanced_row(
                board_index=board_index,
                board_count=standard_board_count,
                board_type="standard",
                display_index=board_index + 1,
            )
        for board_index in range(final_board_count):
            self._add_advanced_row(
                board_index=board_index,
                board_count=final_board_count,
                board_type="final",
                display_index=board_index + 1,
            )
        self.restore_advanced_rows(row_snapshots)
        self.resizeEvent(None)
        self.sync_active_configuration()

    def snapshot_advanced_rows(self) -> dict[str, list[dict]]:
        """Return the current advanced row state grouped by slot type."""
        snapshots = {"standard": [], "final": []}
        for row in self._advanced_rows:
            board_type = row["board_type"]
            selected_round_index = next(
                (
                    int(radio.property("source_round_index"))
                    for radio in row["board_radios"]
                    if radio.isChecked()
                ),
                None,
            )
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
                    "selected_round_index": selected_round_index,
                    "daily_double_count": (
                        row["daily_double_spinbox"].value()
                        if row.get("daily_double_spinbox") is not None
                        else None
                    ),
                    "daily_double_indices": [
                        list(index) for index in row.get("daily_double_indices", [])
                    ],
                    "daily_double_source_round_index": row.get(
                        "daily_double_source_round_index"
                    ),
                }
            )
        return snapshots

    def restore_advanced_rows(self, snapshots: dict[str, list[dict]]) -> None:
        """Restore preserved advanced row state after resizing slot counts."""
        row_positions = {"standard": 0, "final": 0}
        for row in self._advanced_rows:
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
                self.reload_advanced_row(row["index"], snapshot)

    def advanced_row_selection(self, row: dict) -> dict:
        """Return one row's selected round and Daily Double layout.

        Args:
            row: Advanced row state.

        Returns:
            A dictionary that ``reload_advanced_row`` can re-apply.
        """
        return {
            "selected_round_index": next(
                (
                    int(radio.property("source_round_index"))
                    for radio in row["board_radios"]
                    if radio.isChecked()
                ),
                None,
            ),
            "daily_double_indices": [
                list(index) for index in row.get("daily_double_indices", [])
            ],
            "daily_double_source_round_index": row.get(
                "daily_double_source_round_index"
            ),
        }

    def reload_advanced_row(self, row_index: int, selection: object = None) -> None:
        """Load one row's source game again on a worker thread.

        Args:
            row_index: Index of the advanced row.
            selection: Optional result of ``advanced_row_selection`` (or a row
                snapshot) to re-apply once the game has loaded, so the row
                keeps its round and Daily Doubles.

        Returns:
            ``None``.
        """
        if not 0 <= row_index < len(self._advanced_rows):
            return
        row = self._advanced_rows[row_index]
        row["load_timer"].stop()
        self._clear_advanced_row_loaded_state(row)
        row["pending_selection"] = selection
        self.load_advanced_row_async(row_index)

    def clear_advanced_configuration(self) -> None:
        """Discard advanced configuration and reset the welcome screen."""
        self._resetting_advanced_configuration = True
        self._advanced_game_cache = {}
        self._advanced_media_status_cache = {}
        self._advanced_mode_summary_text = ""
        self.standard_board_count_spinbox.setValue(2)
        self.final_board_count_spinbox.setValue(1)
        self.rebuild_advanced_rows()
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
        self._resetting_advanced_configuration = False

    def _add_advanced_row(
        self, board_index: int, board_count: int, board_type: str, display_index: int
    ) -> None:
        """Create one advanced configuration row."""
        row_widget = QWidget(self.advanced_rows_widget)
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
                value_edit.editingFinished.connect(self.sync_active_configuration)
                values_layout.addWidget(value_edit)
                value_edits.append(value_edit)
            controls_layout.addWidget(values_widget, 1, 1, 1, 3)
            controls_layout.addWidget(QLabel("Daily Doubles", row_widget), 2, 0)
            daily_double_spinbox = QSpinBox(row_widget)
            daily_double_spinbox.setRange(
                ADVANCED_DAILY_DOUBLE_COUNT_MIN, ADVANCED_DAILY_DOUBLE_COUNT_MAX
            )
            daily_double_spinbox.setValue(min(board_index + 1, 2))
            daily_double_spinbox.valueChanged.connect(self.sync_active_configuration)
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
            "index": len(self._advanced_rows),
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
            "load_request_id": 0,
            "loading": False,
            "status_label": status_label,
            "loaded_data": None,
            "pending_selection": None,
        }
        row_index = row["index"]
        load_timer.timeout.connect(partial(self.load_advanced_row_async, row_index))
        gameid_edit.textChanged.connect(
            partial(self.start_advanced_row_debounce_timer, row_index)
        )
        gameid_edit.returnPressed.connect(partial(self.refresh_advanced_row, row_index))
        random_button.clicked.connect(partial(self.random_advanced_row, row_index))
        load_media_button.clicked.connect(
            partial(self.load_advanced_question_media, row_index)
        )
        self._advanced_rows.append(row)
        self.advanced_rows_layout.addWidget(row_widget)

    def default_values_for_board(self, board_index: int, board_count: int) -> list[int]:
        """Return the default clue values shown for one advanced board row."""
        return default_board_row_values(board_index, board_count)

    def start_advanced_row_debounce_timer(
        self, row_index: int, _: object = None
    ) -> None:
        """Debounce advanced row source-game loading while typing."""
        if not 0 <= row_index < len(self._advanced_rows):
            return
        row = self._advanced_rows[row_index]
        row["load_timer"].stop()
        self._clear_advanced_row_loaded_state(row)
        # Typing drops any load in flight, including a row Random.
        self._next_advanced_request_id(row)
        if not row["gameid_edit"].text().strip():
            row["status_label"].setText("Enter a source game id.")
            self.sync_active_configuration()
            return
        row["load_timer"].start(ADVANCED_ROW_DEBOUNCE_MS)
        row["status_label"].setText("Loading...")
        self.sync_active_configuration()

    def _clear_advanced_row_loaded_state(self, row: dict) -> None:
        """Clear one advanced row's loaded selection state."""
        row["loaded_data"] = None
        row["loading"] = False
        row["daily_double_indices"] = []
        row["daily_double_source_round_index"] = None
        row["pending_selection"] = None
        self._clear_advanced_row_radios(row)

    def load_advanced_row_async(self, row_index: int) -> None:
        """Load one advanced row's source game on a worker thread."""
        if not 0 <= row_index < len(self._advanced_rows):
            return
        row = self._advanced_rows[row_index]
        game_id = row["gameid_edit"].text().strip()
        if not game_id:
            row["status_label"].setText("Enter a source game id.")
            self.sync_active_configuration()
            return
        request_id = self._next_advanced_request_id(row)
        row["loading"] = True
        row["status_label"].setText("Loading...")
        if (
            game_id in self._advanced_game_cache
            and game_id in self._advanced_media_status_cache
        ):
            row["loading"] = False
            self._apply_advanced_row_loaded_data(
                row_index,
                game_id,
                self._advanced_game_cache.get(game_id),
                self._advanced_media_status_cache.get(game_id),
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
            self.advanced_row_load_result_trigger.emit(
                row_index, request_id, game_id, data, media_status
            )

        self.loader.run_async(_load)

    def _next_advanced_request_id(self, row: dict) -> int:
        """Invalidate any load in flight for ``row`` and return a new request id.

        Args:
            row: Advanced row state.

        Returns:
            The row's new request id.
        """
        self._advanced_request_counter += 1
        row["load_request_id"] = self._advanced_request_counter
        return row["load_request_id"]

    def _cache_advanced_game(
        self, game_id: str, data: object, media_status: object
    ) -> None:
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
        self._advanced_game_cache[game_id] = data
        self._advanced_media_status_cache[game_id] = media_status

    def handle_advanced_row_load_result(
        self,
        row_index: int,
        request_id: int,
        game_id: object,
        data: object,
        media_status: object,
    ) -> None:
        """Apply one advanced row's async load result if it is still current."""
        if not 0 <= row_index < len(self._advanced_rows):
            return
        row = self._advanced_rows[row_index]
        if request_id != row["load_request_id"]:
            return
        if str(game_id).strip() != row["gameid_edit"].text().strip():
            return
        row["loading"] = False
        self._cache_advanced_game(str(game_id).strip(), data, media_status)
        self._apply_advanced_row_loaded_data(
            row_index, str(game_id).strip(), data, media_status
        )

    def refresh_advanced_row(self, row_index: int) -> None:
        """Load one advanced row's source game now (Enter key).

        Skips the debounce. The load runs on a worker thread unless the game
        is already cached.
        """
        self.reload_advanced_row(row_index)

    def _apply_advanced_row_loaded_data(
        self, row_index: int, game_id: str, data: object, media_status: object
    ) -> None:
        """Apply loaded game data and rebuild one advanced row's radios."""
        if not 0 <= row_index < len(self._advanced_rows):
            return
        row = self._advanced_rows[row_index]
        pending_selection = row.get("pending_selection") or {}
        row["pending_selection"] = None
        if data is None:
            row["status_label"].setText(
                "\n".join(
                    [
                        "Cannot load game",
                        media_status.summary_text() if media_status else "",
                    ]
                ).strip()
            )
            self.sync_active_configuration()
            return
        matching_rounds = [
            (round_index, round_data)
            for round_index, round_data in enumerate(data.rounds)
            if round_matches_board_type(round_data, row["board_type"])
        ]
        if not matching_rounds:
            expected_label = self.expected_board_type_label(row["board_type"])
            row["status_label"].setText(
                "\n".join(
                    [
                        self.build_source_game_summary_text(
                            game_id, data, media_status
                        ),
                        "",
                        f"No {expected_label} found in this source game.",
                    ]
                ).strip()
            )
            self.sync_active_configuration()
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
        for radio_index, (round_index, round_data) in enumerate(matching_rounds):
            radio = QRadioButton(
                self.describe_round_for_data(data, round_data, round_index),
                row["board_radio_widget"],
            )
            radio.setProperty("source_round_index", round_index)
            radio.setChecked(radio_index == default_selection)
            radio.clicked.connect(self.sync_active_configuration)
            row["board_radio_group"].addButton(radio)
            row["board_radio_layout"].addWidget(radio)
            row["board_radios"].append(radio)
        if matching_rounds:
            selected_round_index = matching_rounds[default_selection][0]
            row["status_label"].setText(
                self.build_source_game_summary_text(
                    game_id,
                    data,
                    media_status,
                    selected_round_index=selected_round_index,
                )
            )
        self.resizeEvent(None)
        self.sync_active_configuration()

    def random_advanced_row(self, row_index: int, checked: object = False) -> None:
        """Load a random source game into one advanced row on a worker thread.

        The worker tries at most ``ADVANCED_RANDOM_MAX_ATTEMPTS`` games and
        stops early once a newer load for the row has started. If every try
        fails, the game the row had loaded before is restored (see
        ``handle_advanced_row_random_result``).
        """
        if not 0 <= row_index < len(self._advanced_rows):
            return
        row = self._advanced_rows[row_index]
        row["load_timer"].stop()
        previous_game_id = row["gameid_edit"].text().strip()
        row["random_fallback"] = (
            (previous_game_id, self.advanced_row_selection(row))
            if previous_game_id and row.get("loaded_data") is not None
            else None
        )
        self._clear_advanced_row_loaded_state(row)
        request_id = self._next_advanced_request_id(row)
        row["loading"] = True
        row["status_label"].setText("Loading...")
        self.sync_active_configuration()
        board_type = row["board_type"]

        def _load() -> None:
            game_id = ""
            data = None
            for _ in range(ADVANCED_RANDOM_MAX_ATTEMPTS):
                if request_id != row["load_request_id"]:
                    return
                try:
                    candidate_id = str(get_random_game())
                    candidate = get_game(candidate_id)
                except Exception as exc:
                    logging.error(exc)
                    continue
                if candidate is not None and any(
                    round_matches_board_type(round_data, board_type)
                    for round_data in candidate.rounds
                ):
                    game_id, data = candidate_id, candidate
                    break
            media_status = detect_question_media(game_id) if game_id else None
            self.advanced_row_random_result_trigger.emit(
                row_index, request_id, game_id, data, media_status
            )

        self.loader.run_async(_load)

    def handle_advanced_row_random_result(
        self,
        row_index: int,
        request_id: int,
        game_id: object,
        data: object,
        media_status: object,
    ) -> None:
        """Apply one row's Random result on the UI thread if it is still current.

        Args:
            row_index: Index of the advanced row.
            request_id: Id the load was started with.
            game_id: Picked game id, or ``""`` when every attempt failed.
            data: Loaded game data, or ``None``.
            media_status: Local question-media status for ``game_id``.

        Returns:
            ``None``.
        """
        if not 0 <= row_index < len(self._advanced_rows):
            return
        row = self._advanced_rows[row_index]
        if request_id != row["load_request_id"]:
            return
        row["loading"] = False
        fallback = row.pop("random_fallback", None)
        game_id = str(game_id).strip()
        if not game_id:
            expected_label = self.expected_board_type_label(row["board_type"])
            failure_text = (
                f"Could not find a random game with a {expected_label} after "
                f"{ADVANCED_RANDOM_MAX_ATTEMPTS} tries. Try again."
            )
            if (
                fallback is not None
                and fallback[0] == row["gameid_edit"].text().strip()
            ):
                # Put back the game the row had before Random, keeping its
                # round and Daily Doubles. It is usually cached, so this is
                # immediate; otherwise it reloads on the worker thread.
                previous_game_id, selection = fallback
                self.reload_advanced_row(row_index, selection)
                if not row["loading"]:
                    row["status_label"].setText(
                        "\n\n".join(
                            [
                                row["status_label"].text(),
                                f"{failure_text} Kept game {previous_game_id}.",
                            ]
                        )
                    )
                return
            row["status_label"].setText(failure_text)
            self.sync_active_configuration()
            return
        self._cache_advanced_game(game_id, data, media_status)
        # Block signals so showing the picked id doesn't start a reload.
        row["gameid_edit"].blockSignals(True)
        row["gameid_edit"].setText(game_id)
        row["gameid_edit"].blockSignals(False)
        self._apply_advanced_row_loaded_data(row_index, game_id, data, media_status)

    def load_advanced_question_media(
        self, row_index: int, checked: object = False
    ) -> None:
        """Import question media for one advanced row's source game id."""
        if not 0 <= row_index < len(self._advanced_rows):
            return
        row = self._advanced_rows[row_index]
        game_id = row["gameid_edit"].text().strip()
        if not game_id:
            QMessageBox.warning(
                self,
                "Question Media",
                "Enter a game id for this advanced board before loading question media.",
            )
            return
        selected_path = self.select_question_media_path()
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
        self._advanced_game_cache.pop(game_id, None)
        self._advanced_media_status_cache.pop(game_id, None)
        for other_row in self._advanced_rows:
            if other_row["gameid_edit"].text().strip() == game_id:
                self.reload_advanced_row(
                    other_row["index"], self.advanced_row_selection(other_row)
                )

    def expected_board_type_label(self, board_type: str) -> str:
        """Return the user-facing label for an advanced slot type."""
        return "Final Jeopardy board" if board_type == "final" else "Jeopardy board"

    def _clear_advanced_row_radios(self, row: dict) -> None:
        """Remove any previous round-selection radios from one advanced row."""
        for radio in row["board_radios"]:
            row["board_radio_group"].removeButton(radio)
        while row["board_radio_layout"].count():
            item = row["board_radio_layout"].takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        row["board_radios"] = []

    def describe_round_for_data(
        self, game_data: object, round_data: object, index: int
    ) -> str:
        """Return a user-facing label for a round in an arbitrary game payload."""
        if isinstance(round_data, FinalBoard):
            return "Final Jeopardy!"
        standard_round_index = sum(
            1
            for prior_round in game_data.rounds[:index]
            if not isinstance(prior_round, FinalBoard)
        )
        if standard_round_index < len(STANDARD_ROUND_LABELS):
            return STANDARD_ROUND_LABELS[standard_round_index]
        return f"Round {standard_round_index + 1}"

    def build_standard_board_selection(
        self,
        game_id: str,
        round_data: object,
        source_round_index: int,
        source_round_label: str,
        row_values: list[int],
        requested_daily_double_count: int | None = None,
        existing_daily_double_indices: object = None,
    ) -> dict:
        """Return one standard-board selection with stable Daily Double coords."""
        round_copy = clone_round(round_data)
        normalize_standard_board_daily_doubles(
            round_copy,
            requested_count=requested_daily_double_count,
            daily_double_indices=existing_daily_double_indices,
        )
        daily_double_indices = standard_board_daily_double_indices(round_copy)
        return {
            "game_id": game_id,
            "source_round_index": int(source_round_index),
            "source_round_label": source_round_label,
            "board_type": "standard",
            "row_values": list(row_values),
            "daily_double_count": len(daily_double_indices),
            "daily_double_indices": daily_double_indices,
        }

    def sync_active_configuration(self) -> None:
        """Push either the regular or advanced startup config into the game."""
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
        for round_index in selected_indices:
            if not 0 <= int(round_index) < len(source_data.rounds):
                continue
            round_data = source_data.rounds[int(round_index)]
            row_values = original_board_row_values(source_data, int(round_index))
            if isinstance(round_data, FinalBoard):
                selection = {
                    "game_id": game_id,
                    "source_round_index": int(round_index),
                    "source_round_label": self.describe_round(
                        round_data, int(round_index)
                    ),
                    "board_type": "final",
                    "row_values": row_values,
                }
            else:
                selection = self.build_standard_board_selection(
                    game_id=game_id,
                    round_data=round_data,
                    source_round_index=int(round_index),
                    source_round_label=self.describe_round(
                        round_data, int(round_index)
                    ),
                    row_values=row_values,
                    requested_daily_double_count=round_data.daily_double_count(),
                    existing_daily_double_indices=standard_board_daily_double_indices(
                        round_data
                    ),
                )
            board_selections.append(selection)
            resolved_boards.append((selection, source_data, round_data))
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
        """Build and apply the current advanced Frankenstein-board selection."""
        board_selections = []
        resolved_boards = []
        requested_daily_double_counts = []
        for row in self._advanced_rows:
            game_id = row["gameid_edit"].text().strip()
            if not game_id or row["loaded_data"] is None:
                continue
            selected_round_index = next(
                (
                    int(radio.property("source_round_index"))
                    for radio in row["board_radios"]
                    if radio.isChecked()
                ),
                None,
            )
            if selected_round_index is None:
                continue
            try:
                row_values = [int(edit.text()) for edit in row["value_edits"]]
            except ValueError:
                row["status_label"].setText(
                    "Point values must be whole numbers for this board slot."
                )
                continue
            source_round_label = next(
                (radio.text() for radio in row["board_radios"] if radio.isChecked()),
                "",
            )
            media_status = self._advanced_media_status_cache.get(game_id)
            row["status_label"].setText(
                self.build_source_game_summary_text(
                    game_id,
                    row["loaded_data"],
                    media_status,
                    selected_round_index=selected_round_index,
                )
            )
            if row["board_type"] == "final":
                selection = {
                    "game_id": game_id,
                    "source_round_index": selected_round_index,
                    "source_round_label": source_round_label,
                    "board_type": row["board_type"],
                    "row_values": row_values,
                }
                board_selections.append(selection)
                resolved_boards.append(
                    (
                        selection,
                        row["loaded_data"],
                        row["loaded_data"].rounds[selected_round_index],
                    )
                )
                continue
            source_round = row["loaded_data"].rounds[selected_round_index]
            existing_daily_double_indices = (
                row.get("daily_double_indices")
                if row.get("daily_double_source_round_index") == selected_round_index
                else None
            )
            baseline_daily_double_indices = select_advanced_daily_double_indices(
                source_round,
                row["daily_double_spinbox"].value(),
                existing_daily_double_indices=existing_daily_double_indices,
            )
            selection = self.build_standard_board_selection(
                game_id=game_id,
                round_data=source_round,
                source_round_index=selected_round_index,
                source_round_label=source_round_label,
                row_values=row_values,
                requested_daily_double_count=row["daily_double_spinbox"].value(),
                existing_daily_double_indices=baseline_daily_double_indices,
            )
            row["daily_double_indices"] = [
                tuple(index) for index in selection.get("daily_double_indices", [])
            ]
            row["daily_double_source_round_index"] = selected_round_index
            requested_daily_double_counts.append(row["daily_double_spinbox"].value())
            board_selections.append(selection)
            resolved_boards.append((selection, row["loaded_data"], source_round))
        configuration_complete = len(board_selections) == len(self._advanced_rows)
        if hasattr(self.game, "set_board_selection_configs"):
            self.game.set_board_selection_configs(
                board_selections if configuration_complete else None
            )
        session_game_id = self.compose_session_game_id(board_selections)
        if hasattr(self.game, "set_session_game_id"):
            self.game.set_session_game_id(session_game_id)
        if hasattr(self.game, "set_selected_round_indices"):
            self.game.set_selected_round_indices(list(range(len(board_selections))))
        composed_data = compose_game_from_resolved_board_selections(resolved_boards)
        self.game.data = composed_data
        if hasattr(self.game, "set_composed_game_data"):
            self.game.set_composed_game_data(
                board_selections if configuration_complete else None,
                composed_data if configuration_complete else None,
            )
        if configuration_complete and composed_data is not None:
            self._advanced_mode_summary_text = self.build_advanced_summary_text(
                board_selections, composed_data, requested_daily_double_counts
            )
            self.summary_label.setText(self._advanced_mode_summary_text)
        elif self.advanced_options_checkbox.isChecked():
            self._advanced_mode_summary_text = (
                "Fill every board slot before starting the Frankenstein game."
            )
            self.summary_label.setText(self._advanced_mode_summary_text)
        self.check_start()

    def compose_session_game_id(self, board_selections: list[dict]) -> str:
        """Return the save/log identifier for the current board composition."""
        source_ids = [
            str(selection.get("game_id", "")).strip() for selection in board_selections
        ]
        source_ids = [game_id for game_id in source_ids if game_id]
        if not source_ids:
            return self.textbox.text().strip()
        if len(set(source_ids)) == 1:
            return source_ids[0]
        return "frankenstein-" + "-".join(source_ids)

    def build_source_game_summary_text(
        self,
        game_id: str,
        data: object,
        media_status: object,
        selected_round_index: int | None = None,
    ) -> str:
        """Return one advanced row's summary text."""
        summary_data = data
        if selected_round_index is not None and 0 <= selected_round_index < len(
            data.rounds
        ):
            summary_data = GameData(
                [data.rounds[selected_round_index]], data.date, data.comments
            )
        summary_lines = [f"{game_id}: {summary_data.date}", str(summary_data.comments)]
        missing_question_count = getattr(
            summary_data, "missing_question_count", lambda: 0
        )()
        if missing_question_count:
            summary_lines.append(f"Missing questions: {missing_question_count}")
        expected_daily_doubles = None
        if summary_data is not data:
            # One round picked from the source: hold it to its own place there.
            expected_daily_doubles = data.source_daily_double_counts(
                [selected_round_index]
            )
        if getattr(summary_data, "has_missing_daily_double", lambda *_: False)(
            expected_daily_doubles
        ):
            summary_lines.append(MISSING_DAILY_DOUBLE_WARNING)
        if media_status is not None:
            summary_lines.append(media_status.summary_text())
        return "\n".join(line for line in summary_lines if line)

    def build_advanced_summary_text(
        self,
        board_selections: list[dict],
        composed_data: object,
        requested_daily_double_counts: object = None,
    ) -> str:
        """Return the summary text for the current Frankenstein composition.

        Args:
            board_selections: Board selections in play order.
            composed_data: Game composed from ``board_selections``.
            requested_daily_double_counts: Daily Double count the host asked
                for on each standard board, in order. The missing-Daily-Double
                warning compares against these instead of the regular-game
                rule.

        Returns:
            Summary text for the advanced-mode summary label.
        """
        summary_lines = [composed_data.date, composed_data.comments, ""]
        standard_index = 0
        final_index = 0
        for selection in board_selections:
            values = ", ".join(str(value) for value in selection.get("row_values", []))
            if selection.get("board_type") == "final":
                final_index += 1
                board_label = f"Final {final_index}"
                suffix = ""
            else:
                standard_index += 1
                board_label = f"Board {standard_index}"
                suffix = (
                    f", DDs: {selection.get('daily_double_count', 0)}"
                    if selection.get("daily_double_count") is not None
                    else ""
                )
            summary_lines.append(
                f"{board_label}: {selection.get('game_id')} - {selection.get('source_round_label')}"
                + (f" ({values}{suffix})" if values or suffix else "")
            )
        missing_question_count = getattr(
            composed_data, "missing_question_count", lambda: 0
        )()
        if missing_question_count:
            summary_lines.extend(
                [
                    "",
                    f"WARNING: Missing {missing_question_count} question"
                    f"{'' if missing_question_count == 1 else 's'}",
                ]
            )
        if composed_data.has_missing_daily_double(requested_daily_double_counts):
            summary_lines.extend(["", MISSING_DAILY_DOUBLE_WARNING])
        return "\n".join(str(line) for line in summary_lines if line is not None)

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
        """Start the game or open the local-media preview when available."""
        self.sync_active_configuration()
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
        dialog = QFileDialog(self, "Select Question Media")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        dialog.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        dialog.setNameFilter("Zip archives (*.zip);;All directories and files (*)")
        if dialog.exec():
            selected_files = dialog.selectedFiles()
            if selected_files:
                return selected_files[0]
        return ""

    def load_saved_game(self, checked: object = False) -> None:
        """Prompt for and prepare a saved game session to resume.

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
        # Drop any single-game load in flight so it can't replace this resume.
        self.debounce_timer.stop()
        self._begin_summary_request(loading=False)
        try:
            resume_state = self.game.prepare_resume_from_dir(selected_dir)
        except Exception as e:
            logging.error(e)
            QMessageBox.warning(self, "Saved Game Error", str(e))
            return
        self.resume_path = selected_dir
        self.presenter.set_resume_path(selected_dir)
        self.start_button.setText("Resume!")
        self.advanced_options_checkbox.setChecked(False)
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
        self.presenter.set_advanced_enabled(self.advanced_options_checkbox.isChecked())
        self.presenter.set_resume_path(self.resume_path)
        self.presenter.set_summary_text(self._base_summary_text)
        self.presenter.set_loading(self._loading_summary)
        state = self.presenter.sync_from_game()
        if state.status_text:
            self.summary_label.setText(state.status_text)
        self.start_button.setEnabled(state.start_enabled)
        self.advanced_start_button.setEnabled(state.advanced_start_enabled)

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
        for index, round_data in enumerate(self.game.data.rounds):
            checkbox = QCheckBox("", self.rounds_widget)
            checkbox.setProperty(
                "round_label",
                saved_labels[index]
                if saved_labels
                else self.describe_round(round_data, index),
            )
            checkbox.setStyleSheet(ROUND_CHECKBOX_STYLE)
            checkbox.setChecked(index in selected_indices)
            checkbox.setEnabled(enabled)
            checkbox.stateChanged.connect(self.update_selected_rounds)
            self.rounds_layout.addWidget(checkbox)
            self.round_checkboxes.append(checkbox)
        self.rounds_widget.setVisible(True)
        self.update_selected_rounds()

    def describe_round(self, round_data: object, index: int) -> str:
        """Return a user-facing label for a game round.

        Args:
            round_data: Round object being described.
            index: Zero-based round index within the loaded game data.

        Returns:
            Human-readable round label for the checkbox UI.
        """
        return self.describe_round_for_data(self.game.data, round_data, index)

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
