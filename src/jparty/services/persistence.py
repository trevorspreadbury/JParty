"""Compatibility exports for persisted game-state helpers.

This module gathers the persistence-related functions used by the application
for loading, saving, and reconstructing gameplay state. The implementations
live in ``jparty.domain.state`` and are re-exported here as service utilities.
"""

from jparty.domain.state import (
    MANUAL_SCORE_ADJUSTMENT_TYPE,
    QUESTION_HISTORY_ENTRY_TYPE,
    SCORE_CORRECTION_TYPE,
    HistoryFileError,
    classify_buzz_phases,
    get_current_game_state,
    get_history_entry_type,
    is_manual_score_adjustment,
    is_question_history_entry,
    load_general_state,
    load_question_history,
    read_history_file,
    reconstruct_score_history,
    save_general_state,
)

__all__ = [
    "MANUAL_SCORE_ADJUSTMENT_TYPE",
    "QUESTION_HISTORY_ENTRY_TYPE",
    "SCORE_CORRECTION_TYPE",
    "HistoryFileError",
    "classify_buzz_phases",
    "get_history_entry_type",
    "get_current_game_state",
    "is_manual_score_adjustment",
    "is_question_history_entry",
    "load_general_state",
    "load_question_history",
    "read_history_file",
    "reconstruct_score_history",
    "save_general_state",
]
