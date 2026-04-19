"""Test packaging module."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from jparty.app import bootstrap

pytestmark = pytest.mark.unit


def test_pyproject_declares_console_script() -> None:
    """Test test pyproject declares console script."""
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" in pyproject
    assert 'jparty = "jparty.app.bootstrap:main"' in pyproject


def test_module_entrypoint_delegates_to_bootstrap() -> None:
    """Test test module entrypoint delegates to bootstrap."""
    import jparty.__main__ as module_entry

    assert module_entry.main is bootstrap.main


def test_module_import_works_from_non_repo_cwd(temp_dir: object) -> None:
    """Test test module import works from non repo cwd."""
    src_dir = Path(__file__).resolve().parents[2] / "src"
    script = f"import os, sys; os.chdir(r'{temp_dir}'); sys.path.insert(0, r'{src_dir}'); import jparty.__main__; print('ok')"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "JPARTY_DATA_DIR": str(temp_dir / "user_data"),
        },
    )
    assert completed.stdout.strip() == "ok"


def test_data_dir_can_be_loaded_from_dotenv(temp_dir: object) -> None:
    """Test test data dir can be loaded from dotenv."""
    src_dir = Path(__file__).resolve().parents[2] / "src"
    data_dir = temp_dir / "custom-data"
    (temp_dir / ".env").write_text(f"DATA_DIR={data_dir}\n", encoding="utf-8")
    script = f"import os, sys; os.chdir(r'{temp_dir}'); sys.path.insert(0, r'{src_dir}'); import jparty.app.paths as paths; print(os.environ['DATA_DIR']); print(paths.USER_DATA_ROOT)"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={
            key: value
            for (key, value) in {**os.environ, "QT_QPA_PLATFORM": "offscreen"}.items()
            if key not in {"DATA_DIR", "JPARTY_DATA_DIR"}
        },
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    assert Path(lines[0]) == data_dir
    assert Path(lines[1]) == data_dir


def test_expand_game_id_inputs_supports_ids_and_text_files(temp_dir: object) -> None:
    """Test test expand game id inputs supports ids and text files."""
    game_ids_file = temp_dir / "games.txt"
    game_ids_file.write_text("4453\n# comment\n4454\n\n4455\n", encoding="utf-8")
    game_ids = bootstrap.expand_game_id_inputs(["4452", str(game_ids_file)])
    assert game_ids == ["4452", "4453", "4454", "4455"]


def test_main_download_dispatches_to_downloader(monkeypatch: object) -> None:
    """Test test main download dispatches to downloader."""
    recorded = {}
    monkeypatch.setattr(
        bootstrap,
        "download_games",
        lambda inputs, delay_seconds=5: recorded.update(
            {"inputs": inputs, "delay": delay_seconds}
        ),
    )
    result = bootstrap.main(["download", "4453", "4454"])
    assert result == 0
    assert recorded == {"inputs": ["4453", "4454"], "delay": 5}


def test_download_games_skips_existing_and_supports_file_inputs(
    temp_dir: object, monkeypatch: object, capsys: object
) -> None:
    """Test test download games skips existing and supports file inputs."""
    game_ids_file = temp_dir / "games.txt"
    game_ids_file.write_text("4454\n", encoding="utf-8")
    saved_dir = temp_dir / "saved_games"
    saved_dir.mkdir()
    (saved_dir / "4453.html").write_text("existing", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(
        bootstrap, "get_game_html", lambda game_id: f"<html>{game_id}</html>"
    )
    monkeypatch.setattr(
        bootstrap, "process_game_board_from_html", lambda html, game_id: object()
    )
    monkeypatch.setattr(bootstrap.time, "sleep", lambda seconds: None)
    downloaded = bootstrap.download_games(["4453", str(game_ids_file)], delay_seconds=0)
    captured = capsys.readouterr()
    assert downloaded == ["4454"]
    assert "Game already saved" in captured.out
    assert (saved_dir / "4454.html").read_text(encoding="utf-8") == "<html>4454</html>"
