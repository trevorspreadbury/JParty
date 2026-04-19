"""Common module."""

import re
from threading import Thread

import simpleaudio as sa
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QFontMetrics
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QPushButton, QSizePolicy

from jparty.app.paths import data_asset_path

MARGIN_ARG_COUNT_WIDTH_HEIGHT = 2
MARGIN_ARG_COUNT_ALL_SIDES = 4
MIN_AUTOFIT_FONT_SIZE = 2


def resource_path(relative_path: object) -> object:
    """Run resource path."""
    return str(data_asset_path(relative_path))


class SongPlayer:
    """Represent songplayer."""

    def __init__(self) -> None:
        """Initialize the instance."""
        super().__init__()
        self.__wave_obj = sa.WaveObject.from_wave_file(resource_path("intro.wav"))
        self.__final = sa.WaveObject.from_wave_file(resource_path("final.wav"))
        self.__play_obj = None
        self.__repeating = False
        self.__repeat_thread = None

    def play(self, repeat: object = False) -> None:
        """Run play."""
        self.__repeating = repeat
        self.__play_obj = self.__wave_obj.play()
        if repeat:
            self.__repeat_thread = Thread(target=self.__repeat)
            self.__repeat_thread.start()

    def final(self, repeat: object = False) -> None:
        """Run final."""
        self.__repeating = repeat
        self.__play_obj = self.__final.play()
        if repeat:
            self.__repeat_thread = Thread(target=self.__repeat)
            self.__repeat_thread.start()

    def stop(self) -> None:
        """Run stop."""
        self.__repeating = False
        self.__play_obj.stop()

    def __repeat(self) -> None:
        """Return repeat."""
        while True:
            self.__play_obj.wait_done()
            if not self.__repeating:
                break
            self.__play_obj = self.__wave_obj.play()


class CompoundObject:
    """Represent compoundobject."""

    def __init__(self, *objs: object) -> None:
        """Initialize the instance."""
        self.__objs = list(objs)

    def __setattr__(self, name: object, value: object) -> None:
        """Return setattr."""
        if name[0] == "_":
            self.__dict__[name] = value
        else:
            for obj in self.__objs:
                setattr(obj, name, value)

    def __getattr__(self, name: object) -> object:
        """Return getattr."""
        ret = CompoundObject(*[getattr(obj, name) for obj in self.__objs])
        return ret

    def __iadd__(self, display: object) -> object:
        """Return iadd."""
        self.__objs.append(display)
        return self

    def __call__(self, *args: object, **kwargs: object) -> object:
        """Return call."""
        return CompoundObject(*[obj(*args, **kwargs) for obj in self.__objs])

    def __repr__(self) -> str:
        """Return repr."""
        return "CompoundObject(" + ", ".join([repr(o) for o in self.__objs]) + ")"


"add shadow to widget. Radius is proportion of widget height"


def add_shadow(widget: object, radius: object = 0.1, offset: object = 3) -> None:
    """Run add shadow."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(widget.height())
    shadow.setColor(QColor("black"))
    shadow.setOffset(offset)
    widget.setGraphicsEffect(shadow)


class AutosizeWidget:
    """This class is a mixin which must be inherited with a QWidget with a `text()` method."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize the instance."""
        self.autosize_margins = (0.0, 0.0, 0.0, 0.0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.autoresize()

    def sizeHint(self) -> object:
        """Run sizehint."""
        return QSize()

    def minimumSizeHint(self) -> object:
        """Run minimumsizehint."""
        return QSize()

    def heightForWidth(self, w: object) -> int:
        """Run heightforwidth."""
        return -1

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
        self.autoresize()

    def autoresize(self) -> None:
        """Run autoresize."""
        if self.size().height() == 0 or self.text() == "":
            return None
        fontsize = self.autofitsize()
        font = self.font()
        font.setPixelSize(fontsize)
        self.setFont(font)

    def plaintext(self) -> object:
        """Run plaintext."""
        text = self.text()
        text = re.sub("<br>", "\n", text)
        text = re.sub("<[^>]*>", "", text)
        return text

    def setAutosizeMargins(self, *args: object) -> None:
        """Set the dynamic sizing margins.

        ---
        if 1 arg, set all margins,
        if 2 args, set width and height margins
        if 4 args, set left, top, right and bottom margins
        """
        if len(args) == 1:
            self.autosize_margins = (args[0], args[0], args[0], args[0])
        elif len(args) == MARGIN_ARG_COUNT_WIDTH_HEIGHT:
            self.autosize_margins = (args[0], args[1], args[0], args[1])
        elif len(args) == MARGIN_ARG_COUNT_ALL_SIDES:
            self.autosize_margins = (args[0], args[1], args[2], args[3])
        else:
            raise Exception("Need 1, 2, or 4 arguments")

    def autofitsize(self, stepsize: object = 1) -> object:
        """Run autofitsize."""
        font = self.font()
        (ml, mt, mr, md) = self.autosize_margins
        rect = self.rect().adjusted(
            int(self.width() * ml),
            int(self.height() * mt),
            int(-self.width() * mr),
            int(-self.height() * mt),
        )
        text = self.plaintext()
        font.setPixelSize(int(self.initialSize()))
        size = font.pixelSize()

        def fullrect(font: object) -> object:
            """Run fullrect."""
            fm = QFontMetrics(font)
            return fm.boundingRect(rect, self.flags(), text)

        newrect = fullrect(font)
        if not rect.contains(newrect):
            while size > MIN_AUTOFIT_FONT_SIZE:
                size -= stepsize
                font.setPixelSize(size)
                newrect = fullrect(font)
                if rect.contains(newrect):
                    return font.pixelSize()
        return size


class DynamicLabel(QLabel, AutosizeWidget):
    """Represent dynamiclabel."""

    def __init__(
        self, text: object, initialSize: object, parent: object = None
    ) -> None:
        """Initialize the instance."""
        self.__initialSize = initialSize
        super().__init__(text, parent)

    def flags(self) -> object:
        """Run flags."""
        flags = 0
        if self.wordWrap():
            flags |= Qt.TextFlag.TextWordWrap
        flags |= self.alignment()
        return flags

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
        AutosizeWidget.resizeEvent(self, event)

    def setText(self, text: object) -> None:
        """Run settext."""
        super().setText(text)
        self.autoresize()

    def initialSize(self) -> object:
        """Run initialsize."""
        if callable(self.__initialSize):
            return self.__initialSize()
        else:
            return self.__initialSize


class DynamicButton(QPushButton, AutosizeWidget):
    """Represent dynamicbutton."""

    def __init__(self, text: object, parent: object = None) -> None:
        """Initialize the instance."""
        super().__init__(text, parent)

    def resizeEvent(self, event: object) -> None:
        """Run resizeevent."""
        AutosizeWidget.resizeEvent(self, event)

    def setText(self, text: object) -> None:
        """Run settext."""
        super().setText(text)
        self.autoresize()

    def initialSize(self) -> object:
        """Run initialsize."""
        return self.height() * 0.5

    def flags(self) -> int:
        """Run flags."""
        return 0
