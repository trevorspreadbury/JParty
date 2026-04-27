"""Compatibility exports for game-loading service functions.

This module provides a stable import surface for the application's game loading
helpers. The actual implementations live in ``archive_client``, but re-exporting
them here keeps service-oriented imports organized and backwards compatible.
"""

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
        resolved_boards.append(
            (selection, game_data, game_data.rounds[source_round_index])
        )

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
    "process_game_board_from_html",
]
