"""Styles module."""

from pathlib import Path

import requests
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QColor, QPalette, QPixmap
from PyQt6.QtWidgets import QCommonStyle, QStyle

from jparty.ui.widgets.common import DynamicLabel, add_shadow

REQUEST_TIMEOUT_SECONDS = 10


class JPartyStyle(QCommonStyle):
    """Represent jpartystyle."""

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
        """Run pixelmetric."""
        return JPartyStyle.PM_dict.get(key, super().pixelMetric(key, *args, **kwargs))

    def styleHint(self, key: object, *args: object, **kwargs: object) -> object:
        """Run stylehint."""
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
    """Represent mylabel."""

    def __init__(
        self,
        text: object,
        initialSize: object,
        parent: object = None,
        image: object = False,
    ) -> None:
        """Initialize the instance."""
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
        """Override the resize event to rescale the image."""
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
