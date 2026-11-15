"""Tests for the buzzer join QR code on the audience start screen."""

import pytest
import qrcode
from PyQt6.QtGui import QColor

from jparty.ui.widgets.welcome import Image, QRWidget

pytestmark = pytest.mark.qt

URL = "http://192.168.0.12:8080"


def test_qr_image_adapter_draws_a_full_size_code(qapp: object) -> None:
    """The Qt image adapter should render every module at the requested size."""
    box_size = 4
    qr = qrcode.QRCode(box_size=box_size)
    qr.add_data(URL)
    qr.make()

    pixmap = qr.make_image(image_factory=Image).pixmap()

    expected_size = (qr.modules_count + 2 * qr.border) * box_size
    assert pixmap.width() == expected_size
    assert pixmap.height() == expected_size
    image = pixmap.toImage()
    # The top-left finder pattern always starts with a dark module.
    corner = qr.border * box_size
    assert image.pixelColor(corner, corner) == QColor("black")
    # The quiet-zone border stays background colored.
    assert image.pixelColor(0, 0) != QColor("black")


def test_qr_widget_renders_code_when_resized(qtbot: object) -> None:
    """Resizing the start screen should rebuild the QR pixmap without errors.

    333 px is not a multiple of 50, so this also covers a non-integer
    ``height / 50`` box size, which PyQt6 rejects for image sizes.
    """
    widget = QRWidget(URL.removeprefix("http://"))
    qtbot.addWidget(widget)

    widget.resize(400, 333)
    qtbot.waitUntil(lambda: not widget.qrlabel.pixmap().isNull(), timeout=2000)

    assert widget.qrlabel.pixmap().width() > 0
