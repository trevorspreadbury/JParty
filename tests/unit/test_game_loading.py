"""Unit tests for structured game loading services."""

import random

import pytest
from bs4 import BeautifulSoup
from jparty.domain.models import Board, FinalBoard, GameData, Question
from jparty.services.game_loader import (
    build_game_from_board_selection_configs,
    normalize_standard_board_daily_doubles,
    original_board_row_values,
    standard_board_daily_double_indices,
)
from jparty.services.game_loading import GameLoader, GameLoadStatus
from jparty.services.game_parser import GameParser

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


def test_normalize_standard_board_daily_doubles_caps_count_and_avoids_categories() -> (
    None
):
    """Requested Daily Doubles should cap at six and stay category-unique."""
    categories = [f"Cat {index}" for index in range(6)]
    board = Board(
        categories,
        [
            Question((col, row), f"Q {col}-{row}", f"A {col}-{row}", categories[col])
            for col in range(6)
            for row in range(5)
        ],
    )

    normalize_standard_board_daily_doubles(
        board,
        requested_count=9,
        rng=random.Random(0),  # noqa: S311
    )

    daily_double_indices = standard_board_daily_double_indices(board)
    assert len(daily_double_indices) == 6
    assert (
        len(
            {
                board.get_question(index[0], index[1]).category
                for index in daily_double_indices
            }
        )
        == 6
    )


def test_build_game_from_board_selection_configs_uses_saved_daily_double_locations(
    monkeypatch: object,
) -> None:
    """Saved Daily Double coordinates should rebuild the same board layout."""
    categories = [f"Cat {index}" for index in range(6)]
    source = GameData(
        [
            Board(
                categories,
                [
                    Question(
                        (col, row),
                        f"Q {col}-{row}",
                        f"A {col}-{row}",
                        categories[col],
                        value=200 * (row + 1),
                    )
                    for col in range(6)
                    for row in range(5)
                ],
            ),
            FinalBoard("Final", Question((0, 0), "FQ", "FA", "Final")),
        ],
        "January 1, 2026",
        "Fixture",
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": source}[game_id],
    )

    composed = build_game_from_board_selection_configs(
        [
            {
                "game_id": "111",
                "source_round_index": 0,
                "source_round_label": "Jeopardy!",
                "board_type": "standard",
                "row_values": [200, 400, 600, 800, 1000],
                "daily_double_count": 2,
                "daily_double_indices": [[0, 1], [4, 3]],
            }
        ]
    )

    assert composed is not None
    assert standard_board_daily_double_indices(composed.rounds[0]) == [[0, 1], [4, 3]]


def test_game_parser_normalizes_comments_and_image_flags(
    fixture_dir: object,
) -> None:
    """Parsed J-Archive games should not retain BeautifulSoup objects."""
    html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    parser = GameParser()

    game = parser.process_game_board_from_html(html, "4453")
    assert game is not None
    assert isinstance(game.comments, str)
    assert all(
        isinstance(question.image, bool)
        for round_data in game.rounds
        for question in getattr(round_data, "questions", [])
    )

    date, comments = parser.get_game_sum(BeautifulSoup(html, "html.parser"))
    assert isinstance(date, str)
    assert isinstance(comments, str)
    assert comments == game.comments


def _parsed_4453_without(fixture_dir: object, round_index: int, indices: set) -> object:
    """Parse the 4453 fixture and drop the given clues from one round."""
    html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    game = GameParser().process_game_board_from_html(html, "4453")
    assert game is not None
    round_data = game.rounds[round_index]
    round_data.questions = [
        question for question in round_data.questions if question.index not in indices
    ]
    return game


def test_original_board_row_values_ignore_gap_in_first_category(
    fixture_dir: object,
) -> None:
    """Test a missing clue in category 0 does not shift the row values (#53)."""
    game = _parsed_4453_without(fixture_dir, 0, {(0, 2)})
    assert original_board_row_values(game, 0) == [200, 400, 600, 800, 1000]
    assert original_board_row_values(game, 1) == [400, 800, 1200, 1600, 2000]
    assert original_board_row_values(game, 2) == []


def test_original_board_row_values_fall_back_for_an_empty_row(
    fixture_dir: object,
) -> None:
    """Test a row with no clues uses the default ladder for that board."""
    empty_row = {(col, 2) for col in range(6)}
    game = _parsed_4453_without(fixture_dir, 1, empty_row)
    assert original_board_row_values(game, 1) == [400, 800, 1200, 1600, 2000]


def test_compose_with_gap_in_first_category_keeps_every_column_value(
    fixture_dir: object, monkeypatch: object
) -> None:
    """Test composing a board with a category-0 gap keeps each row's value."""
    game = _parsed_4453_without(fixture_dir, 0, {(0, 2)})
    monkeypatch.setattr("jparty.services.game_loader.get_game", lambda game_id: game)
    composed = build_game_from_board_selection_configs(
        [
            {
                "game_id": "4453",
                "source_round_index": 0,
                "board_type": "standard",
                "row_values": original_board_row_values(game, 0),
            }
        ]
    )
    assert composed is not None
    for question in composed.rounds[0].questions:
        assert question.value == (question.index[1] + 1) * 200
