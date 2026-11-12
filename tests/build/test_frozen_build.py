"""Build smoke test: build the PyInstaller app and run its self-check.

This takes several minutes, so it only runs when ``JPARTY_RUN_BUILD_TEST=1``
is set, and it needs the ``build`` extra::

    JPARTY_RUN_BUILD_TEST=1 uv run --extra build pytest tests/build -q

It builds into a temporary folder (not ``dist/``), launches the packaged app
with ``self-check``, and checks the exit code and report. That catches broken
specs, missing bundled assets or Qt plugins, and libraries PyInstaller can't
bundle, which a normal test run never sees.
"""

import importlib.util
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.build,
    pytest.mark.skipif(
        os.environ.get("JPARTY_RUN_BUILD_TEST") != "1",
        reason="set JPARTY_RUN_BUILD_TEST=1 to build the app (takes minutes)",
    ),
    pytest.mark.skipif(
        importlib.util.find_spec("PyInstaller") is None,
        reason="needs the build extra: uv run --extra build ...",
    ),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_TIMEOUT_SECONDS = 1200
SELF_CHECK_TIMEOUT_SECONDS = 180


def _packaged_app(dist_dir: Path) -> Path:
    """Return the path of the packaged executable for this platform."""
    if sys.platform == "darwin":
        return dist_dir / "JParty.app" / "Contents" / "MacOS" / "JParty"
    return dist_dir / ("JParty.exe" if os.name == "nt" else "JParty")


def test_packaged_app_passes_self_check(tmp_path: Path) -> None:
    """The documented spec should build an app whose self-check passes."""
    dist_dir = tmp_path / "dist"
    build = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "-y",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(tmp_path / "build"),
            "JParty.spec",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=BUILD_TIMEOUT_SECONDS,
        check=False,
    )
    assert build.returncode == 0, build.stderr[-4000:]
    app = _packaged_app(dist_dir)
    assert app.exists(), f"no packaged app at {app}"

    report = tmp_path / "self-check.txt"
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(  # noqa: S603 - path built above, fixed arguments
        [str(app), "self-check", "--report", str(report)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=SELF_CHECK_TIMEOUT_SECONDS,
        check=False,
    )
    text = report.read_text(encoding="utf-8") if report.exists() else "(no report)"
    assert result.returncode == 0, text + result.stderr[-2000:]
    assert text.rstrip().endswith("SELF-CHECK PASSED"), text
    # The packaged app must read its version from bundled package metadata.
    assert f"PASS package metadata: jparty {version('jparty')}" in text, text
