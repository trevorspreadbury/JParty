"""Core gameplay domain models and engine entry points.

The ``jparty.domain`` package contains the central game engine, input helpers,
serialization logic, and data models that describe Jeopardy rounds, clues,
players, and buzz attempts. Other layers import from here to work with the
shared gameplay state in a consistent way.
"""

from .game_engine import Game
from .models import Board, BuzzAttempt, FinalBoard, GameData, Player, Question

__all__ = [
    "Board",
    "BuzzAttempt",
    "FinalBoard",
    "Game",
    "GameData",
    "Player",
    "Question",
]
