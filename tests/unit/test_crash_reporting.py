"""Test crash reporting setup module."""

import logging
import sys
import threading
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QMessageBox

from jparty.app import bootstrap
from jparty.app import logging as crash_logging

pytestmark = pytest.mark.unit


@pytest.fixture
def isolated_crash_reporting(monkeypatch: object, tmp_path: Path) -> Path:
    """Redirect the log file and restore global hook/logging state afterwards."""
    log_file = tmp_path / "logs" / "latest.log"
    monkeypatch.setattr(crash_logging, "LOG_FILE", log_file)
    monkeypatch.setattr(crash_logging, "_installed_hook", None)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    yield log_file
    for handler in root.handlers[:]:
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    for handler in saved_handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(saved_level)


def test_importing_bootstrap_does_not_install_hook_as_side_effect() -> None:
    """Test crash reporting is installed explicitly rather than on import."""
    assert hasattr(crash_logging, "install_crash_reporting")
    assert not hasattr(crash_logging, "qt_exception_hook")
    assert bootstrap.install_crash_reporting is crash_logging.install_crash_reporting


def test_install_crash_reporting_sets_excepthook_and_log_file(
    isolated_crash_reporting: Path,
) -> None:
    """Test installation replaces the default excepthook and writes the log."""
    hook = crash_logging.install_crash_reporting()
    assert sys.excepthook is not sys.__excepthook__
    assert sys.excepthook == hook.exception_hook
    assert isolated_crash_reporting.exists()
    assert "Logging initialized" in isolated_crash_reporting.read_text(encoding="utf-8")


def test_install_crash_reporting_is_idempotent(
    isolated_crash_reporting: Path,
) -> None:
    """Test repeated installation reuses the same hook."""
    first = crash_logging.install_crash_reporting()
    second = crash_logging.install_crash_reporting()
    assert first is second


def test_launch_gui_installs_crash_reporting_first(monkeypatch: object) -> None:
    """Test the GUI entry point installs crash reporting before Qt startup."""
    calls = []

    class StopLaunch(Exception):
        """Sentinel raised to stop launch after crash reporting setup."""

    def fake_install() -> None:
        calls.append("install")

    def fake_set_style(*args: object) -> None:
        calls.append("qt")
        raise StopLaunch

    monkeypatch.setattr(bootstrap, "install_crash_reporting", fake_install)
    monkeypatch.setattr(bootstrap.QApplication, "setStyle", fake_set_style)
    with pytest.raises(StopLaunch):
        bootstrap.launch_gui()
    assert calls == ["install", "qt"]


def test_install_keeps_the_previous_log(isolated_crash_reporting: Path) -> None:
    """Test each launch moves the last log to ``latest.log.1`` instead of wiping it."""
    log_file = isolated_crash_reporting
    log_file.parent.mkdir(parents=True)
    log_file.write_text("last launch crashed here\n", encoding="utf-8")
    previous = log_file.with_name("latest.log.1")
    previous.write_text("two launches ago\n", encoding="utf-8")

    crash_logging.install_crash_reporting()

    assert previous.read_text(encoding="utf-8") == "last launch crashed here\n"
    current = log_file.read_text(encoding="utf-8")
    assert "last launch crashed here" not in current
    assert "Logging initialized" in current


def test_install_appends_when_the_old_log_cannot_be_moved(
    isolated_crash_reporting: Path, monkeypatch: object
) -> None:
    """Test a log locked by another instance is appended to, not truncated."""
    log_file = isolated_crash_reporting
    log_file.parent.mkdir(parents=True)
    log_file.write_text("still needed\n", encoding="utf-8")

    def locked(*args: object) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "replace", locked)
    crash_logging.install_crash_reporting()

    text = log_file.read_text(encoding="utf-8")
    assert text.startswith("still needed\n")
    assert "Could not move the previous log aside" in text


def test_install_sets_threading_excepthook(isolated_crash_reporting: Path) -> None:
    """Test worker-thread exceptions go through the crash hook too."""
    hook = crash_logging.install_crash_reporting()
    assert threading.excepthook == hook.thread_exception_hook


def test_thread_exception_is_logged_and_reported(
    isolated_crash_reporting: Path, monkeypatch: object
) -> None:
    """Test an exception escaping a thread is logged with its traceback."""
    hook = crash_logging.install_crash_reporting()
    reported = []
    monkeypatch.setattr(hook, "_exception_caught", _FakeSignal(reported))

    def boom() -> None:
        raise ValueError("worker exploded")

    worker = threading.Thread(target=boom, name="loader")
    worker.start()
    worker.join()

    text = isolated_crash_reporting.read_text(encoding="utf-8")
    assert "Uncaught exception in thread loader" in text
    assert "ValueError: worker exploded" in text
    assert reported and reported[0].endswith("ValueError: worker exploded")


class _FakeSignal:
    """Stand-in for the Qt signal that records emitted crash messages."""

    def __init__(self, sink: list) -> None:
        self._sink = sink

    def emit(self, message: str) -> None:
        self._sink.append(message)


def test_exception_box_shows_log_location_without_email(
    isolated_crash_reporting: Path, monkeypatch: object, qapp: object
) -> None:
    """Test the crash dialog points at the log file and offers no email."""
    shown = {}

    def fake_critical(
        parent: object, title: str, text: str, *args: object, **kwargs: object
    ) -> QMessageBox.StandardButton:
        shown.update(title=title, text=text, kwargs=kwargs)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", fake_critical)
    crash_logging.show_exception_box("Traceback...\nValueError: boom")

    assert shown["title"] == "Crashed!"
    assert "ValueError: boom" in shown["text"]
    assert str(isolated_crash_reporting) in shown["text"]
    assert "send a report" not in shown["text"].lower()
    assert "buttons" not in shown["kwargs"]
    assert not hasattr(crash_logging, "mailto")
