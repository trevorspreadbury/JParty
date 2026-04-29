"""Compatibility exports for game-loading service functions.

This module provides a stable import surface for the application's game loading
helpers. The actual implementations live in ``archive_client``, but re-exporting
them here keeps service-oriented imports organized and backwards compatible.
"""

import random
from collections import defaultdict

from jparty.domain.models import FinalBoard, GameData, Question

from .archive_client import (
    find_question_media,
    get_game,
    get_game_html,
    get_Gsheet_game,
    get_jarchive_game_html,
    get_random_game,
    get_wayback_game_html,
    list_to_game,
    process_game_board_from_html,
    save_game_html,
)

DEFAULT_ADVANCED_BASE_VALUE = 200
FOUR_PLUS_STANDARD_BOARD_BASE_VALUE = 100
STANDARD_CLUE_VALUE_COUNT = 5
MAX_DAILY_DOUBLES_PER_BOARD = 6
ROW_ONE_TOTAL_WEIGHT = 0.12
ROW_TWO_TOTAL_WEIGHT = 9.0
ROW_THREE_AND_FIVE_TOTAL_WEIGHT = 54.0
ROW_FOUR_TOTAL_WEIGHT = (
    100.0
    - ROW_ONE_TOTAL_WEIGHT
    - ROW_TWO_TOTAL_WEIGHT
    - ROW_THREE_AND_FIVE_TOTAL_WEIGHT
)
DAILY_DOUBLE_ROW_TOTAL_WEIGHTS = {
    0: ROW_ONE_TOTAL_WEIGHT,
    1: ROW_TWO_TOTAL_WEIGHT,
    2: ROW_THREE_AND_FIVE_TOTAL_WEIGHT / 2,
    3: ROW_FOUR_TOTAL_WEIGHT,
    4: ROW_THREE_AND_FIVE_TOTAL_WEIGHT / 2,
}


def clone_question(question: object) -> Question:
    """Return a detached copy of one question without recursive parser state."""
    return Question(
        index=question.index,
        text=question.text,
        answer=question.answer,
        category=question.category,
        value=question.value,
        dd=question.dd,
        complete=question.complete,
        image=question.image,
        image_url=question.image_url,
        actual_results=question.actual_results,
    )


def clone_round(round_data: object) -> object:
    """Return a detached board/final-board copy safe for composition."""
    if isinstance(round_data, FinalBoard):
        cloned_question = clone_question(round_data.question)
        return FinalBoard(round_data.category, cloned_question)
    return type(round_data)(
        list(round_data.categories),
        [clone_question(question) for question in round_data.questions],
        dj=round_data.dj,
    )


def round_matches_board_type(round_data: object, board_type: object) -> bool:
    """Return whether one source round matches the requested selection type."""
    if board_type == "final":
        return isinstance(round_data, FinalBoard)
    if board_type == "standard":
        return not isinstance(round_data, FinalBoard)
    return True


def default_board_row_values(
    standard_board_position: int, standard_board_count: int
) -> list[int]:
    """Return default clue values for one standard board slot.

    Args:
        standard_board_position: Zero-based position among standard boards.
        standard_board_count: Total number of standard boards in the game.

    Returns:
        A five-value list matching the board's default clue ladder.
    """
    BOARDS = 4
    base_value = (
        FOUR_PLUS_STANDARD_BOARD_BASE_VALUE
        if standard_board_count >= BOARDS
        else DEFAULT_ADVANCED_BASE_VALUE
    )
    board_multiplier = standard_board_position + 1
    return [
        base_value * board_multiplier * (row_index + 1)
        for row_index in range(STANDARD_CLUE_VALUE_COUNT)
    ]


def _question_sort_key(question: object) -> tuple[int, int]:
    """Return a stable sort key for a clue."""
    return (int(question.index[0]), int(question.index[1]))


def _question_index_list(question: object) -> list[int]:
    """Return one clue coordinate as a JSON-friendly list."""
    return [int(question.index[0]), int(question.index[1])]


