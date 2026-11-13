"""Animated side-border widgets used for buzz and hint feedback.

This module contains the illuminated border panels shown beside the board on
the host and audience displays. The host variants can also flash keyboard hint
graphics to guide game control.

Every animation is driven by a ``QTimer`` on the Qt GUI thread. Widgets must
not be touched from Python threads, which hang or crash the app on quit.
"""

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from jparty.ui.widgets.common import resource_path

FLASH_STEP_MS = 200
HINT_BLINK_MS = 500


class Borders:
    """Manage the pair of side-border widgets for a display."""

    def __init__(self, parent: object) -> None:
        """Initialize left and right border widgets for a display.

        Args:
            parent: Parent display widget that owns the borders.

        Returns:
            ``None``.
        """
        super().__init__()
        self.left = self.create_widget(parent, -1)
        self.right = self.create_widget(parent, 1)
        # Parenting the timer to a border widget means it can never fire after
        # the widgets are destroyed.
        self._flash_steps = []
        self._flash_timer = QTimer(self.left)
        self._flash_timer.setInterval(FLASH_STEP_MS)
        self._flash_timer.timeout.connect(self._next_flash_step)

    def __iter__(self) -> object:
        """Iterate over the left and right border widgets.

        Returns:
            An iterator over both border widgets.
        """
        return iter([self.left, self.right])

    def create_widget(self, parent: object, d: object) -> object:
        """Create one border widget instance.

        Args:
            parent: Parent display widget.
            d: Direction marker, typically ``-1`` for left and ``1`` for right.

        Returns:
            A ``BorderWidget`` instance.
        """
        return BorderWidget(parent, d)

    def _next_flash_step(self) -> None:
        """Apply the next on/off state of a running flash.

        Returns:
            ``None``.
        """
        if not self._flash_steps:
            self._flash_timer.stop()
            return
        self.lights(self._flash_steps.pop(0))
        if not self._flash_steps:
            self._flash_timer.stop()

    def flash(self) -> None:
        """Blink both borders off, on, then off, 200 ms apart.

        Returns:
            ``None``.
        """
        self.lights(False)
        self._flash_steps = [True, False]
        self._flash_timer.start()

    def lights(self, val: object) -> None:
        """Turn both border widgets on or off.

        Args:
            val: Boolean-like value indicating whether the borders should glow.

        Returns:
            ``None``.
        """
        for b in self:
            b.lights(val)

    def stop(self) -> None:
        """Stop any running border animation.

        Returns:
            ``None``.
        """
        self._flash_steps = []
        self._flash_timer.stop()


