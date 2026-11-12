"""Unit tests for board composition and parsing helpers."""

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
from jparty.services.game_parser import GameParser

pytestmark = pytest.mark.unit


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


def test_original_board_row_values_ignore_daily_double_value(
    fixture_dir: object,
) -> None:
    """Test a Daily Double in category 0 does not set its row's value.

    J-Archive shows a Daily Double's wager instead of its board value, so the
    parser gives it a fallback from the modern value table. In a pre-2001 game
    that fallback is double the real value, and it used to set the whole row.
    """
    game = _parsed_4453_without(fixture_dir, 0, set())
    first_category_clue = next(
        question for question in game.rounds[0].questions if question.index == (0, 4)
    )
    first_category_clue.dd = True
    first_category_clue.value = 5000
    assert original_board_row_values(game, 0) == [200, 400, 600, 800, 1000]


def test_original_board_row_values_fall_back_when_only_a_daily_double_remains(
    fixture_dir: object,
) -> None:
    """Test a row whose only clue is a Daily Double uses the default ladder."""
    others_in_row = {(col, 3) for col in range(1, 6)}
    game = _parsed_4453_without(fixture_dir, 0, others_in_row)
    remaining = next(
        question for question in game.rounds[0].questions if question.index == (0, 3)
    )
    remaining.dd = True
    remaining.value = 5000
    assert original_board_row_values(game, 0) == [200, 400, 600, 800, 1000]


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
