"""Compatibility exports for persisted game-state helpers.

This module gathers the persistence-related functions used by the application
for loading, saving, and reconstructing gameplay state. The implementations
live in ``jparty.domain.state`` and are re-exported here as service utilities.
"""

from jparty.domain.state import (
    classify_buzz_phases,
    get_current_game_state,
    load_general_state,
    load_question_history,
    reconstruct_score_history,
    save_general_state,
)

__all__ = [
    "classify_buzz_phases",
    "get_current_game_state",
    "load_general_state",
    "load_question_history",
    "reconstruct_score_history",
    "save_general_state",
]