def standard_board_daily_double_indices(round_data: object) -> list[list[int]]:
    """Return sorted Daily Double coordinates for one standard board."""
    return [
        _question_index_list(question)
        for question in sorted(
            (
                question
                for question in getattr(round_data, "questions", [])
                if question.dd
            ),
            key=_question_sort_key,
        )
    ]


def _weighted_daily_double_candidates(
    questions: list[Question], occupied_categories: set[str]
) -> tuple[list[Question], list[float]]:
    """Return weighted promotion candidates that respect category limits."""
    row_question_counts = defaultdict(int)
    for question in questions:
        if question.dd:
            continue
        row_question_counts[int(question.index[1])] += 1
    candidates = []
    weights = []
    for question in sorted(questions, key=_question_sort_key):
        if question.dd or question.category in occupied_categories:
            continue
        row_index = int(question.index[1])
        row_question_count = row_question_counts.get(row_index, 0)
        total_row_weight = DAILY_DOUBLE_ROW_TOTAL_WEIGHTS.get(row_index, 0.0)
        if row_question_count <= 0 or total_row_weight <= 0:
            continue
        candidates.append(question)
        weights.append(total_row_weight / row_question_count)
    return candidates, weights


def _pick_weighted_question(
    candidates: list[Question], weights: list[float], rng: random.Random
) -> Question | None:
    """Return one weighted random clue from the candidate pool."""
    if not candidates:
        return None
    total_weight = sum(weights)
    if total_weight <= 0:
        return rng.choice(candidates)
    threshold = rng.random() * total_weight
    running_total = 0.0
    for candidate, weight in zip(candidates, weights, strict=False):
        running_total += weight
        if threshold <= running_total:
            return candidate
    return candidates[-1]


def normalize_standard_board_daily_doubles(
    round_data: object,
    requested_count: object = None,
    daily_double_indices: object = None,
    rng: random.Random | None = None,
) -> object:
    """Apply a valid Daily Double layout to one standard board clone."""
    if isinstance(round_data, FinalBoard):
        return round_data
    rng = rng or random.Random()
    questions = sorted(getattr(round_data, "questions", []), key=_question_sort_key)
    if not questions:
        return round_data

    original_daily_double_indices = {
        tuple(_question_index_list(question)) for question in questions if question.dd
    }
    questions_by_index = {
        (int(question.index[0]), int(question.index[1])): question
        for question in questions
    }
    category_questions: dict[str, list[Question]] = defaultdict(list)
    for question in questions:
        category_questions[str(question.category)].append(question)

    max_possible = min(MAX_DAILY_DOUBLES_PER_BOARD, len(category_questions))
    if requested_count is None:
        requested_total = len(original_daily_double_indices)
    else:
        requested_total = max(0, min(int(requested_count), max_possible))

    for question in questions:
        question.dd = False

    chosen_questions = []
    occupied_categories: set[str] = set()
    if daily_double_indices:
        for raw_index in daily_double_indices:
            if not isinstance(raw_index, list | tuple) or len(raw_index) != 2:
                continue
            normalized_index = (int(raw_index[0]), int(raw_index[1]))
            question = questions_by_index.get(normalized_index)
            if question is None or question.category in occupied_categories:
                continue
            chosen_questions.append(question)
            occupied_categories.add(question.category)
            if len(chosen_questions) >= requested_total:
                break
    else:
        existing_dd_by_category: dict[str, list[Question]] = defaultdict(list)
        for question in questions:
            if tuple(_question_index_list(question)) in original_daily_double_indices:
                existing_dd_by_category[question.category].append(question)
        for existing_questions in existing_dd_by_category.values():
            chosen_question = rng.choice(existing_questions)
            chosen_questions.append(chosen_question)
            occupied_categories.add(chosen_question.category)
        if len(chosen_questions) > requested_total:
            rng.shuffle(chosen_questions)
            chosen_questions = chosen_questions[:requested_total]
            occupied_categories = {question.category for question in chosen_questions}

    while len(chosen_questions) < requested_total:
        candidates, weights = _weighted_daily_double_candidates(
            questions, occupied_categories
        )
        chosen_question = _pick_weighted_question(candidates, weights, rng)
        if chosen_question is None:
            break
        chosen_questions.append(chosen_question)
        occupied_categories.add(chosen_question.category)
        chosen_question.dd = True

    for question in chosen_questions:
        question.dd = True
    return round_data


