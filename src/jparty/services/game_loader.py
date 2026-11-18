"""Compatibility exports for game-loading service functions.

This module provides a stable import surface for the application's game loading
helpers. The actual implementations live in ``archive_client``, but re-exporting
them here keeps service-oriented imports organized and backwards compatible.
"""

import logging
import random
from collections import defaultdict
from collections.abc import Callable

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
QUESTION_INDEX_PART_COUNT = 2
# Labels for a game's standard rounds, in order. Saved in each board
# selection's ``source_round_label``.
STANDARD_ROUND_LABELS = [
    "Jeopardy!",
    "Double Jeopardy!",
    "Triple Jeopardy!",
]
FINAL_ROUND_LABEL = "Final Jeopardy!"
# Most games Random tries before giving up, so a run of games that won't
# parse can't keep hitting J-Archive and the Wayback Machine (#88).
RANDOM_GAME_MAX_ATTEMPTS = 10
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


def original_board_row_values(game_data: object, round_index: int) -> list[int]:
    """Return the per-row clue values of one round in an original game.

    Each row takes the value of the first clue found in that row, so a clue
    missing from one category does not shift values in the others. Daily
    Doubles are skipped: J-Archive shows their wager instead of their board
    value, so the parser gives them a fallback from the modern value table,
    which is wrong for games before the 2001 value change. Rows with no other
    clues fall back to the default ladder for the round's position among the
    game's standard boards.

    Args:
        game_data: Parsed source game containing the round.
        round_index: Index of the round within ``game_data.rounds``.

    Returns:
        A five-value list for a standard board, or ``[]`` for a Final board.
    """
    round_data = game_data.rounds[round_index]
    if isinstance(round_data, FinalBoard):
        return []
    standard_round_indices = [
        index
        for index, candidate in enumerate(game_data.rounds)
        if not isinstance(candidate, FinalBoard)
    ]
    row_values = default_board_row_values(
        standard_round_indices.index(round_index), len(standard_round_indices)
    )
    found_rows = set()
    for question in sorted(round_data.questions, key=_question_sort_key):
        if question.dd:
            continue
        row_index = question.index[1]
        if 0 <= row_index < STANDARD_CLUE_VALUE_COUNT and row_index not in found_rows:
            row_values[row_index] = question.value
            found_rows.add(row_index)
    return row_values


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
    rng = rng or random.Random()  # noqa: S311
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
    chosen_indices: set[tuple[int, int]] = set()
    occupied_categories: set[str] = set()
    if daily_double_indices:
        for raw_index in daily_double_indices:
            if not isinstance(raw_index, list | tuple) or (
                len(raw_index) != QUESTION_INDEX_PART_COUNT
            ):
                continue
            normalized_index = (int(raw_index[0]), int(raw_index[1]))
            question = questions_by_index.get(normalized_index)
            if question is None or normalized_index in chosen_indices:
                continue
            # The board's own Daily Doubles are kept even when two share a
            # category, so a board plays (and resumes) as it was written.
            # Only extras have to be in a category of their own.
            if (
                question.category in occupied_categories
                and normalized_index not in original_daily_double_indices
            ):
                continue
            chosen_questions.append(question)
            chosen_indices.add(normalized_index)
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


