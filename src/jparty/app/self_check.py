"""Headless self-check for installed and packaged JParty builds.

``jparty self-check`` exercises the parts of the app that packaging most often
breaks: package metadata, bundled assets, Qt Multimedia's audio plugins, the
QR-code renderer, and matplotlib/NumPy. It opens no windows and uses no
network, so it can run inside a PyInstaller build as a smoke test. The
packaged app has no console, so results can also be written to a report file.
"""

from __future__ import annotations

import io
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

SOUND_LOAD_TIMEOUT_SECONDS = 10.0
QR_TEST_URL = "http://192.168.0.1:8080"
QR_BOX_SIZE = 4


@dataclass
class CheckResult:
    """Outcome of one self-check step."""

    name: str
    passed: bool
    detail: str


def _check_package_metadata() -> str:
    """Confirm the installed package metadata provides the version."""
    try:
        return f"jparty {version('jparty')}"
    except PackageNotFoundError as error:
        raise RuntimeError(
            "jparty package metadata is missing, so the app would show a "
            "hard-coded fallback version"
        ) from error


def _check_assets() -> str:
    """Confirm the bundled data and buzzer web assets exist."""
    from jparty.app.paths import web_asset_path
    from jparty.ui.widgets.common import resource_path

    required = [
        Path(resource_path(name))
        for name in (
            "intro.wav",
            "final.wav",
            "stumped.wav",
            "dd.wav",
            "ITC_ Korinna Normal.ttf",
        )
    ]
    required += [
        Path(web_asset_path("templates")),
        Path(web_asset_path("static")) / "buzzer.js",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"missing assets: {', '.join(missing)}")
    return f"{len(required)} assets found"


def _check_sounds() -> str:
    """Confirm every game sound decodes through Qt Multimedia."""
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtMultimedia import QSoundEffect

    from jparty.ui.widgets.common import SongPlayer, has_audio_output

    if not has_audio_output():
        return "skipped: no audio output device"
    player = SongPlayer()
    effects = {
        name.split("__")[-1]: effect
        for name, effect in vars(player).items()
        if isinstance(effect, QSoundEffect)
    }
    deadline = time.monotonic() + SOUND_LOAD_TIMEOUT_SECONDS
    while time.monotonic() < deadline and any(
        effect.status() == QSoundEffect.Status.Loading for effect in effects.values()
    ):
        QCoreApplication.processEvents()
        time.sleep(0.02)
    not_ready = {
        name: effect.status().name
        for name, effect in effects.items()
        if effect.status() != QSoundEffect.Status.Ready
    }
    if not_ready:
        raise RuntimeError(f"sounds not ready: {not_ready}")
    return f"{len(effects)} sounds ready"


def _check_qr_code() -> str:
    """Confirm the buzzer QR code renders through the Qt image adapter."""
    import qrcode

    from jparty.ui.widgets.welcome import Image

    qr = qrcode.QRCode(box_size=QR_BOX_SIZE)
    qr.add_data(QR_TEST_URL)
    qr.make()
    pixmap = qr.make_image(image_factory=Image).pixmap()
    expected = (qr.modules_count + 2 * qr.border) * QR_BOX_SIZE
    if pixmap.isNull() or pixmap.width() != expected:
        raise RuntimeError(f"QR pixmap is {pixmap.width()} px, expected {expected}")
    return f"{expected} px QR code"


def _check_charts() -> str:
    """Confirm matplotlib and NumPy can render a chart."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy

    figure, axes = plt.subplots()
    axes.plot(numpy.arange(5), numpy.arange(5) ** 2)
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    plt.close(figure)
    if not buffer.getvalue():
        raise RuntimeError("chart rendered no data")
    return f"matplotlib {matplotlib.__version__}, numpy {numpy.__version__}"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("package metadata", _check_package_metadata),
    ("assets", _check_assets),
    ("sounds", _check_sounds),
    ("qr code", _check_qr_code),
    ("charts", _check_charts),
]


def run_self_check(report_path: str | None = None) -> int:
    """Run every self-check step and report the results.

    Args:
        report_path: Optional file to write the report to, for builds without
            a console.

    Returns:
        ``0`` when every check passes, otherwise ``1``.
    """
    if not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(["jparty-self-check"])
    results = []
    for name, check in CHECKS:
        try:
            results.append(CheckResult(name, True, check()))
        except Exception as error:  # noqa: BLE001 - report every failure
            results.append(CheckResult(name, False, f"{type(error).__name__}: {error}"))
    lines = [
        f"{'PASS' if result.passed else 'FAIL'} {result.name}: {result.detail}"
        for result in results
    ]
    failed = [result for result in results if not result.passed]
    lines.append("SELF-CHECK " + ("FAILED" if failed else "PASSED"))
    report = "\n".join(lines) + "\n"
    if sys.stdout is not None:  # windowed PyInstaller builds have no stdout
        print(report, end="")
    if report_path:
        Path(report_path).write_text(report, encoding="utf-8")
    return 1 if failed else 0
