"""Getting a set of boards ready before they are played.

:func:`prepare_boards` builds each board, which loads its source games from
the local cache or the network, and saves each J-Archive game to the local
cache so playing the board later doesn't need the network. It also finds
each board's questions with local question media, for a preview.

It can be slow, so call it off the UI thread.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from jparty.services.archive_client import GOOGLE_SHEETS_ID_LENGTH, save_game_html
from jparty.services.game_loader import build_game_from_board_selection_configs
from jparty.services.question_media import game_local_media_questions


@dataclass(frozen=True)
class PreparedBoard:
    """One board, built and ready to play, or why it couldn't be.

    Attributes:
        key: What the board is for, such as a tournament game's key.
        label: The board's description.
        data: The built game, or ``None`` if it couldn't be built.
        error: Why the board couldn't be built or cached, or ``""``.
        media: ``(round index, question)`` for each question with local
            question media.
    """

    key: str
    label: str
    data: object = None
    error: str = ""
    media: tuple[tuple[int, object], ...] = ()

    @property
    def ready(self) -> bool:
        """Return whether the board was built and its games cached."""
        return self.data is not None and not self.error


def _source_ids(selections: Sequence[Mapping]) -> list[str]:
    """Return the board's source game ids, once each, in order."""
    ids = []
    for selection in selections:
        game_id = str(selection.get("game_id", "")).strip()
        if game_id and game_id not in ids:
            ids.append(game_id)
    return ids


def prepare_board(
    key: str, label: str, selections: Sequence[Mapping], games: dict | None = None
) -> PreparedBoard:
    """Build one board and cache its J-Archive games.

    Args:
        key: What the board is for.
        label: The board's description.
        selections: The board's ``board_selections``.
        games: Source games already loaded, by id, shared between boards.

    Returns:
        The prepared board.
    """
    games = {} if games is None else games
    selections = [dict(selection) for selection in selections]
    try:
        data = build_game_from_board_selection_configs(selections, games)
    except Exception as exc:  # noqa: BLE001 - reported to the host
        logging.exception("Couldn't build the board for %s", key)
        return PreparedBoard(key, label, error=f"Couldn't load the board: {exc}")
    ids = _source_ids(selections)
    if data is None or not getattr(data, "rounds", None):
        missing = [game_id for game_id in ids if games.get(game_id) is None]
        detail = f" (couldn't load {', '.join(missing)})" if missing else ""
        return PreparedBoard(key, label, error=f"Couldn't load the board{detail}.")
    unsaved = []
    for game_id in ids:
        if len(game_id) >= GOOGLE_SHEETS_ID_LENGTH:
            # Google Sheets games aren't cached; they load from the sheet.
            continue
        try:
            save_game_html(game_id)
        except Exception:  # noqa: BLE001 - reported to the host
            logging.exception("Couldn't cache game %s", game_id)
            unsaved.append(game_id)
    error = f"Couldn't save {', '.join(unsaved)} to the cache." if unsaved else ""
    return PreparedBoard(
        key, label, data, error, tuple(game_local_media_questions(data))
    )


def prepare_boards(
    boards: Sequence[tuple[str, str, Sequence[Mapping]]],
    on_progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> list[PreparedBoard]:
    """Build every board and cache its J-Archive games.

    Each source game is loaded once, however many boards use it.

    Args:
        boards: ``(key, label, board_selections)`` for each board.
        on_progress: Called with ``(boards done, boards)`` after each board.
        is_cancelled: Polled before each board; stops early when it returns
            ``True``.

    Returns:
        The boards prepared, in order. Fewer than ``boards`` if cancelled.
    """
    games: dict = {}
    prepared = []
    for index, (key, label, selections) in enumerate(boards):
        if is_cancelled():
            break
        prepared.append(prepare_board(key, label, selections, games))
        if on_progress is not None:
            on_progress(index + 1, len(boards))
    return prepared
