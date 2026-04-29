"""Unit tests for structured game loading services."""

import pytest
from jparty.domain.models import Board, FinalBoard, GameData, Question
from jparty.services.game_loading import GameLoader, GameLoadStatus

pytestmark = pytest.mark.unit


class StubCache:
    """Minimal cache stub for game-loader tests."""

    def __init__(self, html: str | None = None) -> None:
        """Store one optional cached HTML payload."""
        self.html = html
        self.saved = {}

    def load_saved_html(self, game_id: object) -> str | None:
        """Return cached HTML when configured."""
        return self.html

    def save_html(self, game_id: object, game_html: str) -> str:
        """Record a saved HTML payload."""
        self.saved[str(game_id)] = game_html
        return str(game_id)

    def get_loaded_html(self, game_id: object) -> str | None:
        """Return an already-loaded HTML payload when present."""
        return self.saved.get(str(game_id))


class StubFetcher:
    """Minimal remote fetcher stub for game-loader tests."""

    def __init__(self) -> None:
        """Configure fetcher call behavior."""
        self.wayback_html = "<html>wayback</html>"
        self.jarchive_html = "<html>jarchive</html>"
        self.sheet_rows = [["meta"]]
        self.raise_wayback = False
        self.raise_sheets = False

    def get_wayback_game_html(self, game_id: object) -> str:
        """Return Wayback HTML or raise."""
        if self.raise_wayback:
            raise RuntimeError("wayback failed")
        return self.wayback_html

    def get_jarchive_game_html(self, game_id: object) -> str:
        """Return direct J-Archive HTML."""
        return self.jarchive_html

    def get_google_sheet_rows(self, file_id: object) -> list[list[str]]:
        """Return sheet rows or raise."""
        if self.raise_sheets:
            raise RuntimeError("sheets failed")
        return self.sheet_rows


class StubParser:
    """Minimal parser stub for game-loader tests."""

    def __init__(self) -> None:
        """Configure parser behavior."""
        self.game = GameData(
            [
                Board(["Cat"], [Question((0, 0), "Q", "A", "Cat")]),
                FinalBoard("Final", Question((0, 0), "FQ", "FA", "Final")),
            ],
            "January 1, 2026",
            "Fixture",
        )
        self.return_none = False

    def process_game_board_from_html(self, html: object, game_id: object) -> object:
        """Return a parsed game or ``None``."""
        if self.return_none:
            return None
        return self.game

    def list_to_game(self, rows: list[list[str]]) -> object:
        """Return a parsed sheet-backed game."""
        return self.game


def test_game_loader_prefers_cache_hit() -> None:
    """Cached HTML should return a cache-hit result without remote fetches."""
    loader = GameLoader(
        cache=StubCache("<html>cached</html>"),
        parser=StubParser(),
        fetcher=StubFetcher(),
    )

    result = loader.load_game("4453")

    assert result.status == GameLoadStatus.CACHE_HIT
    assert result.game_data is not None
    assert result.source == "cache"


def test_game_loader_falls_back_to_jarchive_after_wayback_failure() -> None:
    """Wayback errors should fall back to direct J-Archive fetches."""
    fetcher = StubFetcher()
    fetcher.raise_wayback = True
    loader = GameLoader(cache=StubCache(None), parser=StubParser(), fetcher=fetcher)

    result = loader.load_game("4453")

    assert result.status == GameLoadStatus.SUCCESS
    assert result.source == "jarchive"


def test_game_loader_returns_invalid_for_unparseable_html() -> None:
    """Parser failures should return a typed invalid-game result."""
    parser = StubParser()
    parser.return_none = True
    loader = GameLoader(cache=StubCache(None), parser=parser, fetcher=StubFetcher())

    result = loader.load_game("4453")

    assert result.status == GameLoadStatus.INVALID_GAME
    assert result.game_data is None


def test_game_loader_reports_google_sheet_failures() -> None:
    """Google Sheets fetch failures should surface as network errors."""
    fetcher = StubFetcher()
    fetcher.raise_sheets = True
    loader = GameLoader(cache=StubCache(None), parser=StubParser(), fetcher=fetcher)

    result = loader.load_game("abcdefg")

    assert result.status == GameLoadStatus.NETWORK_ERROR
    assert result.source == "google_sheets"


def test_game_loader_save_game_html_persists_loaded_html() -> None:
    """Saving HTML should write fetched payloads into the cache."""
    cache = StubCache(None)
    loader = GameLoader(cache=cache, parser=StubParser(), fetcher=StubFetcher())

    loader.save_game_html("4453")

    assert cache.saved["4453"] == "<html>wayback</html>"
