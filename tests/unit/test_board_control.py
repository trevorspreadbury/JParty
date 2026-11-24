"""Tests for who has control of the board."""

from types import SimpleNamespace

import pytest

from jparty.domain.board_control import (
    board_for_phone,
    control_after_ruling,
    control_at_round_start,
    control_from_history,
)
from jparty.domain.models import Board, Question

pytestmark = pytest.mark.unit


def _players(*scores: int) -> list[SimpleNamespace]:
    """Return players in seat order with ``scores``."""
    return [
        SimpleNamespace(score=score, player_number=number)
        for number, score in enumerate(scores)
    ]


def test_first_round_starts_at_seat_one() -> None:
    """Everyone has $0, so the earliest seat picks first."""
    players = _players(0, 0, 0)
    assert control_at_round_start(players) is players[0]


def test_later_round_starts_with_the_lowest_score() -> None:
    """The trailing player picks first; ties go to the earlier seat."""
    players = _players(2000, -400, 600, -400)
    assert control_at_round_start(players) is players[1]


def test_no_players_means_no_control() -> None:
    """An empty game has nobody to pick."""
    assert control_at_round_start([]) is None
    assert control_from_history([], 0, []) is None


def test_correct_response_takes_control() -> None:
    """A correct response passes control; a wrong one leaves it."""
    alice, bob = _players(0, 0)
    assert control_after_ruling(alice, bob, correct=True) is bob
    assert control_after_ruling(alice, bob, correct=False) is alice


def _clue_entry(round_index: int, *attempts: tuple[int, bool]) -> dict:
    """Return a question_history clue line with ``(player, correct)`` attempts."""
    return {
        "question_index": [0, 0],
        "round_index": round_index,
        "answer_attempts": [
            {"player_index": player, "answer_correct": correct}
            for player, correct in attempts
        ],
    }


def test_resume_gives_control_to_the_last_correct_player_this_round() -> None:
    """Wrong responses and earlier rounds don't count."""
    players = _players(400, 800, 0)
    history = [
        _clue_entry(0, (2, True)),
        _clue_entry(1, (0, True)),
        _clue_entry(1, (1, False), (2, True)),
        _clue_entry(1, (0, False)),
        {"type": "manual_score_adjustment", "player_index": 0},
    ]
    assert control_from_history(history, 1, players) is players[2]


def test_resume_falls_back_to_the_lowest_score() -> None:
    """With no correct response this round, the round's first picker has it."""
    players = _players(400, -200, 0)
    history = [_clue_entry(0, (0, True)), _clue_entry(1, (0, False))]
    assert control_from_history(history, 1, players) is players[1]


def test_resume_skips_a_player_no_longer_seated() -> None:
    """Control can't go to a seat that is empty now."""
    players = _players(400, 0)
    history = [_clue_entry(0, (5, True))]
    assert control_from_history(history, 0, players) is players[1]


def test_board_for_phone_marks_played_clues() -> None:
    """Each row lists its value per category, with gaps for played clues."""
    categories = [f"Cat {i}" for i in range(6)]
    questions = [
        Question((col, row), "clue", "answer", categories[col], (row + 1) * 200)
        for col in range(6)
        for row in range(5)
        if (col, row) != (5, 4)
    ]
    questions[0].complete = True
    board = Board(categories, questions)

    payload = board_for_phone(board)

    assert payload["categories"] == categories
    assert len(payload["rows"]) == 5
    assert payload["rows"][0] == [None, 200, 200, 200, 200, 200]
    assert payload["rows"][4] == [1000, 1000, 1000, 1000, 1000, None]