def select_advanced_daily_double_indices(
    round_data: object,
    requested_count: object,
    existing_daily_double_indices: object = None,
    rng: random.Random | None = None,
) -> list[list[int]]:
    """Return the Daily Double coordinates to keep for one advanced board.

    The source board's original Daily Doubles are the baseline. Asking for
    more keeps every original and adds the extras already chosen in
    ``existing_daily_double_indices`` (``normalize_standard_board_daily_doubles``
    draws any still missing). Asking for fewer keeps only a subset of the
    originals: the existing subset when it has the right size, otherwise a
    random one.

    Args:
        round_data: Source standard board.
        requested_count: Number of Daily Doubles the host asked for.
        existing_daily_double_indices: Coordinates chosen earlier for this
            board, kept when still valid so the layout stays stable.
        rng: Random source used to pick a subset of the originals.

    Returns:
        Daily Double coordinates as ``[column, row]`` lists.
    """
    rng = rng or random.SystemRandom()
    original_daily_double_indices = standard_board_daily_double_indices(round_data)
    requested_total = max(0, int(requested_count))
    original_index_set = {tuple(index) for index in original_daily_double_indices}
    existing_indices = [
        list(index)
        for index in (existing_daily_double_indices or [])
        if isinstance(index, list | tuple) and len(index) == QUESTION_INDEX_PART_COUNT
    ]
    if requested_total <= len(original_daily_double_indices):
        if requested_total == len(original_daily_double_indices):
            return original_daily_double_indices
        existing_original_subset = []
        seen_indices = set()
        for index in existing_indices:
            normalized_index = tuple(index)
            if (
                normalized_index in original_index_set
                and normalized_index not in seen_indices
            ):
                existing_original_subset.append(list(index))
                seen_indices.add(normalized_index)
        if len(existing_original_subset) == requested_total:
            return existing_original_subset
        return [
            list(index)
            for index in rng.sample(original_daily_double_indices, requested_total)
        ]

    extra_slots = requested_total - len(original_daily_double_indices)
    current_extra_indices = []
    seen_extra_indices = set()
    for index in existing_indices:
        normalized_index = tuple(index)
        if (
            normalized_index not in original_index_set
            and normalized_index not in seen_extra_indices
        ):
            current_extra_indices.append(list(index))
            seen_extra_indices.add(normalized_index)
    return original_daily_double_indices + current_extra_indices[:extra_slots]


def describe_source_round(game_data: object, round_index: int) -> str:
    """Return the label for one round of a source game.

    This is the label the welcome screen shows and each board selection
    saves as ``source_round_label``.

    Args:
        game_data: Source game containing the round.
        round_index: Index of the round within ``game_data.rounds``.

    Returns:
        ``"Final Jeopardy!"`` for a Final, otherwise the standard round's
        label by its place among the game's standard rounds.
    """
    if isinstance(game_data.rounds[round_index], FinalBoard):
        return FINAL_ROUND_LABEL
    standard_round_index = sum(
        1
        for prior_round in game_data.rounds[:round_index]
        if not isinstance(prior_round, FinalBoard)
    )
    if standard_round_index < len(STANDARD_ROUND_LABELS):
        return STANDARD_ROUND_LABELS[standard_round_index]
    return f"Round {standard_round_index + 1}"


# One board in play, as saved in ``general.json``'s ``board_selections`` and
# read back by ``build_game_from_board_selection_configs``. The two builders
# below are the only places that write these dictionaries; see
# docs/game-logging.md for the format.


def standard_board_selection(
    game_id: str,
    source_round_index: int,
    source_round_label: str,
    row_values: list[int],
    daily_double_indices: list[list[int]],
) -> dict:
    """Return the saved form of one standard board.

    Args:
        game_id: Source game the board comes from.
        source_round_index: The round's index in the source game.
        source_round_label: Label of that round, shown on the welcome screen.
        row_values: The five clue values, top row first.
        daily_double_indices: Daily Double coordinates as
            ``[category_index, row_index]`` pairs.

    Returns:
        A ``board_selections`` entry.
    """
    daily_double_indices = [
        [int(index[0]), int(index[1])] for index in daily_double_indices
    ]
    return {
        "game_id": game_id,
        "source_round_index": int(source_round_index),
        "source_round_label": source_round_label,
        "board_type": "standard",
        "row_values": list(row_values),
        "daily_double_count": len(daily_double_indices),
        "daily_double_indices": daily_double_indices,
    }


