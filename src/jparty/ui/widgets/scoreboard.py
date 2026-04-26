"""Scoreboard and podium widgets for connected players.

This module renders player nameplates, scores, podium backgrounds, and the
host-only controls used to remove or reorder players during the lobby.
"""

import time
from base64 import urlsafe_b64decode
from functools import partial
from threading import Thread

from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from jparty.ui.styles import MyLabel
from jparty.ui.widgets.common import resource_path
from jparty.ui.widgets.score_correction import ScoreCorrectionDialog


class NameLabel(MyLabel):
    """Display a player's name or handwritten signature image."""

    name_aspect_ratio = 1.3422

    def __init__(self, name: object, parent: object) -> None:
        """Initialize a name label from plain text or embedded signature data.

        Args:
            name: Player name text or data-URL encoded signature image.
            parent: Parent widget.

        Returns:
            ``None``.
        """
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
        """Return the starting font size for player names.

        Returns:
            A font size derived from the current widget height.
        """
        return self.height() * 1

    def resizeEvent(self, event: object) -> None:
        """Rescale signature images whenever the label changes size.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
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
    """Render one player's podium, score, and buzz animations."""

    aspect_ratio = 0.732
    margin = 0.05

    def __init__(self, game: object, player: object, parent: object = None) -> None:
        """Initialize a podium widget for a player.

        Args:
            game: Active game instance controlling interactions.
            player: Player object displayed by the widget.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
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
        """Return the preferred podium size based on current height.

        Returns:
            Preferred ``QSize`` for the podium aspect ratio.
        """
        h = self.height()
        return QSize(int(h * PlayerWidget.aspect_ratio), h)

    def minimumSizeHint(self) -> object:
        """Return the minimum preferred podium size.

        Returns:
            An empty ``QSize``.
        """
        return QSize()

    def startScoreFontSize(self) -> object:
        """Return the starting font size for score text.

        Returns:
            A font size derived from the current widget height.
        """
        return self.height() * 0.2

    def resizeEvent(self, event: object) -> None:
        """Adjust podium content margins when the widget is resized.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        m = int(PlayerWidget.margin * self.width())
        self.setContentsMargins(m, 0, m, 0)

    def set_lights(self, val: object) -> None:
        """Toggle the podium's active-lit background.

        Args:
            val: Boolean-like value indicating whether lights should show.

        Returns:
            ``None``.
        """
        self.background = self.active_background if val else self.main_background
        self.update()

    def __buzz_hint(self) -> None:
        """Return buzz hint."""
        self.set_lights(True)
        time.sleep(0.25)
        self.set_lights(False)

    def buzz_hint(self) -> None:
        """Flash the podium briefly as a buzz feedback hint.

        Returns:
            ``None``.
        """
        self.__buzz_hint_thread = Thread(target=self.__buzz_hint, name="buzz_hint")
        self.__buzz_hint_thread.start()

    def update_score(self) -> None:
        """Refresh the displayed score text and color.

        Returns:
            ``None``.
        """
        score = self.player.score
        palette = self.score_label.palette()
        if score < 0:
            palette.setColor(QPalette.ColorRole.WindowText, QColor("red"))
        else:
            palette.setColor(QPalette.ColorRole.WindowText, QColor("white"))
        self.score_label.setPalette(palette)
        self.score_label.setText(f"{score:,}")

    def run_lights(self) -> None:
        """Start the animated buzz-winning light sequence.

        Returns:
            ``None``.
        """
        self.__light_thread = Thread(target=self.__lights, name="lights")
        self.__light_thread.start()

    def stop_lights(self) -> None:
        """Stop any running light animation and restore the base state.

        Returns:
            ``None``.
        """
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
        """Handle host clicks for score edits or Daily Double player choice.

        Args:
            event: Qt mouse event object.

        Returns:
            ``None``.
        """
        if self.game.soliciting_player:
            self.game.get_dd_wager(self.player)
            return None
        if self.game.active_question is None:
            self.game.adjust_score(self.player)

    def paintEvent(self, event: object) -> None:
        """Paint the current podium background image.

        Args:
            event: Qt paint event object.

        Returns:
            ``None``.
        """
        qp = QPainter()
        qp.begin(self)
        qp.drawPixmap(self.rect(), self.background)
        qp.end()

    def leaveEvent(self, event: object) -> None:
        """Clear hover lighting when leaving a Daily Double selection state.

        Args:
            event: Qt enter/leave event object.

        Returns:
            ``None``.
        """
        if self.game.soliciting_player:
            self.set_lights(False)

    def enterEvent(self, event: object) -> None:
        """Light the podium on hover during Daily Double player selection.

        Args:
            event: Qt enter/leave event object.

        Returns:
            ``None``.
        """
        if self.game.soliciting_player:
            self.set_lights(True)


