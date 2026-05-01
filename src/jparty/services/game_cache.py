"""Persistent cache helpers for archived game HTML."""

from __future__ import annotations

import logging
from pathlib import Path


class GameCache:
    """Read and write cached J-Archive game HTML files."""

    def __init__(self, saved_games_dir: Path) -> None:
        """Store the directory used for cached game HTML."""
        self.saved_games_dir = saved_games_dir
        self._loaded_html_cache: dict[str, str] = {}

    def load_saved_html(self, game_id: object) -> str | None:
        """Return cached HTML for a game id when available."""
        saved_game_path = self.saved_games_dir / f"{game_id}.html"
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
        """Persist HTML for a game id and return the written path."""
        saved_game_path = self.saved_games_dir / f"{game_id}.html"
        saved_game_path.write_text(game_html, encoding="utf-8")
        self._loaded_html_cache[str(game_id)] = game_html
        return saved_game_path

    def get_loaded_html(self, game_id: object) -> str | None:
        """Return in-memory loaded HTML for a game id when present."""
        return self._loaded_html_cache.get(str(game_id))
