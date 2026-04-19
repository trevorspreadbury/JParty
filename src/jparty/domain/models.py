"""Core data models representing games, boards, clues, and players.

This module defines the domain objects that the rest of JParty passes around
when loading archived games, tracking buzz attempts, and updating player state.
These models intentionally stay lightweight so the engine, services, and UI can
share a common representation of game data.
"""

import os
import sys
from dataclasses import dataclass

from jparty.domain.input import index_to_key

BOARD_QUESTION_COUNT = 30


@dataclass
class Question:
    """Represent a single clue on the board or in Final Jeopardy."""

    index: tuple
    text: str
    answer: str
    category: str
    value: int = -1
    dd: bool = False
    complete: bool = False
    image: bool = False
    image_url: str = None
    actual_results: str = None


@dataclass
class BuzzAttempt:
    """Capture one player buzz interaction for analytics and persistence."""

    player_index: int
    question_index: tuple
    timestamp: float
    is_early: bool
    is_success: bool
    is_rebound: bool
    in_timeout: bool


class Board:
    """Represent a standard Jeopardy round board."""

    size = (6, 5)

    def __init__(
        self, categories: object, questions: object, dj: object = False
    ) -> None:
        """Initialize a board with categories and clue objects.

        Args:
            categories: Sequence of category names displayed on the board.
            questions: Sequence of ``Question`` objects belonging to the board.
            dj: Whether this board represents the Double Jeopardy round.

        Returns:
            ``None``.
        """
        self.categories = categories
        self.dj = dj
        self.questions = questions or []

    def get_question(self, i: object, j: object) -> object:
        """Return the question at a board coordinate if one exists.

        Args:
            i: Zero-based category index.
            j: Zero-based clue row index.

        Returns:
            The matching ``Question`` object, or ``None`` if no clue matches the
            requested coordinates.
        """
        for question in self.questions:
            if question.index == (i, j):
                return question
        return None

    def complete(self) -> object:
        """Check whether the board has the expected number of clues.

        Returns:
            ``True`` when the board contains all standard clues, otherwise
            ``False``.
        """
        return len(self.questions) == BOARD_QUESTION_COUNT


class FinalBoard(Board):
    """Represent the single-clue Final Jeopardy board."""

    size = (1, 1)

    def __init__(self, category: object, question: object) -> None:
        """Initialize the Final Jeopardy board wrapper.

        Args:
            category: Final Jeopardy category name.
            question: ``Question`` object representing the final clue.

        Returns:
            ``None``.
        """
        super().__init__([category], [question], dj=False)
        self.category = category
        self.question = question

    def complete(self) -> object:
        """Check whether the final board has its single required clue.

        Returns:
            ``True`` when the final board contains exactly one question.
        """
        return len(self.questions) == 1


@dataclass
class GameData:
    """Bundle the parsed rounds and metadata for one archived game."""

    rounds: list
    date: str
    comments: str


class Player:
    """Represent a connected player and their live game state."""

    def __init__(self, name: object, waiter: object, player_number: object) -> None:
        """Initialize a player session.

        Args:
            name: Display name chosen by the player.
            waiter: Connection or response channel used to communicate with the
                player's lectern client.
            player_number: Zero-based player slot currently assigned to the
                player.

        Returns:
            ``None``.
        """
        self.name = name
        self.token = os.urandom(15)
        self.score = 0
        self.waiter = waiter
        self.wager = None
        self.finalanswer = ""
        self.page = "buzz"
        self.player_number = player_number
        self.key = index_to_key[player_number]

    def __hash__(self) -> object:
        """Return a stable hash derived from the player's random token.

        Returns:
            Integer hash value suitable for set membership and dict keys.
        """
        return int.from_bytes(self.token, sys.byteorder)

    def state(self) -> object:
        """Return a minimal serializable view of the player's current state.

        Returns:
            A dictionary containing the current page and score.
        """
        return {"page": self.page, "score": self.score}
