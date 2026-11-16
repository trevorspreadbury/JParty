"""Unit tests for board composition and parsing helpers."""

import random

import pytest
from bs4 import BeautifulSoup

from jparty.domain.models import Board, FinalBoard, GameData, Question
from jparty.services.game_loader import (
    RANDOM_GAME_MAX_ATTEMPTS,
    advanced_standard_board_selection,
    build_game_from_board_selection_configs,
    describe_source_round,
    final_board_selection,
    find_random_game,
    load_tiebreaker_clues,
    normalize_standard_board_daily_doubles,
    original_board_row_values,
    original_board_selection,
    round_matches_board_type,
    select_advanced_daily_double_indices,
    standard_board_daily_double_indices,
    standard_board_selection,
    tiebreaker_clues,
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


# The ``board_selections`` example in docs/game-logging.md. Saves already on
# disk use exactly these keys, so the builders must keep producing them.
DOCUMENTED_BOARD_SELECTIONS = [
    {
        "game_id": "4453",
        "source_round_index": 1,
        "source_round_label": "Double Jeopardy!",
        "board_type": "standard",
        "row_values": [400, 800, 1200, 1600, 2000],
        "daily_double_count": 2,
        "daily_double_indices": [[1, 3], [4, 2]],
    },
    {
        "game_id": "4453",
        "source_round_index": 2,
        "source_round_label": "Final Jeopardy!",
        "board_type": "final",
        "row_values": [],
    },
]


def _documented_source_game() -> GameData:
    """Return a game shaped like the one the documented selections describe."""
    double_jeopardy = _board_with_daily_doubles({(1, 3), (4, 2)})
    for question in double_jeopardy.questions:
        question.value = 400 * (question.index[1] + 1)
    return GameData(
        [
            _board_with_daily_doubles({(0, 0)}),
            double_jeopardy,
            FinalBoard("Final", Question((0, 0), "FQ", "FA", "Final")),
        ],
        "January 1, 2026",
        "Fixture",
    )


def test_board_selection_builders_match_the_documented_format() -> None:
    """The builders write exactly the documented ``board_selections`` entries."""
    assert [
        standard_board_selection(
            "4453",
            1,
            "Double Jeopardy!",
            [400, 800, 1200, 1600, 2000],
            [[1, 3], [4, 2]],
        ),
        final_board_selection("4453", 2, "Final Jeopardy!"),
    ] == DOCUMENTED_BOARD_SELECTIONS
    source = _documented_source_game()
    assert [
        original_board_selection("4453", source, 1),
        original_board_selection("4453", source, 2),
    ] == DOCUMENTED_BOARD_SELECTIONS


def test_documented_board_selections_rebuild_the_saved_game(
    monkeypatch: object,
) -> None:
    """A save written in the documented format still loads (round trip)."""
    source = _documented_source_game()
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"4453": source}[game_id],
    )

    composed = build_game_from_board_selection_configs(DOCUMENTED_BOARD_SELECTIONS)

    assert composed is not None
    assert [
        original_board_selection("4453", source, 1)["daily_double_indices"],
        standard_board_daily_double_indices(composed.rounds[0]),
    ] == [[[1, 3], [4, 2]]] * 2
    assert [question.value for question in composed.rounds[0].questions[:5]] == [
        400,
        800,
        1200,
        1600,
        2000,
    ]
    assert isinstance(composed.rounds[1], FinalBoard)
    assert composed.comments == "4453: Double Jeopardy! / 4453: Final Jeopardy!"


def test_describe_source_round_labels_rounds_by_position() -> None:
    """Rounds are labelled by their place among the standard rounds."""
    game = GameData(
        [_board_with_daily_doubles(set()) for _ in range(4)]
        + [FinalBoard("Final", Question((0, 0), "FQ", "FA", "Final"))],
        "date",
        "comments",
    )

    assert [describe_source_round(game, index) for index in range(5)] == [
        "Jeopardy!",
        "Double Jeopardy!",
        "Triple Jeopardy!",
        "Round 4",
        "Final Jeopardy!",
    ]


