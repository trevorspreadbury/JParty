"""Persistent cache helpers for archived game HTML."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> Path:
    """Write ``text`` to ``path`` so readers never see a partial file.

    The text goes to a temporary file in the same directory first, which is
    then moved over ``path`` with ``os.replace``. If the process dies part way
    through, ``path`` is either missing or still holds its previous contents.

    Args:
        path: Destination file.
        text: UTF-8 text to write.

    Returns:
        ``path``.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            temp_file.write(text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        Path(temp_name).replace(path)
    except BaseException:
        try:
            Path(temp_name).unlink()
        except OSError:
            pass
        raise
    return path


class GameCache:
    """Read and write cached J-Archive game HTML files."""

    def __init__(self, saved_games_dir: Path) -> None:
        """Store the directory used for cached game HTML."""
        self.saved_games_dir = saved_games_dir
        self._loaded_html_cache: dict[str, str] = {}

    def saved_html_path(self, game_id: object) -> Path:
        """Return the cache file path for a game id."""
        return self.saved_games_dir / f"{game_id}.html"

    def load_saved_html(self, game_id: object) -> str | None:
        """Return cached HTML for a game id when available."""
        saved_game_path = self.saved_html_path(game_id)
        if not saved_game_path.exists():
            return None
        try:
            game_html = saved_game_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logging.warning(
                "Cached game %s could not be decoded as UTF-8; refetching",
                game_id,
            )
            return None
        self._loaded_html_cache[str(game_id)] = game_html
        return game_html

    def save_html(self, game_id: object, game_html: str) -> Path:
        """Persist HTML for a game id atomically and return the written path."""
        saved_game_path = write_text_atomic(self.saved_html_path(game_id), game_html)
        self._loaded_html_cache[str(game_id)] = game_html
        return saved_game_path

    def get_loaded_html(self, game_id: object) -> str | None:
        """Return in-memory loaded HTML for a game id when present."""
        return self._loaded_html_cache.get(str(game_id))