def final_board_selection(
    game_id: str, source_round_index: int, source_round_label: str
) -> dict:
    """Return the saved form of one Final Jeopardy board.

    Args:
        game_id: Source game the board comes from.
        source_round_index: The round's index in the source game.
        source_round_label: Label of that round, shown on the welcome screen.

    Returns:
        A ``board_selections`` entry. Finals have no clue values, so
        ``row_values`` is ``[]``.
    """
    return {
        "game_id": game_id,
        "source_round_index": int(source_round_index),
        "source_round_label": source_round_label,
        "board_type": "final",
        "row_values": [],
    }


def advanced_standard_board_selection(
    game_id: str,
    round_data: object,
    source_round_index: int,
    source_round_label: str,
    row_values: list[int],
    requested_daily_double_count: int,
    existing_daily_double_indices: object = None,
) -> dict:
    """Return the saved form of one advanced-mode standard board.

    The board keeps its original Daily Doubles as a baseline (see
    ``select_advanced_daily_double_indices``), and any extras still missing
    are drawn here, so the saved coordinates are the final layout.

    Args:
        game_id: Source game the board comes from.
        round_data: The source round. It is not changed.
        source_round_index: The round's index in the source game.
        source_round_label: Label of that round.
        row_values: The five clue values, top row first.
        requested_daily_double_count: Daily Doubles the host asked for.
        existing_daily_double_indices: Coordinates chosen earlier for this
            board, kept when still valid so the layout stays stable.

    Returns:
        A ``board_selections`` entry.
    """
    baseline_daily_double_indices = select_advanced_daily_double_indices(
        round_data,
        requested_daily_double_count,
        existing_daily_double_indices=existing_daily_double_indices,
    )
    round_copy = clone_round(round_data)
    normalize_standard_board_daily_doubles(
        round_copy,
        requested_count=requested_daily_double_count,
        daily_double_indices=baseline_daily_double_indices,
    )
    return standard_board_selection(
        game_id,
        source_round_index,
        source_round_label,
        row_values,
        standard_board_daily_double_indices(round_copy),
    )


def original_board_selection(game_id: str, game_data: object, round_index: int) -> dict:
    """Return the saved form of one round played as it is in its source game.

    Regular mode uses this: the round keeps its clue values and Daily
    Doubles from the source game.

    Args:
        game_id: Source game id.
        game_data: Parsed source game.
        round_index: Index of the round within ``game_data.rounds``.

    Returns:
        A ``board_selections`` entry.
    """
    round_data = game_data.rounds[round_index]
    label = describe_source_round(game_data, round_index)
    if isinstance(round_data, FinalBoard):
        return final_board_selection(game_id, round_index, label)
    return standard_board_selection(
        game_id,
        round_index,
        label,
        original_board_row_values(game_data, round_index),
        standard_board_daily_double_indices(round_data),
    )


def compose_game_from_resolved_board_selections(
    resolved_boards: list[tuple[dict, GameData, object]],
) -> GameData | None:
    """Build a composite game from already-resolved source boards."""
    if not resolved_boards:
        return None
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

    return compose_game_from_resolved_board_selections(resolved_boards)


def find_random_game(
    accept: Callable[[object], bool],
    max_attempts: int = RANDOM_GAME_MAX_ATTEMPTS,
    is_cancelled: Callable[[], bool] = lambda: False,
    pick_game_id: Callable[[], object] | None = None,
    load_game: Callable[[object], object] | None = None,
) -> tuple[str, object]:
    """Try random J-Archive games until one is accepted.

    Both Random buttons on the welcome screen use this. A failed fetch or
    parse only costs that one try, so a network blip doesn't end the search,
    and the search stops after ``max_attempts`` tries so a run of bad games
    can't keep hitting the network.

    Args:
        accept: Returns whether a loaded game can be used. It is only called
            with data that is not ``None``.
        max_attempts: Most games to try.
        is_cancelled: Checked before each try; once it returns ``True`` the
            search stops.
        pick_game_id: Returns a random game id. Defaults to
            ``get_random_game``.
        load_game: Loads one game id. Defaults to ``get_game``.

    Returns:
        ``(game_id, data)`` for the first accepted game, or ``("", None)``
        when every try failed or the search was cancelled.
    """
    pick_game_id = pick_game_id or get_random_game
    load_game = load_game or get_game
    for _ in range(max_attempts):
        if is_cancelled():
            break
        try:
            game_id = str(pick_game_id())
            logging.info(f"GAMEID {game_id}")
            data = load_game(game_id)
        except Exception as exc:
            logging.error(exc)
            continue
        if data is not None and accept(data):
            return game_id, data
    return "", None


