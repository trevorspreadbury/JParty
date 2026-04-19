"""Paths module."""

import os
from importlib import resources
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from .config import APP_NAME

REQUIRED_SUBDIRS = ("saved_games", "question_media", "game_states", "game_scores")
load_dotenv(find_dotenv(usecwd=True), override=False)


def _candidate_user_data_roots() -> object:
    """Return candidate user data roots."""
    override = os.environ.get("DATA_DIR") or os.environ.get("JPARTY_DATA_DIR")
    if override:
        yield Path(override)
    if os.name == "nt":
        for env_name in ("LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(env_name)
            if base:
                yield (Path(base) / APP_NAME)
        yield (Path.home() / f".{APP_NAME.lower()}")
        yield (Path.cwd() / ".jparty-data")
        return
    yield (Path.home() / ".local" / "share" / APP_NAME)
    yield (Path.home() / f".{APP_NAME.lower()}")
    yield (Path.cwd() / ".jparty-data")


def _prepare_user_data_root(path: Path) -> Path:
    """Return prepare user data root."""
    path.mkdir(parents=True, exist_ok=True)
    for subdir in REQUIRED_SUBDIRS:
        (path / subdir).mkdir(parents=True, exist_ok=True)
    return path


def _default_user_data_root() -> Path:
    """Return default user data root."""
    last_error = None
    for candidate in _candidate_user_data_roots():
        try:
            return _prepare_user_data_root(candidate)
        except OSError as exc:
            last_error = exc
            continue
    raise RuntimeError(
        "Could not create a writable JParty data directory"
    ) from last_error


USER_DATA_ROOT = _default_user_data_root()
SAVED_GAMES = USER_DATA_ROOT / "saved_games"
QUESTION_MEDIA = USER_DATA_ROOT / "question_media"
GAME_STATES_DIR = USER_DATA_ROOT / "game_states"
GAME_SCORES_DIR = USER_DATA_ROOT / "game_scores"
LOG_FILE = USER_DATA_ROOT / "latest.log"


def package_root() -> Path:
    """Run package root."""
    return Path(resources.files("jparty"))


def asset_root() -> Path:
    """Run asset root."""
    return package_root() / "assets"


def asset_path(*parts: str) -> Path:
    """Run asset path."""
    return asset_root().joinpath(*parts)


def data_asset_path(*parts: str) -> Path:
    """Run data asset path."""
    return asset_path("data", *parts)


def web_asset_path(*parts: str) -> Path:
    """Run web asset path."""
    return asset_path("buzzer", *parts)
