"""Scoreboard module."""

import time
from base64 import urlsafe_b64decode
from functools import partial
from threading import Thread

from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from jparty.ui.styles import MyLabel
from jparty.ui.widgets.common import resource_path


class NameLabel(MyLabel):
    """Represent namelabel."""

    name_aspect_ratio = 1.3422

    def __init__(self, name: object, parent: object) -> None:
        """Initialize the instance."""
        self.signature = None
        super().__init__("", self.startNameFontSize, parent)
        if name[:21] == "data:image/png;base64":
            i = QImage()
            i.loadFromData(urlsafe_b64decode(name[22:]), "PNG")
            self.signature = QPixmap.fromImage(i)
        else:
            self.setText(name)
        self.setGraphicsEffect(None)
        self.setAutosizeMargins(0.05)

    def startNameFontSize(self) -> object:
        """Run startnamefontsize."""
        return self.height() * 1

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
        super().resizeEvent(event)
        if self.signature is not None:
            self.setPixmap(
                self.signature.scaled(
                    int(self.height() * NameLabel.name_aspect_ratio),
                    self.height(),
                    transformMode=Qt.TransformationMode.SmoothTransformation,
                )
            )


class PlayerWidget(QWidget):
    """Represent playerwidget."""

    aspect_ratio = 0.732
    margin = 0.05

    def __init__(self, game: object, player: object, parent: object = None) -> None:
        """Initialize the instance."""
        super().__init__(parent)
        self.player = player
        self.game = game
        self.__buzz_hint_thread = None
        self.__flash_thread = None
        self.__light_thread = None
        self.name_label = NameLabel(player.name, self)
        self.score_label = MyLabel("$0", self.startScoreFontSize, self)
        self.update_score()
        self.setMouseTracking(True)
        self.main_background = QPixmap(resource_path("player.png"))
        self.active_background = QPixmap(resource_path("player_active.png"))
        self.lights_backgrounds = [
            QPixmap(resource_path(f"player_lights{i}.png")) for i in range(1, 6)
        ]
        self.background = self.main_background
        self.highlighted = False
        layout = QVBoxLayout()
        layout.addStretch(4)
        layout.addWidget(self.score_label, 10)
        layout.addStretch(11)
        layout.addWidget(self.name_label, 31)
        layout.addStretch(10)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Expanding)
        self.setLayout(layout)
        self.show()

    def sizeHint(self) -> object:
        """Run sizehint."""
        h = self.height()
        return QSize(int(h * PlayerWidget.aspect_ratio), h)

    def minimumSizeHint(self) -> object:
        """Run minimumsizehint."""
        return QSize()

    def startScoreFontSize(self) -> object:
        """Run startscorefontsize."""
        return self.height() * 0.2

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
        m = int(PlayerWidget.margin * self.width())
        self.setContentsMargins(m, 0, m, 0)

    def set_lights(self, val: object) -> None:
        """Run set lights."""
        self.background = self.active_background if val else self.main_background
        self.update()

    def __buzz_hint(self) -> None:
        """Return buzz hint."""
        self.set_lights(True)
        time.sleep(0.25)
        self.set_lights(False)

    def buzz_hint(self) -> None:
        """Run buzz hint."""
        self.__buzz_hint_thread = Thread(target=self.__buzz_hint, name="buzz_hint")
        self.__buzz_hint_thread.start()

    def update_score(self) -> None:
        """Run update score."""
        score = self.player.score
        palette = self.score_label.palette()
        if score < 0:
            palette.setColor(QPalette.ColorRole.WindowText, QColor("red"))
        else:
            palette.setColor(QPalette.ColorRole.WindowText, QColor("white"))
        self.score_label.setPalette(palette)
        self.score_label.setText(f"{score:,}")

    def run_lights(self) -> None:
        """Run run lights."""
        self.__light_thread = Thread(target=self.__lights, name="lights")
        self.__light_thread.start()

    def stop_lights(self) -> None:
        """Run stop lights."""
        self.__light_thread = None
        self.set_lights(False)
        self.update()

    def __lights(self) -> None:
        """Return lights."""
        for img in self.lights_backgrounds:
            self.background = img
            self.update()
            time.sleep(1.0)
            if self.__light_thread is None:
                return None
        self.set_lights(True)
        self.update()

    def mousePressEvent(self, event: object) -> None:
        """Run mousepressevent."""
        if self.game.soliciting_player:
            self.game.get_dd_wager(self.player)
            return None
        self.game.adjust_score(self.player)

    def paintEvent(self, event: object) -> None:
        """Run paintevent."""
        qp = QPainter()
        qp.begin(self)
        qp.drawPixmap(self.rect(), self.background)
        qp.end()

    def leaveEvent(self, event: object) -> None:
        """Run leaveevent."""
        if self.game.soliciting_player:
            self.set_lights(False)

    def enterEvent(self, event: object) -> None:
        """Run enterevent."""
        if self.game.soliciting_player:
            self.set_lights(True)


