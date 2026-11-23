"""Rule on a spoken response to a clue.

This is the robot host's judge. It is deliberately strict for now: a response
is ruled correct only when it matches the clue's answer exactly once both are
normalized, and anything else is left for the host to rule on. Matching that
can also rule a response wrong (partial names, misspellings from
speech-to-text, alternatives such as "X or Y") comes next.
"""

import re
from enum import Enum

from jparty.services.speech import speakable_text

_QUESTION_FORM = re.compile(r"^(?:what|who|where|when)(?: is| are| was| were|'s|s)?\s+")
_ARTICLES = re.compile(r"\b(?:a|an|the)\b")
_PUNCTUATION = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")


class Ruling(Enum):
    """The judge's call on one response."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    # The judge can't tell; the host rules with the arrow keys.
    UNSURE = "unsure"


def normalize_response(text: object) -> str:
    """Return ``text`` reduced to the words that decide a ruling.

    Markup is removed, the text is lowercased, a leading "what is" or
    "who are" is dropped, and so are articles and punctuation.

    Args:
        text: A clue's answer or a player's transcribed response.

    Returns:
        The normalized words separated by single spaces; empty when nothing
        is left.
    """
    cleaned = speakable_text(text).lower().replace("’", "'")
    cleaned = _QUESTION_FORM.sub("", cleaned)
    cleaned = _PUNCTUATION.sub(" ", cleaned)
    cleaned = _ARTICLES.sub(" ", cleaned)
    return _SPACES.sub(" ", cleaned).strip()


def judge_response(question: object, transcript: str) -> Ruling:
    """Rule on what a player said in response to ``question``.

    Args:
        question: The clue; its ``answer`` is the correct response.
        transcript: What the player was heard to say.

    Returns:
        ``Ruling.CORRECT`` for an exact match once normalized, otherwise
        ``Ruling.UNSURE``. This judge never rules a response incorrect.
    """
    heard = normalize_response(transcript)
    answer = normalize_response(getattr(question, "answer", ""))
    if heard and heard == answer:
        return Ruling.CORRECT
    return Ruling.UNSURE