class HostBorders(Borders):
    """Extend borders with flashing keyboard hint support for the host."""

    def __init__(self, parent: object) -> None:
        """Initialize host borders and the hint blink timer.

        Args:
            parent: Parent host display widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self._hint_key = None
        self._hint_shown = False
        self._hint_timer = QTimer(self.left)
        self._hint_timer.setInterval(HINT_BLINK_MS)
        self._hint_timer.timeout.connect(self._toggle_hints)

    def create_widget(self, parent: object, d: object) -> object:
        """Create a host-specific border widget.

        Args:
            parent: Parent host display widget.
            d: Direction marker for left or right border.

        Returns:
            A ``HostBorderWidget`` instance.
        """
        return HostBorderWidget(parent, d)

    def _set_hints_shown(self, shown: bool) -> None:
        """Show or hide the active hint graphic on both borders.

        Args:
            shown: Whether the hint graphic should be visible.

        Returns:
            ``None``.
        """
        self._hint_shown = shown
        for b in self:
            if shown:
                b.show_hints(self._hint_key)
            else:
                b.hide_hints(self._hint_key)

    def _toggle_hints(self) -> None:
        """Flip the active hint graphic for the next half-second blink.

        Returns:
            ``None``.
        """
        self._set_hints_shown(not self._hint_shown)

    def _start_hints(self, key: str) -> None:
        """Start blinking a hint graphic, replacing any other hint.

        Args:
            key: Hint key identifier, such as ``"arrow"`` or ``"space"``.

        Returns:
            ``None``.
        """
        self._hint_key = key
        self._set_hints_shown(True)
        self._hint_timer.start()

    def _stop_hints(self, key: str) -> None:
        """Stop blinking hints and clear the hint graphic.

        Args:
            key: Hint key identifier being cleared.

        Returns:
            ``None``.
        """
        self._hint_timer.stop()
        self._hint_key = None
        self._hint_shown = False
        for b in self:
            b.hide_hints(key)

    def arrowhints(self, val: object) -> None:
        """Show or hide flashing arrow-key hints.

        Args:
            val: Boolean-like value indicating whether arrow hints should show.

        Returns:
            ``None``.
        """
        for b in self:
            b.colors = val
            b.update()
        if val:
            self._start_hints("arrow")
        else:
            self._stop_hints("arrow")

    def spacehints(self, val: object) -> None:
        """Show or hide flashing space-bar hints.

        Args:
            val: Boolean-like value indicating whether space hints should show.

        Returns:
            ``None``.
        """
        if val:
            self._start_hints("space")
        else:
            self._stop_hints("space")

    def stop(self) -> None:
        """Stop the border flash and any blinking hints.

        Returns:
            ``None``.
        """
        super().stop()
        self._hint_timer.stop()


class BorderWidget(QWidget):
    """Simple illuminated side panel shown beside the board."""

    def __init__(self, parent: object, d: object) -> None:
        """Initialize a border widget.

        Args:
            parent: Parent display widget.
            d: Direction marker for the widget's side.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.d = d
        self.__lit = False
        self.show()

    def lights(self, val: object) -> None:
        """Turn the illuminated border effect on or off.

        Args:
            val: Boolean-like value indicating whether the border is lit.

        Returns:
            ``None``.
        """
        self.__lit = val
        self.update()

    def sizeHint(self) -> object:
        """Return the preferred size for the border widget.

        Returns:
            An empty ``QSize`` so layout can size the border flexibly.
        """
        return QSize()

    def paintEvent(self, event: object) -> None:
        """Paint the lit background when the border is active.

        Args:
            event: Qt paint event object.

        Returns:
            ``None``.
        """
        qp = QPainter()
        qp.begin(self)
        if self.__lit:
            qp.setBrush(QBrush(QColor("white")))
            qp.drawRect(self.rect())


class HostBorderWidget(BorderWidget):
    """Border widget that can also display host control hints."""

    def __init__(self, parent: object, d: object) -> None:
        """Initialize a host border with hint images and layout.

        Args:
            parent: Parent host display widget.
            d: Direction marker for the widget's side.

        Returns:
            ``None``.
        """
        super().__init__(parent, d)
        self.layout = QVBoxLayout()
        self.hint_label = QLabel(self)
        self.layout.addWidget(self.hint_label)
        self.setLayout(self.layout)
        self.__hint_images = {
            "space": QPixmap(resource_path("space.png")),
            "arrow": QPixmap(
                resource_path(("right" if d == 1 else "left") + "-arrow.png")
            ),
        }
        self.colors = False
        self.show()

    def show_hints(self, key: object) -> None:
        """Display a hint image for the requested control.

        Args:
            key: Hint key identifier, such as ``"space"`` or ``"arrow"``.

        Returns:
            ``None``.
        """
        self.hint_label.setPixmap(
            self.__hint_images[key].scaled(
                self.size() * 0.9,
                Qt.AspectRatioMode.KeepAspectRatio,
                transformMode=Qt.TransformationMode.SmoothTransformation,
            )
        )

    def hide_hints(self, key: object) -> None:
        """Clear the currently displayed hint image.

        Args:
            key: Hint key identifier being cleared.

        Returns:
            ``None``.
        """
        self.hint_label.setPixmap(QPixmap())

    def resizeEvent(self, event: object) -> None:
        """Adjust hint margins when the border widget is resized.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        self.hint_label.setMargin(int(self.width() * 0.05))

    def paintEvent(self, event: object) -> None:
        """Paint the host border, including colored judgment hints.

        Args:
            event: Qt paint event object.

        Returns:
            ``None``.
        """
        super().paintEvent(event)
        qp = QPainter()
        qp.begin(self)
        if self.colors:
            qp.setBrush(QBrush(QColor("#ff0000" if self.d == 1 else "#33cc33")))
            qp.drawRect(self.rect())
