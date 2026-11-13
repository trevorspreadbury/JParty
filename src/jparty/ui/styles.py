"""Shared UI styling helpers, palettes, and custom labels.

This module defines the application's Qt style tweaks, reusable color palettes,
and a specialized label widget that can render either auto-sized text or clue
images. These helpers are imported broadly across the UI layer so widgets share
consistent visual behavior.
"""

from pathlib import Path

import requests
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QColor, QPalette, QPixmap
from PyQt6.QtWidgets import QCommonStyle, QStyle

from jparty.ui.widgets.common import DynamicLabel, add_shadow

REQUEST_TIMEOUT_SECONDS = 10


class JPartyStyle(QCommonStyle):
    """Provide application-wide Qt style overrides for spacing and focus."""

    PM_dict = {
        QStyle.PixelMetric.PM_LayoutBottomMargin: 0,
        QStyle.PixelMetric.PM_LayoutLeftMargin: 0,
        QStyle.PixelMetric.PM_LayoutRightMargin: 0,
        QStyle.PixelMetric.PM_LayoutTopMargin: 0,
        QStyle.PixelMetric.PM_LayoutHorizontalSpacing: 0,
        QStyle.PixelMetric.PM_LayoutVerticalSpacing: 0,
    }
    SH_dict = {QStyle.StyleHint.SH_Button_FocusPolicy: 0}

    def pixelMetric(self, key: object, *args: object, **kwargs: object) -> object:
        """Return overridden layout pixel metrics when JParty customizes them.

        Args:
            key: Qt pixel metric being requested.
            *args: Additional arguments forwarded to ``QCommonStyle``.
            **kwargs: Additional keyword arguments forwarded to
                ``QCommonStyle``.

        Returns:
            The overridden metric value when present, otherwise the base style's
            value.
        """
        return JPartyStyle.PM_dict.get(key, super().pixelMetric(key, *args, **kwargs))

    def styleHint(self, key: object, *args: object, **kwargs: object) -> object:
        """Return overridden Qt style hints when JParty customizes them.

        Args:
            key: Qt style hint being requested.
            *args: Additional arguments forwarded to ``QCommonStyle``.
            **kwargs: Additional keyword arguments forwarded to
                ``QCommonStyle``.

        Returns:
            The overridden hint value when present, otherwise the base style's
            value.
        """
        return JPartyStyle.SH_dict.get(key, super().styleHint(key, *args, **kwargs))


def fetch_image_from_url(url: str) -> QPixmap:
    """Fetch an image from the given URL and convert it to a QPixmap."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        image_data = QByteArray(response.content)
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        return pixmap
    except Exception as e:
        print(f"Failed to fetch or load the image: {e}")
        return QPixmap()


class MyLabel(DynamicLabel):
    """Render auto-sized clue text or a scaled image with JParty styling."""

    def __init__(
        self,
        text: object,
        initialSize: object,
        parent: object = None,
        image: object = False,
    ) -> None:
        """Initialize a styled label for text or image content.

        Args:
            text: Display text or image path/URL to show in the label.
            initialSize: Starting font-size callback or value for auto-sizing.
            parent: Optional parent widget.
            image: Whether ``text`` should be interpreted as image content.

        Returns:
            ``None``.
        """
        super().__init__(text, initialSize, parent)
        if not image:
            self.font().setBold(True)
            self.setWordWrap(True)
        else:
            self.question_image = text
            if not Path(self.question_image).exists():
                self.question_image_pixmap = fetch_image_from_url(
                    str(self.question_image)
                )
            else:
                self.question_image_pixmap = QPixmap(self.question_image)
            self.setText("")
            self.setPixmap(self.question_image_pixmap)
            self.setScaledContents(False)
            self.setObjectName("photo")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        add_shadow(self)
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor("white"))
        self.setPalette(palette)
        self.show()

    def resizeEvent(self, event: object) -> None:
        """Rescale the loaded image whenever the label is resized.

        Args:
            event: Qt resize event object.

        Returns:
            ``None``.
        """
        super().resizeEvent(event)
        if hasattr(self, "question_image_pixmap") and self.question_image_pixmap:
            scaled_pixmap = self.question_image_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(scaled_pixmap)


WINDOWPAL = QPalette()
WINDOWPAL.setColor(QPalette.ColorRole.Base, QColor("white"))
WINDOWPAL.setColor(QPalette.ColorRole.WindowText, QColor("black"))
WINDOWPAL.setColor(QPalette.ColorRole.Text, QColor("black"))
WINDOWPAL.setColor(QPalette.ColorRole.Window, QColor("#fefefe"))
WINDOWPAL.setColor(QPalette.ColorRole.Button, QColor("#e6e6e6"))
WINDOWPAL.setColor(QPalette.ColorRole.Button, QColor("#e6e6e6"))
WINDOWPAL.setColor(QPalette.ColorRole.ButtonText, QColor("black"))
WINDOWPAL.setColor(
    QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#d0d0d0")
)
JBLUE = QColor("#1010a1")
DARKBLUE = QColor("#0b0b74")
CARDPAL = QPalette()
CARDPAL.setColor(QPalette.ColorRole.Window, JBLUE)
CARDPAL.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
