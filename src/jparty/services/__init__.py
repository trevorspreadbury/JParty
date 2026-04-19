"""High-level service entry points used across JParty.

The services package groups together modules that fetch remote game data,
perform lightweight media lookups, and expose persistence helpers. This package
re-exports the most commonly used game-loading functions for convenient imports.
"""

from .game_loader import get_game, get_random_game

__all__ = ["get_game", "get_random_game"]
