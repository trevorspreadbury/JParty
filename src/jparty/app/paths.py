"""Resolve writable data directories and packaged asset locations.

This module chooses a writable user-data root for caches, logs, and persisted
game state, then exposes convenience paths for those subdirectories. It also
provides helpers for locating packaged application assets that ship inside the
installed ``jparty`` distribution.
"""

import os
from importlib import resources
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from .config import APP_NAME

REQUIRED_SUBDIRS = ("saved_games", "question_media", "game_states", "game_scores")
load_dotenv(find_dotenv(usecwd=True), override=False)


def _candidate_user_data_roots() -> object:
    """Yield possible filesystem locations for JParty user data.

    The search order considers explicit environment overrides first, then
    platform-appropriate defaults, and finally a workspace-local fallback.

    Returns:
        An iterator of ``Path`` objects representing candidate writable roots.
    """
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
    """Create the user-data root and required subdirectories if needed.

    Args:
        path: Candidate root directory to create and populate.

    Returns:
        The same ``Path`` once the root and required subdirectories exist.
    """
    path.mkdir(parents=True, exist_ok=True)
    for subdir in REQUIRED_SUBDIRS:
        (path / subdir).mkdir(parents=True, exist_ok=True)
    return path


def _default_user_data_root() -> Path:
    """Choose the first writable user-data root from the candidate list.

    Returns:
        A writable ``Path`` that contains the required JParty data
        subdirectories.

    Raises:
        RuntimeError: If no candidate directory can be created successfully.
    """
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
    """Return the installed package root directory for ``jparty``.

    Returns:
        A ``Path`` pointing at the root of the installed ``jparty`` package.
    """
    return Path(resources.files("jparty"))


def asset_root() -> Path:
    """Return the base directory that contains packaged application assets.

    Returns:
        A ``Path`` pointing at the package's ``assets`` directory.
    """
    return package_root() / "assets"


def asset_path(*parts: str) -> Path:
    """Build a path inside the packaged assets directory.

    Args:
        *parts: Additional path components appended beneath ``asset_root()``.

    Returns:
        A ``Path`` for the requested packaged asset.
    """
    return asset_root().joinpath(*parts)


def data_asset_path(*parts: str) -> Path:
    """Build a path inside the packaged data assets directory.

    Args:
        *parts: Additional path components appended beneath ``assets/data``.

    Returns:
        A ``Path`` for the requested packaged data asset.
    """
    return asset_path("data", *parts)


def web_asset_path(*parts: str) -> Path:
    """Build a path inside the packaged buzzer web assets directory.

    Args:
        *parts: Additional path components appended beneath ``assets/buzzer``.

    Returns:
        A ``Path`` for the requested packaged web asset.
    """
    return asset_path("buzzer", *parts)