def tiebreaker_clues(
    game_data: object, rng: random.Random | None = None
) -> list[Question]:
    """Return a game's clues in the order a tiebreaker asks them (#44).

    The highest-value clues come first. Clues of equal value are shuffled,
    so the tiebreaker asks a random top-value clue and only falls back to a
    lower value once every higher one has been used. Final Jeopardy, blank
    clues, and clues that need an image are left out. The returned clues are
    copies with the Daily Double flag cleared, so the source game is not
    changed.

    Args:
        game_data: Loaded game to take clues from. ``None`` gives no clues.
        rng: Random source for the shuffle. Defaults to a new
            ``random.Random``.

    Returns:
        The tiebreaker clues, highest value first.
    """
    rng = rng or random.Random()  # noqa: S311
    clues_by_value = defaultdict(list)
    for round_data in getattr(game_data, "rounds", None) or []:
        if isinstance(round_data, FinalBoard):
            continue
        for question in round_data.questions:
            if not str(question.text or "").strip() or question.image:
                continue
            if not isinstance(question.value, int) or question.value <= 0:
                continue
            clue = clone_question(question)
            clue.dd = False
            clue.complete = False
            clues_by_value[clue.value].append(clue)
    ordered = []
    for value in sorted(clues_by_value, reverse=True):
        clues = clues_by_value[value]
        rng.shuffle(clues)
        ordered.extend(clues)
    return ordered


def load_tiebreaker_clues(
    game_id: object,
    load_game: Callable[[object], object] | None = None,
    find_game: Callable[..., tuple[str, object]] | None = None,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> tuple[str, list[Question]]:
    """Load the clues for a tiebreaker from one game, or a random game.

    This reaches the network, so call it off the UI thread.

    Args:
        game_id: Game id the host entered. Blank picks a random game.
        load_game: Loads one game id. Defaults to ``get_game``.
        find_game: Finds a random game. Defaults to ``find_random_game``.
        is_cancelled: Checked before each random game is tried, so a search
            the host no longer needs (for example after Close Game) stops
            fetching from J-Archive.

    Returns:
        ``(game_id, clues)`` with the game actually used and its clues in
        tiebreaker order. ``clues`` is empty when the game could not be
        loaded or has no usable clue.
    """
    load_game = load_game or get_game
    find_game = find_game or find_random_game
    game_id = str(game_id or "").strip()
    if game_id:
        game_data = load_game(game_id)
    else:
        game_id, game_data = find_game(
            lambda data: bool(tiebreaker_clues(data)), is_cancelled=is_cancelled
        )
    return game_id, tiebreaker_clues(game_data)


__all__ = [
    "STANDARD_ROUND_LABELS",
    "advanced_standard_board_selection",
    "build_game_from_board_selection_configs",
    "compose_game_from_resolved_board_selections",
    "default_board_row_values",
    "describe_source_round",
    "final_board_selection",
    "original_board_row_values",
    "original_board_selection",
    "standard_board_selection",
    "find_question_media",
    "find_random_game",
    "get_Gsheet_game",
    "get_game",
    "get_game_html",
    "get_jarchive_game_html",
    "get_random_game",
    "load_tiebreaker_clues",
    "save_game_html",
    "get_wayback_game_html",
    "list_to_game",
    "normalize_standard_board_daily_doubles",
    "process_game_board_from_html",
    "round_matches_board_type",
    "select_advanced_daily_double_indices",
    "standard_board_daily_double_indices",
    "tiebreaker_clues",
]
