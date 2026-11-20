"""Helpers for picking source games and describing them to the host.

The welcome screen's single-game setup and the advanced board editor (used
on the welcome screen and in the tournament board picker) share these, so
Random, warnings, and summaries behave and read the same everywhere. Nothing
here touches widgets, so the random-game search can run on a worker thread.
"""

from __future__ import annotations

from jparty.domain.models import GameData
from jparty.services.game_loader import (
    RANDOM_GAME_MAX_ATTEMPTS,
    find_random_game,
    get_game,
    get_random_game,
)
from jparty.services.question_media import detect_question_media

MISSING_DAILY_DOUBLE_WARNING = "CRITICAL: Missing Daily Double"
ADVANCED_RANDOM_MAX_ATTEMPTS = RANDOM_GAME_MAX_ATTEMPTS


def is_playable_game_data(data: object) -> bool:
    """Return whether loaded game data has at least one playable round."""
    return data is not None and bool(getattr(data, "rounds", None))


def find_random_game_with_media(
    accept: object, is_cancelled: object, max_attempts: int
) -> tuple[str, object, object]:
    """Find a random game and its local media status, on a worker thread.

    Both Random buttons use this. It never touches widgets.

    Args:
        accept: Returns whether a loaded game can be used.
        is_cancelled: Returns ``True`` once a newer request replaced this one.
        max_attempts: Most games to try.

    Returns:
        ``(game_id, data, media_status)``, or ``("", None, None)`` when every
        try failed or the search was cancelled.
    """
    game_id, data = find_random_game(
        accept,
        max_attempts=max_attempts,
        is_cancelled=is_cancelled,
        pick_game_id=get_random_game,
        load_game=get_game,
    )
    media_status = detect_question_media(game_id) if game_id else None
    return game_id, data, media_status


def random_game_failure_text(wanted: str, max_attempts: int) -> str:
    """Return the message shown when Random found no usable game.

    Args:
        wanted: What the game had to have, such as ``"playable random game"``.
        max_attempts: How many games were tried.

    Returns:
        The message.
    """
    return f"Could not find a {wanted} after {max_attempts} tries. Try again."


def game_warning_lines(
    data: object, expected_daily_double_counts: list[int] | None = None
) -> list[str]:
    """Return the missing-clue warnings for a game shown to the host.

    The regular summary, each advanced row and the advanced summary all use
    this, so the warnings read the same everywhere.

    Args:
        data: Game, or rounds of one, to check.
        expected_daily_double_counts: Daily Doubles each standard round should
            have, or ``None`` for the regular-game rule.

    Returns:
        Zero or more warning lines.
    """
    lines = []
    missing_question_count = getattr(data, "missing_question_count", lambda: 0)()
    if missing_question_count:
        lines.append(
            f"WARNING: Missing {missing_question_count} question"
            f"{'' if missing_question_count == 1 else 's'}"
        )
    if getattr(data, "has_missing_daily_double", lambda *_: False)(
        expected_daily_double_counts
    ):
        lines.append(MISSING_DAILY_DOUBLE_WARNING)
    return lines


def source_game_summary_text(
    game_id: str,
    data: object,
    media_status: object,
    selected_round_index: int | None = None,
) -> str:
    """Return the summary shown under one advanced board row.

    Args:
        game_id: Source game id.
        data: The loaded source game.
        media_status: Its local question-media status, or ``None``.
        selected_round_index: The round picked for the row, if any; the
            warnings then cover just that round.

    Returns:
        The summary text.
    """
    summary_data = data
    if selected_round_index is not None and 0 <= selected_round_index < len(
        data.rounds
    ):
        summary_data = GameData(
            [data.rounds[selected_round_index]], data.date, data.comments
        )
    summary_lines = [f"{game_id}: {summary_data.date}", str(summary_data.comments)]
    expected_daily_doubles = None
    if summary_data is not data:
        # One round picked from the source: hold it to its own place there.
        expected_daily_doubles = data.source_daily_double_counts([selected_round_index])
    summary_lines.extend(game_warning_lines(summary_data, expected_daily_doubles))
    if media_status is not None:
        summary_lines.append(media_status.summary_text())
    return "\n".join(line for line in summary_lines if line)


def composed_board_summary_text(
    board_selections: list[dict],
    composed_data: object,
    requested_daily_double_counts: object = None,
) -> str:
    """Return the summary for a board composed from advanced rows.

    Args:
        board_selections: Board selections in play order.
        composed_data: Game composed from ``board_selections``.
        requested_daily_double_counts: Daily Double count the host asked
            for on each standard board, in order. The missing-Daily-Double
            warning compares against these instead of the regular-game rule.

    Returns:
        The summary text.
    """
    summary_lines = [composed_data.date, composed_data.comments, ""]
    standard_index = 0
    final_index = 0
    for selection in board_selections:
        values = ", ".join(str(value) for value in selection.get("row_values", []))
        if selection.get("board_type") == "final":
            final_index += 1
            board_label = f"Final {final_index}"
            suffix = ""
        else:
            standard_index += 1
            board_label = f"Board {standard_index}"
            suffix = (
                f", DDs: {selection.get('daily_double_count', 0)}"
                if selection.get("daily_double_count") is not None
                else ""
            )
        summary_lines.append(
            f"{board_label}: {selection.get('game_id')} - {selection.get('source_round_label')}"
            + (f" ({values}{suffix})" if values or suffix else "")
        )
    for warning in game_warning_lines(composed_data, requested_daily_double_counts):
        summary_lines.extend(["", warning])
    return "\n".join(str(line) for line in summary_lines if line is not None)


def composed_session_game_id(board_selections: list[dict]) -> str:
    """Return the save and log id for a set of board selections.

    Args:
        board_selections: Board selections in play order.

    Returns:
        The one source game's id, ``"frankenstein-<id>-<id>..."`` for a
        board from several games, or ``""`` when no selection names a game.
    """
    source_ids = [
        str(selection.get("game_id", "")).strip() for selection in board_selections
    ]
    source_ids = [game_id for game_id in source_ids if game_id]
    if not source_ids:
        return ""
    if len(set(source_ids)) == 1:
        return source_ids[0]
    return "frankenstein-" + "-".join(source_ids)
