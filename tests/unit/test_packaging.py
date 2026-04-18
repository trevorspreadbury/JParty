import os
import subprocess
import sys
from pathlib import Path

import pytest

from jparty.app import bootstrap


pytestmark = pytest.mark.unit


def test_pyproject_declares_console_script():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '[project.scripts]' in pyproject
    assert 'jparty = "jparty.app.bootstrap:main"' in pyproject


def test_module_entrypoint_delegates_to_bootstrap():
    import jparty.__main__ as module_entry

    assert module_entry.main is bootstrap.main


def test_module_import_works_from_non_repo_cwd(temp_dir):
    src_dir = Path(__file__).resolve().parents[2] / "src"
    script = (
        "import os, sys; "
        f"os.chdir(r'{temp_dir}'); "
        f"sys.path.insert(0, r'{src_dir}'); "
        "import jparty.__main__; "
        "print('ok')"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "JPARTY_DATA_DIR": str(temp_dir / 'user_data')},
    )

    assert completed.stdout.strip() == "ok"