def build_game_from_board_selection_configs(board_selections: object) -> object:
    """Build a composite ``GameData`` from saved or advanced board selections.

    Args:
        board_selections: Iterable of dictionaries describing source game ids,
            source round indices, and optional row-value overrides.

    Returns:
        A composed ``GameData`` when every requested board can be loaded;
        otherwise ``None``.
    """
    if not board_selections:
        return None

    resolved_boards = []
    game_cache = {}
    for selection in board_selections:
        game_id = str(selection.get("game_id", "")).strip()
        if not game_id:
            return None
        if game_id not in game_cache:
            game_cache[game_id] = get_game(game_id)
        game_data = game_cache[game_id]
        if game_data is None:
            return None
        try:
            source_round_index = int(selection.get("source_round_index", 0))
        except (TypeError, ValueError):
            return None
        if not 0 <= source_round_index < len(game_data.rounds):
            return None
        source_round = game_data.rounds[source_round_index]
        if not round_matches_board_type(source_round, selection.get("board_type")):
            return None
        resolved_boards.append((selection, game_data, source_round))

    standard_board_count = sum(
        1
        for (_, _, round_data) in resolved_boards
        if not isinstance(round_data, FinalBoard)
    )
    standard_board_position = 0
    composed_rounds = []
    source_descriptions = []
    composite_dates = []
    for selection, game_data, source_round in resolved_boards:
        composite_dates.append(str(game_data.date))
        source_round_copy = clone_round(source_round)
        source_round_index = int(selection.get("source_round_index", 0))
        source_label = str(
            selection.get("source_round_label", f"Round {source_round_index + 1}")
        )
        source_descriptions.append(f"{selection.get('game_id')}: {source_label}")
        if isinstance(source_round_copy, FinalBoard):
            composed_rounds.append(source_round_copy)
            continue

        row_values = selection.get("row_values")
        if (
            not isinstance(row_values, list)
            or len(row_values) != STANDARD_CLUE_VALUE_COUNT
        ):
            row_values = default_board_row_values(
                standard_board_position, standard_board_count
            )
        else:
            row_values = [int(value) for value in row_values]
        for question in source_round_copy.questions:
            try:
                row_index = int(question.index[1])
            except (TypeError, ValueError, IndexError):
                continue
            if 0 <= row_index < len(row_values):
                question.value = row_values[row_index]
        normalize_standard_board_daily_doubles(
            source_round_copy,
            requested_count=selection.get("daily_double_count"),
            daily_double_indices=selection.get("daily_double_indices"),
        )
        source_round_copy.dj = standard_board_position > 0
        composed_rounds.append(source_round_copy)
        standard_board_position += 1

    composite_date = (
        composite_dates[0] if len(set(composite_dates)) == 1 else "Mixed-source game"
    )
    composite_comments = " / ".join(source_descriptions)
    return GameData(composed_rounds, composite_date, composite_comments)


__all__ = [
    "build_game_from_board_selection_configs",
    "default_board_row_values",
    "find_question_media",
    "get_Gsheet_game",
    "get_game",
    "get_game_html",
    "get_jarchive_game_html",
    "get_random_game",
    "save_game_html",
    "get_wayback_game_html",
    "list_to_game",
    "normalize_standard_board_daily_doubles",
    "process_game_board_from_html",
    "standard_board_daily_double_indices",
]
