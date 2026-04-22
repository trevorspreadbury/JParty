"""Lobby and startup widgets for game selection and buzzer joining.

This module contains the welcome-screen widgets used to choose or resume a
game, plus the QR-code display shown on the audience screen so players can join
the buzzer web app.
"""

import logging
import time
from threading import Thread

import qrcode
from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QFont, QImage, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jparty import __version__ as version
from jparty.app.helptext import helpmsg
from jparty.domain.models import FinalBoard
from jparty.services.game_loader import get_game, get_random_game
from jparty.ui.styles import WINDOWPAL
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
    font-size: 16px;
    font-weight: 600;
}
QCheckBox::indicator {
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}
"""


class Image(qrcode.image.base.BaseImage):
    """Adapter that renders QR codes into Qt image objects."""

    def __init__(self, border: object, width: object, box_size: object) -> None:
        """Initialize the QR image buffer.

        Args:
            border: QR-code border width in modules.
            width: QR-code width in modules.
            box_size: Pixel size of each QR module.

        Returns:
            ``None``.
        """
        self.border = border
        self.width = width
        self.box_size = box_size
        size = (width + border * 2) * box_size
        self._image = QImage(size, size, QImage.Format.Format_RGB16)
        self._image.fill(WINDOWPAL.color(QPalette.ColorRole.Window))

    def pixmap(self) -> object:
        """Return the rendered QR code as a ``QPixmap``.

        Returns:
            ``QPixmap`` representation of the QR code image.
        """
        return QPixmap.fromImage(self._image)

    def drawrect(self, row: object, col: object) -> None:
        """Fill one QR module rectangle.

        Args:
            row: Row index of the QR module to fill.
            col: Column index of the QR module to fill.

        Returns:
            ``None``.
        """
        painter = QPainter(self._image)
        painter.fillRect(
            (col + self.border) * self.box_size,
            (row + self.border) * self.box_size,
            self.box_size,
            self.box_size,
            Qt.GlobalColor.black,
        )

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

    gameid_trigger = pyqtSignal(str)
    summary_trigger = pyqtSignal(str)

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
        self.resume_path = None
        self._base_summary_text = ""
        self._loading_summary = False
        self.round_checkboxes = []
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
        select_layout = QHBoxLayout()
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
        self.start_button.clicked.connect(self.game.start_game)
        self.start_button.setEnabled(False)
        self.resume_button = DynamicButton("Load Saved", self)
        self.resume_button.clicked.connect(self.load_saved_game)
        self.rand_button = DynamicButton("Random", self)
        self.rand_button.clicked.connect(self.random)
        button_layout.addWidget(self.start_button, 10)
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
        self.summary_label = DynamicLabel("", lambda: self.height() * 0.04, self)
        self.summary_label.setWordWrap(True)
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self.rounds_widget = QWidget(self)
        self.rounds_layout = QVBoxLayout()
        self.rounds_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rounds_widget.setLayout(self.rounds_layout)
        self.rounds_widget.setVisible(False)
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
        main_layout.addLayout(select_layout, 5)
        main_layout.addStretch(1)
        main_layout.addWidget(self.summary_label, 5)
        main_layout.addWidget(self.rounds_widget, 3)
        main_layout.addLayout(footer_layout, 3)
        main_layout.addStretch(3)
        self.gameid_trigger.connect(self.set_gameid)
        self.summary_trigger.connect(self.set_summary)
        self.setLayout(main_layout)
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

    def __random(self) -> None:
        """Return random."""
        try:
            self.resume_path = None
            self.game.clear_resume_state()
            while True:
                game_id = get_random_game()
                logging.info(f"GAMEID {game_id}")
                self.game.data = get_game(game_id)
                if self.game.valid_game():
                    break
                else:
                    time.sleep(0.25)
            self.gameid_trigger.emit(str(game_id))
            self.summary_trigger.emit(
                self.game.data.date + "\n" + self.game.data.comments
            )
        except Exception as e:
            logging.error(e)
            self.summary_trigger.emit("Cannot get game")

    def random(self, checked: object) -> None:
        """Begin asynchronously loading a random game.

        Args:
            checked: Button checked state supplied by Qt and otherwise ignored.

        Returns:
            ``None``.
        """
        self._loading_summary = True
        self.clear_round_selector()
        self.summary_trigger.emit("Loading...")
        t = Thread(target=self.__random)
        t.start()

    def __show_summary(self) -> None:
        """Return show summary."""
        game_id = self.textbox.text()
        try:
            self.resume_path = None
            self.game.clear_resume_state()
            self.game.data = get_game(game_id)
            if self.game.valid_game():
                self.summary_trigger.emit(
                    self.game.data.date + "\n" + self.game.data.comments
                )
            else:
                self.summary_trigger.emit("Game has blank questions")
        except Exception as e:
            logging.error(e)
            self.summary_trigger.emit("Cannot get game")
        self.check_start()

    def set_summary(self, text: object) -> None:
        """Update the summary text shown on the welcome screen.

        Args:
            text: Summary text to display.

        Returns:
            ``None``.
        """
        self._base_summary_text = text
        self.summary_label.setText(text)
        if text == "Loading...":
            return
        self._loading_summary = False
        if self.resume_path is None and self.game.valid_game():
            self.configure_round_selector()
        elif self.resume_path is None:
            self.clear_round_selector()

    def set_gameid(self, text: object) -> None:
        """Update the game-id input field.

        Args:
            text: New game-id text.

        Returns:
            ``None``.
        """
        self.textbox.setText(text)

    def start_debounce_timer(self, text: object) -> None:
        """Start the debounce timer whenever the text changes."""
        if self.resume_path is not None:
            self.resume_path = None
            self.game.clear_resume_state()
            self.start_button.setText("Start!")
        self.clear_round_selector()
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
        self._loading_summary = True
        self.clear_round_selector()
        self.summary_trigger.emit("Loading...")
        t = Thread(target=self.__show_summary)
        t.start()
        self.check_start()

    def load_saved_game(self, checked: object = False) -> None:
        """Prompt for and prepare a saved game session to resume.

        Args:
            checked: Button checked state supplied by Qt and otherwise ignored.

        Returns:
            ``None``.
        """
        selected_dir = QFileDialog.getExistingDirectory(
            self, "Select Saved Game Folder", ""
        )
        if not selected_dir:
            return
        try:
            resume_state = self.game.prepare_resume_from_dir(selected_dir)
        except Exception as e:
            logging.error(e)
            QMessageBox.warning(self, "Saved Game Error", str(e))
            return
        self.resume_path = selected_dir
        self.start_button.setText("Resume!")
        saved_players = resume_state["general_state"].get("players", [])
        self.configure_round_selector(
            resume_state["general_state"].get("selected_round_indices"),
            enabled=False,
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
        self.summary_label.setText(self._base_summary_text)
        self.check_start()

    def check_start(self) -> None:
        """Enable or disable the start button based on current readiness.

        Returns:
            ``None``.
        """
        rounds_selected = self.resume_path is not None or bool(
            getattr(self.game, "selected_round_indices", lambda: [])()
        )
        expected_player_count = self.game.expected_player_count()
        if rounds_selected and self._base_summary_text:
            self.summary_label.setText(self._base_summary_text)
        if self.game.startable() and rounds_selected:
            self.start_button.setEnabled(True)
        else:
            self.start_button.setEnabled(False)
            if expected_player_count is not None:
                connected_players = len(self.game.buzzer_controller.connected_players)
                self.summary_label.setText(
                    self._base_summary_text
                    + f"\n\nConnect exactly {expected_player_count} players to resume."
                    + f"\nCurrently connected: {connected_players}"
                )
            elif (
                not self._loading_summary
                and not rounds_selected
                and self._base_summary_text
            ):
                self.summary_label.setText(
                    self._base_summary_text + "\n\nSelect at least one round to play."
                )

    def restart(self) -> None:
        """Reset the welcome screen to its initial fresh-game state.

        Returns:
            ``None``.
        """
        self.resume_path = None
        self._base_summary_text = ""
        self.game.clear_resume_state()
        self.start_button.setText("Start!")
        self.clear_round_selector()
        self.show_summary(self)

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
        self.clear_round_selector()
        if not getattr(self.game, "data", None):
            return
        if selected_indices is None:
            selected_indices = list(range(len(self.game.data.rounds)))
        selected_indices = {int(index) for index in selected_indices}
        rounds_label = QLabel("Rounds to play:", self.rounds_widget)
        rounds_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rounds_layout.addWidget(rounds_label)
        for index, round_data in enumerate(self.game.data.rounds):
            checkbox = QCheckBox("", self.rounds_widget)
            checkbox.setProperty("round_label", self.describe_round(round_data, index))
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
        if isinstance(round_data, FinalBoard):
            return "Final Jeopardy!"
        if getattr(round_data, "dj", False):
            return "Double Jeopardy!"
        if index == 0:
            return "Jeopardy!"
        return f"Round {index + 1}"

    def update_selected_rounds(self) -> None:
        """Push the current checkbox selection into the game object.

        Returns:
            ``None``.
        """
        for checkbox in self.round_checkboxes:
            round_label = checkbox.property("round_label") or checkbox.text()
            checkbox.setText(
                f"[{'x' if checkbox.isChecked() else ' '}] {round_label}"
            )
        selected_indices = [
            index
            for index, checkbox in enumerate(self.round_checkboxes)
            if checkbox.isChecked()
        ]
        if hasattr(self.game, "set_selected_round_indices"):
            self.game.set_selected_round_indices(selected_indices)
        self.check_start()


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
                self.url, image_factory=Image, box_size=max(self.height() / 50, 1)
            ).pixmap()
        )

    def restart(self) -> None:
        """Reset the QR screen state when returning to the lobby.

        Returns:
            ``None``.
        """
        pass
