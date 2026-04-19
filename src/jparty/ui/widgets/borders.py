"""Borders module."""

import time
from threading import Thread, current_thread

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from jparty.ui.widgets.common import resource_path


class Borders:
    """Represent borders."""

    def __init__(self, parent: object) -> None:
        """Initialize the instance."""
        super().__init__()
        self.left = self.create_widget(parent, -1)
        self.right = self.create_widget(parent, 1)

    def __iter__(self) -> object:
        """Return iter."""
        return iter([self.left, self.right])

    def create_widget(self, parent: object, d: object) -> object:
        """Run create widget."""
        return BorderWidget(parent, d)

    def __flash(self) -> None:
        """Return flash."""
        self.lights(False)
        time.sleep(0.2)
        self.lights(True)
        time.sleep(0.2)
        self.lights(False)

    def flash(self) -> None:
        """Run flash."""
        self.__flash_thread = Thread(target=self.__flash, name="flash")
        self.__flash_thread.start()

    def lights(self, val: object) -> None:
        """Run lights."""
        for b in self:
            b.lights(val)


class HostBorders(Borders):
    """Represent hostborders."""

    def __init__(self, parent: object) -> None:
        """Initialize the instance."""
        super().__init__(parent)
        self.__active_thread = None

    def create_widget(self, parent: object, d: object) -> object:
        """Run create widget."""
        return HostBorderWidget(parent, d)

    def __flash_hints(self, key: object) -> None:
        """Return flash hints."""
        while self.__active_thread == current_thread():
            for b in self:
                b.show_hints(key)
            time.sleep(0.5)
            for b in self:
                b.hide_hints(key)
            time.sleep(0.5)

    def buzz_hint(self) -> None:
        """Run buzz hint."""
        self.__buzz_hint_thread = Thread(target=self.__buzz_hint, name="buzz_hint")
        self.__buzz_hint_thread.start()

    def arrowhints(self, val: object) -> None:
        """Run arrowhints."""
        for b in self:
            b.colors = val
            b.update()
        if val:
            self.__active_thread = Thread(
                target=self.__flash_hints, args=("arrow",), name="arrow_hints"
            )
            self.__active_thread.start()
        else:
            self.__active_thread = None
            for b in self:
                b.hide_hints("arrow")

    def spacehints(self, val: object) -> None:
        """Run spacehints."""
        if val:
            self.__active_thread = Thread(
                target=self.__flash_hints, args=("space",), name="space_hints"
            )
            self.__active_thread.start()
        else:
            self.__active_thread = None
            for b in self:
                b.hide_hints("space")

    def closeEvent(self, event: object) -> None:
        """Run closeevent."""
        super().closeEvent(event)
        self.__active_hint = None


class BorderWidget(QWidget):
    """Represent borderwidget."""

    def __init__(self, parent: object, d: object) -> None:
        """Initialize the instance."""
        super().__init__(parent)
        self.d = d
        self.__lit = False
        self.show()

    def lights(self, val: object) -> None:
        """Run lights."""
        self.__lit = val
        self.update()

    def sizeHint(self) -> object:
        """Run sizehint."""
        return QSize()

    def paintEvent(self, event: object) -> None:
        """Run paintevent."""
        qp = QPainter()
        qp.begin(self)
        if self.__lit:
            qp.setBrush(QBrush(QColor("white")))
            qp.drawRect(self.rect())


class HostBorderWidget(BorderWidget):
    """Represent hostborderwidget."""

    def __init__(self, parent: object, d: object) -> None:
        """Initialize the instance."""
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
        """Run show hints."""
        self.hint_label.setPixmap(
            self.__hint_images[key].scaled(
                self.size() * 0.9,
                Qt.AspectRatioMode.KeepAspectRatio,
                transformMode=Qt.TransformationMode.SmoothTransformation,
            )
        )

    def hide_hints(self, key: object) -> None:
        """Run hide hints."""
        self.hint_label.setPixmap(QPixmap())

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
        self.hint_label.setMargin(int(self.width() * 0.05))

    def paintEvent(self, event: object) -> None:
        """Run paintevent."""
        super().paintEvent(event)
        qp = QPainter()
        qp.begin(self)
        if self.colors:
            qp.setBrush(QBrush(QColor("#ff0000" if self.d == 1 else "#33cc33")))
            qp.drawRect(self.rect())
