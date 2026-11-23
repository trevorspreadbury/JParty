"""Tests for the robot host's judge.

The answers are written the way J-Archive writes them, brackets included.
"""

from types import SimpleNamespace

import pytest

from jparty.domain.judging import (
    Ruling,
    accepted_forms,
    judge_response,
    normalize_response,
)

CORRECT = Ruling.CORRECT
INCORRECT = Ruling.INCORRECT
UNSURE = Ruling.UNSURE


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What is the Eiffel Tower?", "eiffel tower"),
        ("Who are The Beatles", "beatles"),
        ("what's a haiku", "haiku"),
        ("Who’s Hamlet?", "hamlet"),
        ("<i>Moby-Dick</i>", "moby dick"),
        ("(Abraham) Lincoln", "abraham lincoln"),
        ("What is, um, A.A. Milne?", "aa milne"),
        ("Chekhov's gun", "chekhovs gun"),
        ("Día de los Muertos", "dia de los muertos"),
        ("1,001 nights", "1001 nights"),
        ("Seven Samurai", "7 samurai"),
        ("Harold & Kumar", "harold and kumar"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_response(text: object, expected: str) -> None:
    """Question form, articles, fillers, markup and punctuation don't count."""
    assert normalize_response(text) == expected


def test_a_correct_response_keeps_its_own_question_word() -> None:
    """*What Women Want* is a title, not "what is" + "women want"."""
    assert normalize_response("What Women Want", question_form=False) == (
        "what women want"
    )


@pytest.mark.parametrize(
    ("answer", "forms"),
    [
        ("(Abraham) Lincoln", ["abraham lincoln", "lincoln"]),
        ("Frida (Kahlo)", ["frida kahlo", "frida", "kahlo"]),
        ("CO2 (carbon dioxide)", ["co2 carbon dioxide", "co2", "carbon dioxide"]),
        ("boink (or bonk)", ["boink", "bonk"]),
        ("Hispaniola (Haiti accepted)", ["hispaniola", "haiti"]),
        ("The Very Hungry Caterpillar (by Eric Carle)", ["very hungry caterpillar"]),
        ("filets/fillets", ["filets", "fillets"]),
        ("20/20", ["20 20"]),
        ("does [DOHZ] and does [DUHZ]", ["does and does"]),
    ],
)
def test_accepted_forms(answer: str, forms: list[str]) -> None:
    """Brackets and slashes expand into the forms that count as correct."""
    assert sorted(accepted_forms(answer)) == sorted(forms)


def test_many_optional_parts_are_capped() -> None:
    """A long run of optional words can't produce thousands of forms."""
    answer = " ".join(f"({word})" for word in "a b c d e f g".split()) + " end"
    assert len(accepted_forms(answer)) <= 3


def _judge(answer: str, heard: str) -> Ruling:
    """Judge ``heard`` against a clue whose correct response is ``answer``."""
    return judge_response(SimpleNamespace(answer=answer), heard)


@pytest.mark.parametrize(
    ("answer", "heard", "ruling"),
    [
        # Exact, once normalized.
        ("the Eiffel Tower", "What is the Eiffel Tower?", CORRECT),
        ("<i>Moby-Dick</i>", "what is moby dick", CORRECT),
        ("What Women Want", "What is What Women Want?", CORRECT),
        ("What Women Want", "What Women Want", CORRECT),
        # Optional and alternative parts.
        ("(Abraham) Lincoln", "Who is Lincoln?", CORRECT),
        ("(Abraham) Lincoln", "Who is Abraham Lincoln?", CORRECT),
        ("(Abraham) Lincoln", "Who is Abraham?", UNSURE),
        ("Dwight D. Eisenhower (Ike)", "Who is Ike?", CORRECT),
        ("boink (or bonk)", "what is bonk", CORRECT),
        ("Hispaniola (Haiti accepted)", "What is Haiti?", CORRECT),
        ("The Very Hungry Caterpillar (by Eric Carle)", "Eric Carle", UNSURE),
        ("the mouth/delta", "what is the delta", CORRECT),
        # Speech-to-text slips.
        ("(Pyotr) Tchaikovsky", "Who is Tchaikovski?", CORRECT),
        ("Rihanna", "who is rihana", CORRECT),
        ("a lighthouse", "what is a light house", CORRECT),
        ("Ghostbusters", "what are ghost busters", CORRECT),
        # Plurals, numbers and initialisms.
        ("the Beatles", "Who is the Beatle?", CORRECT),
        ("<i>Seven Samurai</i>", "What is 7 Samurai?", CORRECT),
        ("New York City", "What is NYC?", CORRECT),
        ("MLS (Major League Soccer)", "What is Major League Soccer?", CORRECT),
        ("1957", "What is 1958?", INCORRECT),
        ("<i>12 Years a Slave</i>", "13 Years a Slave", UNSURE),
        # Partial or padded responses are left to the host.
        ("the L.A. Lakers", "Who are the Lakers?", UNSURE),
        ("<i>To the Lighthouse</i>", "What is Lighthouse?", UNSURE),
        ("the Eiffel Tower", "the Eiffel Tower in Paris", UNSURE),
        # Clearly wrong.
        ("the Eiffel Tower", "What is the Statue of Liberty?", INCORRECT),
        ("Chekhov", "Who is Tolstoy?", INCORRECT),
        ("a giraffe", "what is an elephant", INCORRECT),
    ],
)
def test_judge_response(answer: str, heard: str, ruling: Ruling) -> None:
    """Rulings on realistic responses to J-Archive answers."""
    assert _judge(answer, heard) is ruling


@pytest.mark.parametrize("heard", ["", "   ", "um", "what is"])
def test_a_response_with_no_words_is_left_to_the_host(heard: str) -> None:
    """The robot host rules silence wrong itself; the judge stays unsure."""
    assert _judge("the Eiffel Tower", heard) is UNSURE


def test_a_clue_without_an_answer_is_left_to_the_host() -> None:
    """Without a correct response there is nothing to compare with."""
    assert _judge("", "What is Paris?") is UNSURE
