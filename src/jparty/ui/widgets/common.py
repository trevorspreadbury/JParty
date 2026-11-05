"""Shared UI utilities, mixins, and media helpers.

This module provides reusable presentation-layer helpers such as the audio song
player, a compound proxy for mirrored host/audience calls, drop-shadow styling,
and auto-sizing label and button mixins used throughout the widget layer.
"""

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
    """Resolve a packaged data asset path to a string path.

    Args:
        relative_path: Asset path relative to the packaged data directory.

    Returns:
        A string filesystem path for the requested asset.
    """
    return str(data_asset_path(relative_path))


class SongPlayer:
    """Play looping intro or Final Jeopardy music clips."""

    def __init__(self) -> None:
        """Load the audio clips used by the application.

        Returns:
            ``None``.
        """
        super().__init__()
        self.__wave_obj = sa.WaveObject.from_wave_file(resource_path("intro.wav"))
        self.__final = sa.WaveObject.from_wave_file(resource_path("final.wav"))
        self.__stumped = sa.WaveObject.from_wave_file(resource_path("stumped.wav"))
        self.__play_obj = None
        self.__repeating = False
        self.__repeat_thread = None

    def play(self, repeat: object = False) -> None:
        """Play the intro music clip.

        Args:
            repeat: Whether playback should loop until stopped.

        Returns:
            ``None``.
        """
        self.__repeating = repeat
        self.__play_obj = self.__wave_obj.play()
        if repeat:
            self.__repeat_thread = Thread(target=self.__repeat)
            self.__repeat_thread.start()

    def final(self, repeat: object = False) -> None:
        """Play the Final Jeopardy music clip.

        Args:
            repeat: Whether playback should loop until stopped.

        Returns:
            ``None``.
        """
        self.__repeating = repeat
        self.__play_obj = self.__final.play()
        if repeat:
            self.__repeat_thread = Thread(target=self.__repeat)
            self.__repeat_thread.start()

    def stop(self) -> None:
        """Stop playback and prevent further looping.

        Returns:
            ``None``.
        """
        self.__repeating = False
        self.__play_obj.stop()

    def stumped(self) -> None:
        """Play the stumped cue using the preloaded audio asset.

        Returns:
            ``None``.
        """
        self.__stumped.play()

    def __repeat(self) -> None:
        """Loop playback while repeating is enabled.

        Returns:
            ``None``.
        """
        while True:
            self.__play_obj.wait_done()
            if not self.__repeating:
                break
            self.__play_obj = self.__wave_obj.play()


class CompoundObject:
    """Proxy attribute access and calls across multiple objects at once."""

    def __init__(self, *objs: object) -> None:
        """Initialize the proxy with one or more target objects.

        Args:
            *objs: Objects that should receive forwarded operations.

        Returns:
            ``None``.
        """
        self.__objs = list(objs)

    def __setattr__(self, name: object, value: object) -> None:
        """Set an attribute on all proxied objects.

        Args:
            name: Attribute name to set.
            value: Value to assign.

        Returns:
            ``None``.
        """
        if name[0] == "_":
            self.__dict__[name] = value
        else:
            for obj in self.__objs:
                setattr(obj, name, value)

    def __getattr__(self, name: object) -> object:
        """Return a proxy over the named attribute from each target object.

        Args:
            name: Attribute name to retrieve.

        Returns:
            A new ``CompoundObject`` wrapping the retrieved attributes.
        """
        ret = CompoundObject(*[getattr(obj, name) for obj in self.__objs])
        return ret

    def __iadd__(self, display: object) -> object:
        """Append another proxied object.

        Args:
            display: Object to add to the proxy set.

        Returns:
            The updated ``CompoundObject`` instance.
        """
        self.__objs.append(display)
        return self

    def __call__(self, *args: object, **kwargs: object) -> object:
        """Call each proxied callable and wrap the results.

        Args:
            *args: Positional arguments forwarded to each proxied callable.
            **kwargs: Keyword arguments forwarded to each proxied callable.

        Returns:
            A new ``CompoundObject`` wrapping the call results.
        """
        return CompoundObject(*[obj(*args, **kwargs) for obj in self.__objs])

    def __repr__(self) -> str:
        """Return a debug representation of the proxied objects.

        Returns:
            String representation of the compound proxy.
        """
        return "CompoundObject(" + ", ".join([repr(o) for o in self.__objs]) + ")"


