"""Core gameplay domain models and engine entry points.

The ``jparty.domain`` package contains the central game engine, input helpers,
serialization logic, and data models that describe Jeopardy rounds, clues,
players, and buzz attempts. Other layers import from here to work with the
shared gameplay state in a consistent way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Board, BuzzAttempt, FinalBoard, GameData, Player, Question

if TYPE_CHECKING:
    from .game_engine import Game

__all__ = [
    "Board",
    "BuzzAttempt",
    "FinalBoard",
    "Game",
    "GameData",
    "Player",
    "Question",
]


def __getattr__(name: str) -> object:
    """Import ``Game`` on first use.

    ``game_engine`` imports ``jparty.services``, which imports
    ``jparty.domain.models``. Importing ``Game`` eagerly here would make
    ``import jparty.services`` fail with a circular import when it runs first.

    Args:
        name: Attribute requested from the package.

    Returns:
        The requested attribute.

    Raises:
        AttributeError: If ``name`` is not a lazily exported attribute.
    """
    if name == "Game":
        from .game_engine import Game

        return Game
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
