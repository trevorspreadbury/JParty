import os
import sys
from dataclasses import dataclass

from jparty.domain.input import index_to_key


@dataclass
class Question:
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
    player_index: int
    question_index: tuple
    timestamp: float
    is_early: bool
    is_success: bool
    is_rebound: bool
    in_timeout: bool


class Board:
    size = (6, 5)

    def __init__(self, categories, questions, dj=False):
        self.categories = categories
        self.dj = dj
        self.questions = questions or []

    def get_question(self, i, j):
        for question in self.questions:
            if question.index == (i, j):
                return question
        return None

    def complete(self):
        return len(self.questions) == 30


class FinalBoard(Board):
    size = (1, 1)

    def __init__(self, category, question):
        super().__init__([category], [question], dj=False)
        self.category = category
        self.question = question

    def complete(self):
        return len(self.questions) == 1


@dataclass
class GameData:
    rounds: list
    date: str
    comments: str


class Player:
    def __init__(self, name, waiter, player_number):
        self.name = name
        self.token = os.urandom(15)
        self.score = 0
        self.waiter = waiter
        self.wager = None
        self.finalanswer = ""
        self.page = "buzz"
        self.player_number = player_number
        self.key = index_to_key[player_number]

    def __hash__(self):
        return int.from_bytes(self.token, sys.byteorder)

    def state(self):
        return {"page": self.page, "score": self.score}
