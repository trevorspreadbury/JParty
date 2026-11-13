"""Tests for the headless ``jparty self-check`` command."""

import subprocess
import sys
from pathlib import Path

import pytest

from jparty.app import self_check
from jparty.app.bootstrap import main

pytestmark = pytest.mark.qt

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_self_check_passes_on_a_working_install(qapp: object, tmp_path: Path) -> None:
    """Every check should pass in the development environment."""
    report = tmp_path / "report.txt"

    assert self_check.run_self_check(str(report)) == 0

    text = report.read_text(encoding="utf-8")
    for name, _check in self_check.CHECKS:
        assert f"PASS {name}:" in text
    assert text.rstrip().endswith("SELF-CHECK PASSED")


def test_self_check_reports_a_missing_asset(
    qapp: object, tmp_path: Path, monkeypatch: object
) -> None:
    """A missing bundled asset should fail the check and name the file."""
    from jparty.ui.widgets import common

    real_resource_path = common.resource_path
    monkeypatch.setattr(
        common,
        "resource_path",
        lambda name: (
            str(tmp_path / "missing.wav")
            if name == "dd.wav"
            else real_resource_path(name)
        ),
    )
    report = tmp_path / "report.txt"

    assert self_check.run_self_check(str(report)) == 1

    text = report.read_text(encoding="utf-8")
    assert "FAIL assets:" in text
    assert "missing.wav" in text
    assert text.rstrip().endswith("SELF-CHECK FAILED")


def test_self_check_fails_when_metadata_version_is_stale(
    qapp: object, tmp_path: Path, monkeypatch: object
) -> None:
    """Metadata that disagrees with ``jparty.__version__`` should fail the check.

    This is what an install looks like after ``_version.py`` is bumped without
    reinstalling the package.
    """
    monkeypatch.setattr(self_check, "version", lambda name: "0.0.1")
    report = tmp_path / "report.txt"

    assert self_check.run_self_check(str(report)) == 1

    text = report.read_text(encoding="utf-8")
    assert "FAIL package metadata:" in text
    assert "0.0.1" in text
    assert "--reinstall-package jparty" in text


def test_cli_returns_self_check_exit_code(
    qapp: object, tmp_path: Path, monkeypatch: object
) -> None:
    """``jparty self-check`` should return the check's exit code."""
    monkeypatch.setattr(self_check, "run_self_check", lambda report=None: 1)

    assert main(["self-check", "--report", str(tmp_path / "r.txt")]) == 1


def test_module_entry_point_passes_exit_code_to_the_os() -> None:
    """``jparty/__main__.py`` (the PyInstaller entry point) must keep exit codes.

    The packaged app starts through ``jparty/__main__.py``. If it ignored the
    return value of ``main()``, a failing self-check would still exit 0.
    """
    script = (
        "import runpy, sys\n"
        "import jparty.app.self_check as sc\n"
        "sc.run_self_check = lambda report=None: 1\n"
        "sys.argv = ['jparty', 'self-check']\n"
        "runpy.run_module('jparty', run_name='__main__')\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
