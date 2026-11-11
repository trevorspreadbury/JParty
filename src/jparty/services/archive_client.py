"""Compatibility exports for archived game loading helpers."""

from __future__ import annotations

import logging
import os

from bs4 import BeautifulSoup

from jparty.app.paths import QUESTION_MEDIA, SAVED_GAMES

from .game_cache import GameCache
from .game_parser import GameParser
from .game_sources import GameSourceFetcher

# Ids at least this long are Google Sheets file ids, not J-Archive game ids.
GOOGLE_SHEETS_ID_LENGTH = 7
# How many trailing characters to search for a closing ``</html>`` tag.
HTML_TAIL_CHECK_CHARS = 4096

_LOADED_GAME_HTML_CACHE: dict[str, str] = {}
_FETCHER = GameSourceFetcher()
_PARSER = GameParser()


def list_to_game(rows: object) -> object:
    """Convert sheet rows into ``GameData`` using the shared parser."""
    return _PARSER.list_to_game(rows)


def get_Gsheet_game(file_id: object) -> object:
    """Fetch and parse a Google Sheets-backed game."""
    return _PARSER.list_to_game(_FETCHER.get_google_sheet_rows(file_id))


def _cached_game_html(game_id: object) -> str | None:
    """Return cached HTML for ``game_id`` from disk, or ``None`` when absent."""
    return GameCache(SAVED_GAMES).load_saved_html(game_id)


def _fetch_remote_game_html(game_id: object) -> object:
    """Fetch game HTML from Wayback, falling back to J-Archive directly."""
    try:
        return get_wayback_game_html(game_id)
    except Exception:
        logging.error("Wayback lookup failed for %s", game_id, exc_info=True)
        return get_jarchive_game_html(game_id)


def _looks_complete(game_html: object) -> bool:
    """Return whether HTML ends with a closing ``</html>`` tag.

    A cache file cut off part way through can still parse into a game with
    missing rounds, so a missing closing tag is treated as a damaged copy.
    Archive pages may append a trailing comment, so only the tail is checked.
    """
    return "</html>" in str(game_html)[-HTML_TAIL_CHECK_CHARS:].lower()


def _parse_or_none(game_html: object, game_id: object) -> object:
    """Parse HTML into ``GameData``, returning ``None`` if parsing raises."""
    try:
        return process_game_board_from_html(game_html, game_id)
    except Exception:
        logging.warning("Could not parse HTML for game %s", game_id, exc_info=True)
        return None


def get_game_html(game_id: object) -> object:
    """Load archived game HTML from cache or remote fallback sources."""
    game_html = _cached_game_html(game_id)
    if game_html is None:
        game_html = _fetch_remote_game_html(game_id)
    _LOADED_GAME_HTML_CACHE[str(game_id)] = game_html
    return game_html


def save_game_html(game_id: object) -> object:
    """Persist a numeric J-Archive game HTML payload into the local cache.

    The file is written atomically, so a crash or exit mid-write never leaves
    a cut-off cache file behind.
    """
    game_id_str = str(game_id)
    if len(game_id_str) >= GOOGLE_SHEETS_ID_LENGTH:
        return None
    cache = GameCache(SAVED_GAMES)
    saved_game_path = cache.saved_html_path(game_id_str)
    if saved_game_path.exists():
        return saved_game_path
    game_html = _LOADED_GAME_HTML_CACHE.get(game_id_str)
    if game_html is None:
        game_html = get_game_html(game_id_str)
    return cache.save_html(game_id_str, game_html)


def _get_archive_game(game_id: object) -> object:
    """Load and parse an archived game, repairing a damaged cache copy.

    When the cached HTML is missing its closing tag or does not parse, the
    game is fetched from the network instead. If the network copy parses, it
    overwrites the damaged cache file so later loads use the good copy. If the
    network fetch fails, the cached parse result (possibly ``None``) is used.
    """
    game_id_str = str(game_id)
    cached_html = _cached_game_html(game_id_str)
    cached_data = None
    if cached_html is not None:
        cached_data = _parse_or_none(cached_html, game_id_str)
        if cached_data is not None and _looks_complete(cached_html):
            _LOADED_GAME_HTML_CACHE[game_id_str] = cached_html
            return cached_data
        logging.warning(
            "Cached HTML for game %s looks damaged; fetching it again", game_id_str
        )
        try:
            remote_html = _fetch_remote_game_html(game_id_str)
        except Exception:
            logging.error(
                "Could not refetch game %s; using cached copy",
                game_id_str,
                exc_info=True,
            )
            _LOADED_GAME_HTML_CACHE[game_id_str] = cached_html
            return cached_data
    else:
        remote_html = _fetch_remote_game_html(game_id_str)
    _LOADED_GAME_HTML_CACHE[game_id_str] = remote_html
    game_data = process_game_board_from_html(remote_html, game_id_str)
    if cached_html is not None and game_data is not None:
        try:
            GameCache(SAVED_GAMES).save_html(game_id_str, remote_html)
        except OSError:
            logging.error(
                "Could not overwrite damaged cache for game %s",
                game_id_str,
                exc_info=True,
            )
    return game_data


def get_game(game_id: object) -> object:
    """Load a game from either J-Archive-style HTML or Google Sheets."""
    os.environ["JPARTY_GAME_ID"] = str(game_id)
    if len(str(game_id)) < GOOGLE_SHEETS_ID_LENGTH:
        return _get_archive_game(game_id)
    return get_Gsheet_game(str(game_id))


def findanswer(clue: object) -> object:
    """Extract the correct response text from a clue HTML fragment."""
    return _PARSER.findanswer(clue)


def get_jarchive_game_html(game_id: object) -> object:
    """Fetch raw game HTML directly from J-Archive."""
    return _FETCHER.get_jarchive_game_html(game_id)


def find_question_media(game_id: int, round: int, index: tuple) -> str:
    """Locate downloaded media associated with a clue."""
    from jparty.services import question_media as question_media_service

    question_media_service.QUESTION_MEDIA = QUESTION_MEDIA
    return question_media_service.find_question_media_file(game_id, round, index)


def get_actual_player_results(clue: BeautifulSoup, value: int) -> object:
    """Extract contestant scoring outcomes for a standard clue."""
    return _PARSER.get_actual_player_results(clue, value)


def get_clue_value(clue: BeautifulSoup, round_index: int, row_index: int) -> int:
    """Extract a clue's value from HTML with a safe fallback."""
    return _PARSER.get_clue_value(clue, round_index, row_index)


def get_actual_player_final(clue: BeautifulSoup) -> list[list[str]]:
    """Extract contestant scoring outcomes for Final Jeopardy."""
    return _PARSER.get_actual_player_final(clue)


def process_game_board_from_html(html: object, game_id: object) -> object:
    """Parse archived game HTML into a playable ``GameData`` payload."""
    return _PARSER.process_game_board_from_html(html, game_id)


def get_wayback_game_html(game_id: object) -> object:
    """Fetch the latest Wayback Machine snapshot for a game page."""
    return _FETCHER.get_wayback_game_html(game_id)


def get_game_sum(soup: object) -> object:
    """Extract summary metadata from a parsed game page."""
    return _PARSER.get_game_sum(soup)


def get_random_game() -> object:
    """Return a random J-Archive game id discovered from the homepage."""
    return _FETCHER.get_random_game()