class HostPlayerWidget(PlayerWidget):
    """Player podium widget with host-only removal and reorder controls."""

    def __init__(self, game: object, player: object, parent: object = None) -> None:
        """Initialize a host podium widget with extra controls.

        Args:
            game: Active game instance controlling interactions.
            player: Player object displayed by the widget.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
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
        """Position the host control buttons when the podium is resized.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
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
    """Lay out the podium widgets for all connected players."""

    def __init__(self, game: object, parent: object = None) -> None:
        """Initialize a scoreboard for the active game.

        Args:
            game: Active game instance whose players are displayed.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.game = game
        self.player_widgets = []
        self.player_layout = QHBoxLayout()
        self.player_layout.addStretch()
        self.setLayout(self.player_layout)
        self.show()

    def minimumHeight(self) -> object:
        """Return a heuristic minimum height for the scoreboard.

        Returns:
            Height value based on the scoreboard width.
        """
        return 0.2 * self.width()

    def refresh_players(self) -> None:
        """Synchronize podium widgets with the current connected players.

        Returns:
            ``None``.
        """
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
        """Create a podium widget for one player.

        Args:
            player: Player object to display.

        Returns:
            A ``PlayerWidget`` instance.
        """
        return PlayerWidget(self.game, player, self)

    def paintEvent(self, event: object) -> None:
        """Paint the scoreboard podium background.

        Args:
            event: Qt paint event object.

        Returns:
            ``None``.
        """
        qp = QPainter()
        qp.begin(self)
        qp.drawPixmap(self.rect(), QPixmap(resource_path("podium.png")))
        qp.end()


class HostScoreBoard(ScoreBoard):
    """Scoreboard variant that uses host-specific player widgets."""

    button_width_scale = 0.18
    button_height_scale = 0.18
    button_left_margin_scale = 0.02
    button_bottom_margin_scale = 0.06

    def __init__(self, game: object, parent: object = None) -> None:
        """Initialize the host scoreboard with score-correction controls.

        Args:
            game: Active game instance whose players are displayed.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(game, parent)
        self.edit_score_button = QPushButton("Edit Score", self)
        self.edit_score_button.clicked.connect(self.open_score_editor)
        self.score_correction_dialog = None
        self.edit_score_button.raise_()
        self._position_edit_score_button()
        self.refresh_score_edit_button()

    def resizeEvent(self, event: object) -> None:
        """Keep the score-edit button centered without affecting podium layout.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        super().resizeEvent(event)
        self._position_edit_score_button()

    def _position_edit_score_button(self) -> None:
        """Position the overlay score-edit button at the bottom-left.

        Returns:
            ``None``.
        """
        if not hasattr(self, "edit_score_button"):
            return
        button_width = max(120, int(self.width() * self.button_width_scale))
        button_height = max(34, int(self.height() * self.button_height_scale))
        button_x = max(0, int(self.width() * self.button_left_margin_scale))
        button_y = max(
            0,
            self.height()
            - button_height
            - int(self.height() * self.button_bottom_margin_scale),
        )
        self.edit_score_button.setGeometry(
            button_x, button_y, button_width, button_height
        )

    def create_player_widget(self, player: object) -> object:
        """Create a host podium widget for one player.

        Args:
            player: Player object to display.

        Returns:
            A ``HostPlayerWidget`` instance.
        """
        return HostPlayerWidget(self.game, player, self)

    def refresh_score_edit_button(self) -> None:
        """Refresh whether the score-correction button is enabled.

        Returns:
            ``None``.
        """
        self._position_edit_score_button()
        can_open = (
            self.game.can_open_score_editor()
            if hasattr(self.game, "can_open_score_editor")
            else False
        )
        self.edit_score_button.setEnabled(can_open)

    def open_score_editor(self) -> None:
        """Open the host score-correction dialog and apply any saved edits.

        Returns:
            ``None``.
        """
        entries = self.game.get_recent_score_corrections()
        if not entries:
            self.refresh_score_edit_button()
            return
        self.score_correction_dialog = ScoreCorrectionDialog(
            entries, self.game.players, self
        )
        if self.score_correction_dialog.exec():
            corrections = self.score_correction_dialog.collect_changes()
            self.game.apply_question_history_corrections(corrections)
        self.refresh_score_edit_button()

    def hide_close_buttons(self) -> None:
        """Hide player removal and reorder controls after the game starts.

        Returns:
            ``None``.
        """
        for pw in self.player_widgets:
            pw.remove_button.setVisible(False)
            pw.remove_button.setEnabled(False)
            if hasattr(pw, "up_button"):
                pw.up_button.setVisible(False)
                pw.up_button.setEnabled(False)
            if hasattr(pw, "down_button"):
                pw.down_button.setVisible(False)
                pw.down_button.setEnabled(False)
