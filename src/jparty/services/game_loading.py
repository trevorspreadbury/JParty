"""Typed game-loading coordinator and compatibility helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from jparty.app.paths import SAVED_GAMES
from jparty.domain.models import GameData

from .game_cache import GameCache
from .game_parser import GameParser
from .game_sources import GameSourceFetcher

GOOGLE_SHEETS_ID_LENGTH = 7


class GameLoadStatus(str, Enum):
    """Describe the outcome of a game-load attempt."""

    SUCCESS = "success"
    CACHE_HIT = "cache_hit"
    INVALID_GAME = "invalid_game"
    NETWORK_ERROR = "network_error"
    MALFORMED_INPUT = "malformed_input"


@dataclass
class GameLoadResult:
    """Structured result for a game-load attempt."""

    status: GameLoadStatus
    game_data: GameData | None = None
    raw_payload: str | None = None
    source: str = ""
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        """Return whether the result contains playable game data."""
        return self.game_data is not None


class GameLoader:
    """Coordinate cache, remote fetch, and parsing for game loads."""

    def __init__(
        self,
        cache: GameCache | None = None,
        parser: GameParser | None = None,
        fetcher: GameSourceFetcher | None = None,
    ) -> None:
        """Initialize the loader with pluggable cache, parser, and fetcher."""
        self.cache = cache or GameCache(SAVED_GAMES)
        self.parser = parser or GameParser()
        self.fetcher = fetcher or GameSourceFetcher()

    def is_google_sheet_id(self, game_id: object) -> bool:
        """Return whether an identifier should be treated as a sheet id."""
        return len(str(game_id)) >= GOOGLE_SHEETS_ID_LENGTH

    def load_game_html(self, game_id: object) -> GameLoadResult:
        """Load archived game HTML from cache or remote fallbacks."""
        cached_html = self.cache.load_saved_html(game_id)
        if cached_html is not None:
            return GameLoadResult(
                status=GameLoadStatus.CACHE_HIT,
                raw_payload=cached_html,
                source="cache",
            )
        try:
            wayback_html = self.fetcher.get_wayback_game_html(game_id)
            return GameLoadResult(
                status=GameLoadStatus.SUCCESS,
                raw_payload=wayback_html,
                source="wayback",
            )
        except Exception as exc:
            logging.error("Wayback lookup failed for %s", game_id, exc_info=True)
            try:
                jarchive_html = self.fetcher.get_jarchive_game_html(game_id)
            except Exception as jarchive_exc:
                return GameLoadResult(
                    status=GameLoadStatus.NETWORK_ERROR,
                    source="jarchive",
                    error=jarchive_exc,
                )
            return GameLoadResult(
                status=GameLoadStatus.SUCCESS,
                raw_payload=jarchive_html,
                source="jarchive",
                error=exc,
            )

    def load_game(self, game_id: object) -> GameLoadResult:
        """Load a ``GameData`` payload from a supported identifier."""
        game_id_str = str(game_id).strip()
        if not game_id_str:
            return GameLoadResult(GameLoadStatus.MALFORMED_INPUT)
        if self.is_google_sheet_id(game_id_str):
            try:
                rows = self.fetcher.get_google_sheet_rows(game_id_str)
                return GameLoadResult(
                    status=GameLoadStatus.SUCCESS,
                    game_data=self.parser.list_to_game(rows),
                    source="google_sheets",
                )
            except Exception as exc:
                return GameLoadResult(
                    status=GameLoadStatus.NETWORK_ERROR,
                    source="google_sheets",
                    error=exc,
                )

        html_result = self.load_game_html(game_id_str)
        if html_result.raw_payload is None:
            return html_result
        game_data = self.parser.process_game_board_from_html(
            html_result.raw_payload, game_id_str
        )
        if game_data is None:
            return GameLoadResult(
                status=GameLoadStatus.INVALID_GAME,
                raw_payload=html_result.raw_payload,
                source=html_result.source,
                error=html_result.error,
            )
        return GameLoadResult(
            status=html_result.status,
            game_data=game_data,
            raw_payload=html_result.raw_payload,
            source=html_result.source,
            error=html_result.error,
        )

    def save_game_html(self, game_id: object) -> object:
        """Persist cached or fetched HTML for a numeric J-Archive game id."""
        game_id_str = str(game_id)
        if self.is_google_sheet_id(game_id_str):
            return None
        loaded_html = self.cache.get_loaded_html(game_id_str)
        if loaded_html is None:
            html_result = self.load_game_html(game_id_str)
            if html_result.raw_payload is None:
                return None
            loaded_html = html_result.raw_payload
        return self.cache.save_html(game_id_str, loaded_html)


DEFAULT_GAME_CACHE = GameCache(SAVED_GAMES)
DEFAULT_GAME_PARSER = GameParser()
DEFAULT_GAME_FETCHER = GameSourceFetcher()
DEFAULT_GAME_LOADER = GameLoader(
    cache=DEFAULT_GAME_CACHE,
    parser=DEFAULT_GAME_PARSER,
    fetcher=DEFAULT_GAME_FETCHER,
)
