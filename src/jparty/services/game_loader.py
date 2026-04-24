"""Compatibility exports for game-loading service functions.

This module provides a stable import surface for the application's game loading
helpers. The actual implementations live in ``archive_client``, but re-exporting
them here keeps service-oriented imports organized and backwards compatible.
"""

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

__all__ = [
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