def test_board_sharing_a_daily_double_category_keeps_its_layout(
    monkeypatch: object,
) -> None:
    """Two original Daily Doubles in one category survive selection and resume.

    One of them used to be dropped and a random clue elsewhere drawn instead,
    so each sync, and each resume, could move it.
    """
    board = _board_with_daily_doubles({(2, 1), (2, 3)})
    source = GameData([board], "date", "comments")
    monkeypatch.setattr("jparty.services.game_loader.get_game", lambda game_id: source)

    selection = original_board_selection("111", source, 0)
    composed = build_game_from_board_selection_configs([selection])

    assert selection["daily_double_indices"] == [[2, 1], [2, 3]]
    assert standard_board_daily_double_indices(composed.rounds[0]) == [
        [2, 1],
        [2, 3],
    ]


def test_advanced_board_selection_adds_extras_without_moving_originals() -> None:
    """An advanced board keeps its originals and adds extras in new categories."""
    board = _board_with_daily_doubles({(1, 2)})

    selection = advanced_standard_board_selection(
        "111", board, 0, "Jeopardy!", [100, 200, 300, 400, 500], 3
    )

    assert selection["daily_double_count"] == 3
    assert [1, 2] in selection["daily_double_indices"]
    assert len({index[0] for index in selection["daily_double_indices"]}) == 3
    assert [question.index for question in board.questions if question.dd] == [(1, 2)]


def _tiebreaker_source_game() -> GameData:
    """Return a two-round game with a Final, a blank clue, and an image clue."""
    rounds = []
    for multiplier in (1, 2):
        questions = [
            Question(
                index=(col, row),
                text=f"Clue {multiplier}-{col}-{row}",
                answer=f"Answer {multiplier}-{col}-{row}",
                category=f"Cat {col}",
                value=(row + 1) * 200 * multiplier,
            )
            for col in range(6)
            for row in range(5)
        ]
        rounds.append(Board([f"Cat {col}" for col in range(6)], questions))
    top_row = [q for q in rounds[1].questions if q.value == 2000]
    top_row[0].dd = True
    top_row[1].text = ""
    top_row[2].image = True
    rounds.append(
        FinalBoard("Final", Question((0, 0), "Final clue", "Final answer", "Final"))
    )
    return GameData(rounds, "January 1, 2026", "")


def test_tiebreaker_clues_ask_highest_values_first_in_random_order() -> None:
    """Top-value clues come first, shuffled, and skip unusable clues (#44)."""
    game_data = _tiebreaker_source_game()
    clues = tiebreaker_clues(game_data, rng=random.Random(1))  # noqa: S311

    values = [clue.value for clue in clues]
    assert values == sorted(values, reverse=True)
    # Of the six $2000 clues, the blank one and the image one are left out.
    assert values.count(2000) == 4
    assert "Final clue" not in {clue.text for clue in clues}
    assert not any(clue.dd for clue in clues)
    # The source game is untouched.
    assert any(q.dd for q in game_data.rounds[1].questions)
    orders = set()
    for seed in range(10):
        rng = random.Random(seed)  # noqa: S311
        top_clues = tiebreaker_clues(game_data, rng)[:4]
        orders.add(tuple(clue.index for clue in top_clues))
    assert len(orders) > 1


def test_tiebreaker_clues_of_missing_game_are_empty() -> None:
    """A game that failed to load gives no tiebreaker clues."""
    assert tiebreaker_clues(None) == []


def test_load_tiebreaker_clues_uses_entered_or_random_game() -> None:
    """An entered id loads that game; a blank id picks a random usable one."""
    game_data = _tiebreaker_source_game()
    loaded = []

    def load_game(game_id: str) -> GameData:
        loaded.append(game_id)
        return game_data

    game_id, clues = load_tiebreaker_clues(" 4453 ", load_game=load_game)
    assert (game_id, loaded) == ("4453", ["4453"])
    assert clues[0].value == 2000

    def is_cancelled() -> bool:
        return False

    def find_game(accept: object, is_cancelled: object) -> tuple:
        assert accept(game_data) is True
        assert accept(GameData([], "", "")) is False
        searches.append(is_cancelled)
        return "777", game_data

    searches = []
    game_id, clues = load_tiebreaker_clues(
        "", find_game=find_game, is_cancelled=is_cancelled
    )
    assert game_id == "777"
    assert clues
    # The cancel check reaches the random-game search, so Close Game can
    # stop it fetching more games.
    assert searches == [is_cancelled]