"add shadow to widget. Radius is proportion of widget height"


def add_shadow(widget: object, radius: object = 0.1, offset: object = 3) -> None:
    """Apply a black drop shadow effect to a widget.

    Args:
        widget: Widget that should receive the shadow effect.
        radius: Unused retained argument for historical API compatibility.
        offset: Shadow offset in pixels.

    Returns:
        ``None``.
    """
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(widget.height())
    shadow.setColor(QColor("black"))
    shadow.setOffset(offset)
    widget.setGraphicsEffect(shadow)


class AutosizeWidget:
    """Mixin that auto-sizes font content to fit the widget bounds."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize auto-sizing margins and size policy.

        Args:
            *args: Unused positional arguments accepted for mixin compatibility.
            **kwargs: Unused keyword arguments accepted for mixin compatibility.

        Returns:
            ``None``.
        """
        self.autosize_margins = (0.0, 0.0, 0.0, 0.0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.autoresize()

    def sizeHint(self) -> object:
        """Return a flexible preferred size.

        Returns:
            An empty ``QSize``.
        """
        return QSize()

    def minimumSizeHint(self) -> object:
        """Return a minimal preferred size.

        Returns:
            An empty ``QSize``.
        """
        return QSize()

    def heightForWidth(self, w: object) -> int:
        """Report that the widget does not provide a custom height-for-width.

        Args:
            w: Width being queried.

        Returns:
            ``-1`` to defer to default Qt behavior.
        """
        return -1

    def resizeEvent(self, event: object) -> None:
        """Trigger font auto-resizing after widget size changes.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        self.autoresize()

    def autoresize(self) -> None:
        """Recompute and apply a font size that fits the current bounds.

        Returns:
            ``None``.
        """
        if self.size().height() == 0 or self.text() == "":
            return None
        fontsize = self.autofitsize()
        font = self.font()
        font.setPixelSize(fontsize)
        self.setFont(font)

    def plaintext(self) -> object:
        """Return the widget text stripped of simple HTML formatting.

        Returns:
            Plain-text version of the widget's current text.
        """
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
        """Compute the largest font size that fits inside the margins.

        Args:
            stepsize: Pixel decrement used while searching for a fitting size.

        Returns:
            The chosen font pixel size.
        """
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
    """Label widget that auto-sizes text to fit available space."""

    def __init__(
        self, text: object, initialSize: object, parent: object = None
    ) -> None:
        """Initialize an auto-sizing label.

        Args:
            text: Initial label text.
            initialSize: Starting font-size callback or value.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        self.__initialSize = initialSize
        super().__init__(text, parent)

    def flags(self) -> object:
        """Return Qt text-layout flags used for font fitting.

        Returns:
            Combination of alignment and word-wrap flags.
        """
        flags = 0
        if self.wordWrap():
            flags |= Qt.TextFlag.TextWordWrap
        flags |= self.alignment()
        return flags

    def resizeEvent(self, event: object) -> None:
        """Trigger auto-resizing when the label changes size.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        AutosizeWidget.resizeEvent(self, event)

    def setText(self, text: object) -> None:
        """Update text and immediately recompute the fitted font size.

        Args:
            text: New label text.

        Returns:
            ``None``.
        """
        super().setText(text)
        self.autoresize()

    def initialSize(self) -> object:
        """Return the configured starting font size value.

        Returns:
            Numeric starting font size from the configured value or callback.
        """
        if callable(self.__initialSize):
            return self.__initialSize()
        else:
            return self.__initialSize


class DynamicButton(QPushButton, AutosizeWidget):
    """Push button widget with auto-sized label text."""

    def __init__(self, text: object, parent: object = None) -> None:
        """Initialize an auto-sizing button.

        Args:
            text: Initial button text.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(text, parent)

    def resizeEvent(self, event: object) -> None:
        """Trigger auto-resizing when the button changes size.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        AutosizeWidget.resizeEvent(self, event)

    def setText(self, text: object) -> None:
        """Update button text and refit the font size.

        Args:
            text: New button text.

        Returns:
            ``None``.
        """
        super().setText(text)
        self.autoresize()

    def initialSize(self) -> object:
        """Return the starting font size for the button text.

        Returns:
            A font size derived from the current button height.
        """
        return self.height() * 0.5

    def flags(self) -> int:
        """Return the text-layout flags used for font fitting.

        Returns:
            ``0`` because buttons do not need extra text flags here.
        """
        return 0
