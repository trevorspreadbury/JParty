"""Tests for the robot host's judge."""

from types import SimpleNamespace

import pytest

from jparty.domain.judging import Ruling, judge_response, normalize_response


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What is the Eiffel Tower?", "eiffel tower"),
        ("Who are The Beatles", "beatles"),
        ("what's a haiku", "haiku"),
        ("Who’s Hamlet?", "hamlet"),
        ("<i>Moby-Dick</i>", "moby dick"),
        ("(Abraham) Lincoln", "abraham lincoln"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_response(text: object, expected: str) -> None:
    """Question form, articles, markup and punctuation don't count."""
    assert normalize_response(text) == expected


def _clue(answer: str) -> object:
    """Return a clue stand-in with ``answer``."""
    return SimpleNamespace(answer=answer)


def test_exact_match_is_correct() -> None:
    """A response matching the answer once normalized is ruled correct."""
    clue = _clue("the Eiffel Tower")
    assert judge_response(clue, "What is the Eiffel Tower?") is Ruling.CORRECT


@pytest.mark.parametrize("heard", ["Lincoln", "What is Paris", "  "])
def test_anything_else_is_left_to_the_host(heard: str) -> None:
    """This judge never rules a response wrong; the host decides."""
    assert judge_response(_clue("(Abraham) Lincoln"), heard) is Ruling.UNSURE


def test_a_clue_without_an_answer_is_never_correct() -> None:
    """An empty answer can't match an empty response."""
    assert judge_response(_clue(""), "") is Ruling.UNSURE