class HostPlayerWidget(PlayerWidget):
    """Represent hostplayerwidget."""

    def __init__(self, game: object, player: object, parent: object = None) -> None:
        """Initialize the instance."""
        self.remove_button = None
        self.up_button = None
        self.down_button = None
        super().__init__(game, player, parent)
        self.remove_button = QPushButton("", self)
        self.remove_button.clicked.connect(partial(self.game.remove_player, player))
        self.remove_button.setIcon(QIcon(resource_path("close-icon.png")))
        self.remove_button.show()
        self.up_button = QPushButton("▲", self)
        self.up_button.clicked.connect(partial(self.game.move_player_up, player))
        self.up_button.setStyleSheet(
            "QPushButton { font-size: 16px; font-weight: bold; }"
        )
        self.up_button.show()
        self.down_button = QPushButton("▼", self)
        self.down_button.clicked.connect(partial(self.game.move_player_down, player))
        self.down_button.setStyleSheet(
            "QPushButton { font-size: 16px; font-weight: bold; }"
        )
        self.down_button.show()

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
        super().resizeEvent(event)
        if self.remove_button is not None:
            self.remove_button.move(QPoint(0, 0))
            xbutton_size = int(self.width() * 0.2)
            self.remove_button.resize(QSize(xbutton_size, xbutton_size))
            self.remove_button.setIconSize(self.size())
        if self.up_button is not None:
            button_size = int(self.width() * 0.15)
            self.up_button.move(QPoint(self.width() - button_size, 0))
            self.up_button.resize(QSize(button_size, button_size))
        if self.down_button is not None:
            button_size = int(self.width() * 0.15)
            self.down_button.move(
                QPoint(self.width() - button_size, self.height() - button_size)
            )
            self.down_button.resize(QSize(button_size, button_size))


class ScoreBoard(QWidget):
    """Represent scoreboard."""

    def __init__(self, game: object, parent: object = None) -> None:
        """Initialize the instance."""
        super().__init__(parent)
        self.game = game
        self.player_widgets = []
        self.player_layout = QHBoxLayout()
        self.player_layout.addStretch()
        self.setLayout(self.player_layout)
        self.show()

    def minimumHeight(self) -> object:
        """Run minimumheight."""
        return 0.2 * self.width()

    def refresh_players(self) -> None:
        """Run refresh players."""
        for pw in list(self.player_widgets):
            if pw.player not in self.game.players:
                i = self.player_layout.indexOf(pw)
                self.player_layout.takeAt(i + 1)
                self.player_layout.takeAt(i)
                self.player_widgets.remove(pw)
                pw.deleteLater()
        player_to_widget = {pw.player: pw for pw in self.player_widgets}
        while self.player_layout.count() > 1:
            item = self.player_layout.takeAt(1)
            if item.widget():
                item.widget().setParent(None)
        self.player_widgets = []
        for i, p in enumerate(self.game.players):
            if p in player_to_widget:
                pw = player_to_widget[p]
            else:
                pw = self.create_player_widget(p)
            self.player_widgets.append(pw)
            self.player_layout.insertWidget(2 * i + 1, pw)
            self.player_layout.insertStretch(2 * i + 2)
            if hasattr(pw, "up_button"):
                pw.up_button.setEnabled(i > 0)
            if hasattr(pw, "down_button"):
                pw.down_button.setEnabled(i < len(self.game.players) - 1)
        self.update()

    def create_player_widget(self, player: object) -> object:
        """Run create player widget."""
        return PlayerWidget(self.game, player, self)

    def paintEvent(self, event: object) -> None:
        """Run paintevent."""
        qp = QPainter()
        qp.begin(self)
        qp.drawPixmap(self.rect(), QPixmap(resource_path("podium.png")))
        qp.end()


class HostScoreBoard(ScoreBoard):
    """Represent hostscoreboard."""

    def create_player_widget(self, player: object) -> object:
        """Run create player widget."""
        return HostPlayerWidget(self.game, player, self)

    def hide_close_buttons(self) -> None:
        """Run hide close buttons."""
        for pw in self.player_widgets:
            pw.remove_button.setVisible(False)
            pw.remove_button.setEnabled(False)
            if hasattr(pw, "up_button"):
                pw.up_button.setVisible(False)
                pw.up_button.setEnabled(False)
            if hasattr(pw, "down_button"):
                pw.down_button.setVisible(False)
                pw.down_button.setEnabled(False)
