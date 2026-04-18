import os
from importlib import resources
from pathlib import Path

from .config import APP_NAME


def _default_user_data_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


USER_DATA_ROOT = Path(os.environ.get("JPARTY_DATA_DIR", _default_user_data_root()))
USER_DATA_ROOT.mkdir(parents=True, exist_ok=True)

SAVED_GAMES = USER_DATA_ROOT / "saved_games"
QUESTION_MEDIA = USER_DATA_ROOT / "question_media"
GAME_STATES_DIR = USER_DATA_ROOT / "game_states"
GAME_SCORES_DIR = USER_DATA_ROOT / "game_scores"
LOG_FILE = USER_DATA_ROOT / "latest.log"

for directory in (SAVED_GAMES, QUESTION_MEDIA, GAME_STATES_DIR, GAME_SCORES_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def package_root() -> Path:
    return Path(resources.files("jparty"))


def asset_root() -> Path:
    return package_root() / "assets"


def asset_path(*parts: str) -> Path:
    return asset_root().joinpath(*parts)


def data_asset_path(*parts: str) -> Path:
    return asset_path("data", *parts)


def web_asset_path(*parts: str) -> Path:
    return asset_path("buzzer", *parts)
