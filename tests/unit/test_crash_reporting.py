"""Test crash reporting setup module."""

import logging
import sys
from pathlib import Path

import pytest
from jparty.app import bootstrap
from jparty.app import logging as crash_logging
from PyQt6.QtWidgets import QMessageBox

pytestmark = pytest.mark.unit


@pytest.fixture
def isolated_crash_reporting(monkeypatch: object, tmp_path: Path) -> Path:
    """Redirect the log file and restore global hook/logging state afterwards."""
    log_file = tmp_path / "logs" / "latest.log"
    monkeypatch.setattr(crash_logging, "LOG_FILE", log_file)
    monkeypatch.setattr(crash_logging, "_installed_hook", None)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
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


def test_exception_box_reads_non_cp1252_log(
    isolated_crash_reporting: Path, monkeypatch: object, qapp: object
) -> None:
    """Test the crash dialog can attach logs containing emoji player names."""
    log_file = isolated_crash_reporting
    log_file.parent.mkdir(parents=True)
    log_file.write_bytes("Player joined: \U0001f389 Ana\n".encode() + b"\xff\n")
    sent = {}
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        crash_logging,
        "mailto",
        lambda recipients, subject, body: sent.update(body=body),
    )
    crash_logging.show_exception_box("boom")
    assert "\U0001f389 Ana" in sent["body"]
