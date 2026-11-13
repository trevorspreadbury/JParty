"""Unit tests for board composition and parsing helpers."""

import random

import pytest
from bs4 import BeautifulSoup

from jparty.domain.models import Board, FinalBoard, GameData, Question
from jparty.services.game_loader import (
    RANDOM_GAME_MAX_ATTEMPTS,
    build_game_from_board_selection_configs,
    find_random_game,
    normalize_standard_board_daily_doubles,
    original_board_row_values,
    round_matches_board_type,
    select_advanced_daily_double_indices,
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


def _board_with_daily_doubles(daily_double_indices: set) -> Board:
    """Return a full 6x5 board with Daily Doubles at ``daily_double_indices``."""
    categories = [f"Cat {index}" for index in range(6)]
    questions = [
        Question((col, row), f"Q {col}-{row}", f"A {col}-{row}", categories[col])
        for col in range(6)
        for row in range(5)
    ]
    for question in questions:
        question.dd = question.index in daily_double_indices
    return Board(categories, questions)


def test_select_advanced_daily_doubles_matching_count_returns_originals() -> None:
    """Asking for the original count keeps exactly the original Daily Doubles."""
    board = _board_with_daily_doubles({(1, 2), (4, 3)})

    assert select_advanced_daily_double_indices(board, 2) == [[1, 2], [4, 3]]


def test_select_advanced_daily_doubles_adds_extras_on_top_of_originals() -> None:
    """Extra Daily Doubles are added after every original one."""
    board = _board_with_daily_doubles({(1, 2)})

    selected = select_advanced_daily_double_indices(
        board, 3, existing_daily_double_indices=[(0, 4), [1, 2], (5, 1), (2, 2)]
    )

    assert selected == [[1, 2], [0, 4], [5, 1]]


def test_select_advanced_daily_doubles_without_extras_returns_originals() -> None:
    """Missing extras are left for ``normalize_standard_board_daily_doubles``."""
    board = _board_with_daily_doubles({(1, 2)})

    assert select_advanced_daily_double_indices(board, 3) == [[1, 2]]


def test_select_advanced_daily_doubles_fewer_keeps_a_subset_of_originals() -> None:
    """Asking for fewer keeps only original Daily Doubles."""
    board = _board_with_daily_doubles({(1, 2), (4, 3), (5, 0)})

    selected = select_advanced_daily_double_indices(
        board,
        2,
        rng=random.Random(0),  # noqa: S311
    )

    assert len(selected) == 2
    assert {tuple(index) for index in selected} <= {(1, 2), (4, 3), (5, 0)}


def test_select_advanced_daily_doubles_fewer_reuses_existing_subset() -> None:
    """An existing subset of the right size is kept, so the layout is stable."""
    board = _board_with_daily_doubles({(1, 2), (4, 3), (5, 0)})

    selected = select_advanced_daily_double_indices(
        board, 1, existing_daily_double_indices=[(0, 0), (4, 3)]
    )

    assert selected == [[4, 3]]


def test_round_matches_board_type() -> None:
    """Standard slots take boards and final slots take Final Jeopardy."""
    board = _board_with_daily_doubles(set())
    final = FinalBoard("Final", Question((0, 0), "Q", "A", "Final"))

    assert round_matches_board_type(board, "standard") is True
    assert round_matches_board_type(final, "standard") is False
    assert round_matches_board_type(final, "final") is True
    assert round_matches_board_type(board, "final") is False


def test_has_missing_daily_double_uses_expected_counts() -> None:
    """Requested counts replace the regular-game rule of i + 1 per board."""
    game = GameData(
        [
            _board_with_daily_doubles({(0, 0)}),
            _board_with_daily_doubles({(0, 0), (1, 1)}),
            _board_with_daily_doubles({(0, 0), (1, 1)}),
        ],
        "date",
        "comments",
    )

    assert game.has_missing_daily_double() is True
    assert game.has_missing_daily_double([1, 2, 2]) is False
    assert game.has_missing_daily_double([1, 2, 3]) is True


def test_find_random_game_returns_the_first_accepted_game() -> None:
    """Random keeps trying until a game passes ``accept``."""
    ids = iter([1, 2, 3])
    games = {"1": None, "2": GameData([], "bad", ""), "3": GameData([], "good", "")}

    game_id, data = find_random_game(
        lambda candidate: candidate.date == "good",
        pick_game_id=lambda: next(ids),
        load_game=lambda game_id: games[game_id],
    )

    assert game_id == "3"
    assert data is games["3"]


def test_find_random_game_keeps_trying_after_an_error() -> None:
    """One failed fetch costs one try instead of ending the search (#102)."""
    good = GameData([], "good", "")
    results = iter([ConnectionError("blip"), good])

    def load(game_id: str) -> object:
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    assert find_random_game(
        lambda candidate: True, pick_game_id=lambda: 7, load_game=load
    ) == ("7", good)


def test_find_random_game_stops_after_max_attempts() -> None:
    """A run of games that won't parse can't keep hitting the network (#102)."""
    calls = []

    def load(game_id: str) -> None:
        calls.append(game_id)
        raise ValueError("unparseable")

    assert find_random_game(
        lambda candidate: True, pick_game_id=lambda: 9, load_game=load
    ) == ("", None)
    assert len(calls) == RANDOM_GAME_MAX_ATTEMPTS


def test_find_random_game_stops_once_cancelled() -> None:
    """A cancelled search stops before its next try."""
    calls = []

    def load(game_id: str) -> None:
        calls.append(game_id)

    assert find_random_game(
        lambda candidate: True,
        is_cancelled=lambda: len(calls) >= 2,
        pick_game_id=lambda: 5,
        load_game=load,
    ) == ("", None)
    assert calls == ["5", "5"]


def test_source_daily_double_counts_follow_source_round_positions() -> None:
    """Each round keeps its source position's count, whatever else is picked."""
    game = GameData(
        [
            _board_with_daily_doubles({(0, 0)}),
            _board_with_daily_doubles({(0, 0)}),
            FinalBoard("Final", Question((0, 0), "Q", "A", "Final")),
        ],
        "date",
        "comments",
    )

    assert game.source_daily_double_counts([0, 1, 2]) == [1, 2]
    assert game.source_daily_double_counts([1, 2]) == [2]
    assert game.source_daily_double_counts([2, 5]) == []
