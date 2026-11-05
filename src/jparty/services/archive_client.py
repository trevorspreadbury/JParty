"""Compatibility exports for archived game loading helpers."""

from __future__ import annotations

import logging
import os

from bs4 import BeautifulSoup

from jparty.app.paths import QUESTION_MEDIA, SAVED_GAMES

from .game_cache import GameCache
from .game_loading import GOOGLE_SHEETS_ID_LENGTH
from .game_parser import GameParser
from .game_sources import GameSourceFetcher

_LOADED_GAME_HTML_CACHE: dict[str, str] = {}
_FETCHER = GameSourceFetcher()
_PARSER = GameParser()


def list_to_game(rows: object) -> object:
    """Convert sheet rows into ``GameData`` using the shared parser."""
    return _PARSER.list_to_game(rows)


def get_Gsheet_game(file_id: object) -> object:
    """Fetch and parse a Google Sheets-backed game."""
    return _PARSER.list_to_game(_FETCHER.get_google_sheet_rows(file_id))


def get_game_html(game_id: object) -> object:
    """Load archived game HTML from cache or remote fallback sources."""
    cache = GameCache(SAVED_GAMES)
    game_html = cache.load_saved_html(game_id)
    if game_html is not None:
        _LOADED_GAME_HTML_CACHE[str(game_id)] = game_html
        return game_html
    try:
        game_html = get_wayback_game_html(game_id)
    except Exception:
        logging.error("Wayback lookup failed for %s", game_id, exc_info=True)
        game_html = get_jarchive_game_html(game_id)
    _LOADED_GAME_HTML_CACHE[str(game_id)] = game_html
    return game_html


def save_game_html(game_id: object) -> object:
    """Persist a numeric J-Archive game HTML payload into the local cache."""
    game_id_str = str(game_id)
    if len(game_id_str) >= GOOGLE_SHEETS_ID_LENGTH:
        return None
    saved_game_path = SAVED_GAMES / f"{game_id_str}.html"
    if saved_game_path.exists():
        return saved_game_path
    game_html = _LOADED_GAME_HTML_CACHE.get(game_id_str)
    if game_html is None:
        game_html = get_game_html(game_id_str)
    saved_game_path.write_text(game_html, encoding="utf-8")
    return saved_game_path


def get_game(game_id: object) -> object:
    """Load a game from either J-Archive-style HTML or Google Sheets."""
    os.environ["JPARTY_GAME_ID"] = str(game_id)
    if len(str(game_id)) < GOOGLE_SHEETS_ID_LENGTH:
        game_html = get_game_html(game_id)
        return process_game_board_from_html(game_html, game_id)
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
