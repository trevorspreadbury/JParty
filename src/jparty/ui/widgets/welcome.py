"""Welcome module."""

import logging
import time
from threading import Thread

import qrcode
from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QFont, QImage, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
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
from jparty.services.game_loader import get_game, get_random_game
from jparty.ui.styles import WINDOWPAL
from jparty.ui.widgets.common import (
    DynamicButton,
    DynamicLabel,
    add_shadow,
    resource_path,
)


class Image(qrcode.image.base.BaseImage):
    """QR code image widget"""

    def __init__(self, border: object, width: object, box_size: object) -> None:
        """Initialize the instance."""
        self.border = border
        self.width = width
        self.box_size = box_size
        size = (width + border * 2) * box_size
        self._image = QImage(size, size, QImage.Format.Format_RGB16)
        self._image.fill(WINDOWPAL.color(QPalette.ColorRole.Window))

    def pixmap(self) -> object:
        """Run pixmap."""
        return QPixmap.fromImage(self._image)

    def drawrect(self, row: object, col: object) -> None:
        """Run drawrect."""
        painter = QPainter(self._image)
        painter.fillRect(
            (col + self.border) * self.box_size,
            (row + self.border) * self.box_size,
            self.box_size,
            self.box_size,
            Qt.GlobalColor.black,
        )

    def save(self, stream: object, kind: object = None) -> None:
        """Run save."""
        pass


class StartWidget(QWidget):
    """Represent startwidget."""

    def __init__(self, parent: object = None) -> None:
        """Initialize the instance."""
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
        """Run paintevent."""
        qp = QPainter()
        qp.begin(self)
        qp.setBrush(QBrush(WINDOWPAL.color(QPalette.ColorRole.Window)))
        qp.drawRect(self.rect())

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
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
    """Represent welcome."""

    gameid_trigger = pyqtSignal(str)
    summary_trigger = pyqtSignal(str)

    def __init__(self, game: object, parent: object = None) -> None:
        """Initialize the instance."""
        super().__init__(parent)
        self.game = game
        self.resume_path = None
        self._base_summary_text = ""
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
        main_layout.addLayout(footer_layout, 3)
        main_layout.addStretch(3)
        self.gameid_trigger.connect(self.set_gameid)
        self.summary_trigger.connect(self.set_summary)
        self.setLayout(main_layout)
        self.show()

    def show_help(self) -> None:
        """Run show help."""
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
        """Run resizeevent."""
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
        """Run random."""
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
        """Run set summary."""
        self._base_summary_text = text
        self.summary_label.setText(text)

    def set_gameid(self, text: object) -> None:
        """Run set gameid."""
        self.textbox.setText(text)

    def start_debounce_timer(self, text: object) -> None:
        """Start the debounce timer whenever the text changes."""
        if self.resume_path is not None:
            self.resume_path = None
            self.game.clear_resume_state()
            self.start_button.setText("Start!")
        self.debounce_timer.start(2000)

    def debounced_show_summary(self) -> None:
        """Call show_summary with the current text after debounce period."""
        self.show_summary(self.textbox.text())

    def show_summary(self, text: object = None) -> None:
        """Run show summary."""
        self.summary_trigger.emit("Loading...")
        t = Thread(target=self.__show_summary)
        t.start()
        self.check_start()

    def load_saved_game(self, checked: object = False) -> None:
        """Run load saved game."""
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
        """Run check start."""
        if self.game.startable():
            self.start_button.setEnabled(True)
        else:
            self.start_button.setEnabled(False)
            expected_player_count = self.game.expected_player_count()
            if expected_player_count is not None:
                connected_players = len(self.game.buzzer_controller.connected_players)
                self.summary_label.setText(
                    self._base_summary_text
                    + f"\n\nConnect exactly {expected_player_count} players to resume."
                    + f"\nCurrently connected: {connected_players}"
                )

    def restart(self) -> None:
        """Run restart."""
        self.resume_path = None
        self._base_summary_text = ""
        self.game.clear_resume_state()
        self.start_button.setText("Start!")
        self.show_summary(self)


class QRWidget(StartWidget):
    """Represent qrwidget."""

    def __init__(self, host: object, parent: object = None) -> None:
        """Initialize the instance."""
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
        """Run start fontsize."""
        return 0.1 * self.width()

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
        super().resizeEvent(event)
        self.qrlabel.setPixmap(
            qrcode.make(
                self.url, image_factory=Image, box_size=max(self.height() / 50, 1)
            ).pixmap()
        )

    def restart(self) -> None:
        """Run restart."""
        pass
