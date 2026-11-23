"""Rule on a spoken response to a clue.

This is the robot host's judge. It compares what a player was heard to say
with the clue's correct response from J-Archive or a Google Sheet. It leans
towards ``Ruling.UNSURE``, which leaves the ruling to the host, whenever the
response is neither a clear match nor clearly unrelated.

J-Archive writes optional and alternative parts of a correct response in
brackets, and the judge reads them that way:

- ``(Abraham) Lincoln``: words in parentheses may be left out.
- ``Frida (Kahlo)``, ``CO2 (carbon dioxide)``: a closing parenthetical may
  also be given on its own.
- ``boink (or bonk)``, ``Hispaniola (Haiti accepted)``: an alternative.
- ``The Very Hungry Caterpillar (by Eric Carle)``: extra information, never
  needed and not enough on its own.
- ``filets/fillets``: either word.
- ``does [DOHZ]``: square brackets are a pronunciation guide and are ignored.

A response is then ruled:

- correct when it matches one accepted form word for word, allowing for
  spelling slips from speech-to-text, plurals, spelled-out numbers and
  initialisms ("NYC" for "New York City");
- incorrect when it shares no meaningful word with any accepted form and
  looks nothing like one (a different number, such as "1958" for 1957,
  counts as looking nothing like it);
- unsure otherwise, for example a partial answer or one with extra words.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from enum import Enum
from itertools import product

from jparty.services.speech import speakable_text

# More optional parentheticals than this and only the two extremes (all in,
# all out) are tried, so a strange answer can't blow up the form count.
MAX_OPTIONAL_GROUPS = 4

# Whole-response similarity at or above this, after a word-for-word match
# fails, still rules a response correct (speech-to-text spelling slips).
CORRECT_SIMILARITY = 0.85
# Below this, with no meaningful word in common, a response is wrong.
INCORRECT_SIMILARITY = 0.5
# Words shorter than this must match exactly; longer ones may differ by a
# slip of spelling.
FUZZY_WORD_LENGTH = 4
FUZZY_WORD_SIMILARITY = 0.8
# A response this short must match exactly, not just look similar.
FUZZY_RESPONSE_LENGTH = 5

_TAG = re.compile(r"<[^>]+>")
_SQUARE_BRACKETS = re.compile(r"\[[^\]]*\]")
_PARENTHETICAL = re.compile(r"\(([^()]*)\)")
_ALTERNATIVE = re.compile(r"^(?:or|accept|also accepted)[:\s]+", re.IGNORECASE)
_ACCEPTED = re.compile(r"\s+accepted$", re.IGNORECASE)
_EXTRA_INFO = re.compile(r"^(?:by|from|of|doing|in)\s", re.IGNORECASE)
_WORD_SLASH = re.compile(r"\b([A-Za-z]+)/([A-Za-z]+)\b")
_QUESTION_FORM = re.compile(
    r"^(?:what|who|where|when)(?:\s+(?:is|are|was|were)|'s|s)?\b\s*"
)
_DIGIT_COMMA = re.compile(r"(?<=\d),(?=\d{3})")
_PUNCTUATION = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")

_ARTICLES = frozenset({"a", "an", "the"})
_FILLERS = frozenset({"um", "uh", "er", "erm", "hmm", "ah", "uhm", "umm"})
# Words too common to count as "having a word in common" with the answer.
_MINOR_WORDS = frozenset(
    {"of", "in", "on", "and", "to", "for", "at", "by", "de", "la", "le", "is"}
)
_NUMBER_WORDS = {
    word: str(value)
    for value, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve "
        "thirteen fourteen fifteen sixteen seventeen eighteen nineteen "
        "twenty".split()
    )
} | {
    "thirty": "30",
    "forty": "40",
    "fifty": "50",
    "sixty": "60",
    "seventy": "70",
    "eighty": "80",
    "ninety": "90",
    "hundred": "100",
}


class Ruling(Enum):
    """The judge's call on one response."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    # The judge can't tell; the host rules with the arrow keys.
    UNSURE = "unsure"


def _words(text: str) -> list[str]:
    """Split text into normalized words, without articles or fillers."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'").replace("&", " and ")
    text = _DIGIT_COMMA.sub("", text)
    # "A.A. Milne" -> "aa milne", "Chekhov's" -> "chekhovs": these marks join.
    text = text.replace(".", "").replace("'", "")
    text = _PUNCTUATION.sub(" ", text)
    words = []
    for word in text.split():
        if word in _ARTICLES or word in _FILLERS:
            continue
        words.append(_NUMBER_WORDS.get(word, word))
    return words


def normalize_response(text: object, question_form: bool = True) -> str:
    """Return ``text`` reduced to the words that decide a ruling.

    Markup and accents are removed, the text is lowercased, articles,
    fillers such as "um" and punctuation are dropped, and number words
    become digits.

    Args:
        text: A correct response or a player's transcribed response.
        question_form: Also drop a leading "what is" or "who are". Pass
            ``False`` for a correct response, which may itself start with a
            question word (*What Women Want*).

    Returns:
        The normalized words separated by single spaces; empty when nothing
        is left.
    """
    cleaned = speakable_text(text).lower().replace("’", "'").strip()
    if question_form:
        cleaned = _QUESTION_FORM.sub("", cleaned)
    return " ".join(_words(cleaned))


def accepted_forms(answer: object) -> list[str]:
    """Return every normalized form of ``answer`` that counts as correct.

    See the module docstring for how brackets and slashes are read.

    Args:
        answer: The clue's correct response as written in the game data.

    Returns:
        Distinct normalized forms, the full answer first. Empty when the
        answer has no words.
    """
    text = _TAG.sub("", str(answer or ""))
    text = _SQUARE_BRACKETS.sub(" ", text)
    raw_forms = []
    for main in _slash_alternatives(text):
        raw_forms.extend(_parenthetical_forms(main))
    forms = []
    for raw in raw_forms:
        form = normalize_response(raw, question_form=False)
        if form and form not in forms:
            forms.append(form)
    return forms


def _slash_alternatives(text: str) -> list[str]:
    """Expand ``a/b`` between words into each choice, keeping ``20/20``."""
    if not _WORD_SLASH.search(text):
        return [text]
    left = _WORD_SLASH.sub(r"\1", text)
    right = _WORD_SLASH.sub(r"\2", text)
    halves = [half for half in text.split("/") if half.strip()]
    return list(dict.fromkeys([left, right, *halves]))


def _parenthetical_forms(text: str) -> list[str]:
    """Expand optional and alternative parentheticals into plain forms."""
    groups = list(_PARENTHETICAL.finditer(text))
    if not groups:
        return [text]
    alternatives = []
    # Indexes into ``groups`` of the optional words that may be kept in.
    keepable = []
    for index, group in enumerate(groups):
        inner = group.group(1).strip()
        if _ALTERNATIVE.match(inner) or _ACCEPTED.search(inner):
            alternatives.append(_ACCEPTED.sub("", _ALTERNATIVE.sub("", inner)))
        elif not _EXTRA_INFO.match(inner):
            keepable.append(index)
            if not text[group.end() :].strip():
                # "CO2 (carbon dioxide)", "Frida (Kahlo)": may stand alone.
                alternatives.append(inner)
    if len(keepable) > MAX_OPTIONAL_GROUPS:
        choices = [(False,) * len(keepable), (True,) * len(keepable)]
    else:
        choices = list(product((True, False), repeat=len(keepable)))
    forms = []
    for choice in choices:
        kept = {index for index, keep in zip(keepable, choice) if keep}
        pieces, last = [], 0
        for index, group in enumerate(groups):
            pieces.append(text[last : group.start()])
            pieces.append(f" {group.group(1)} " if index in kept else " ")
            last = group.end()
        pieces.append(text[last:])
        forms.append("".join(pieces))
    return forms + alternatives


def _same_word(heard: str, expected: str) -> bool:
    """Whether two normalized words match, allowing plurals and slips."""
    if heard == expected:
        return True
    if heard.rstrip("s") == expected.rstrip("s") and heard.rstrip("s"):
        return True
    if heard.isdigit() or expected.isdigit():
        return False
    if min(len(heard), len(expected)) < FUZZY_WORD_LENGTH:
        return False
    ratio = SequenceMatcher(None, heard, expected).ratio()
    return ratio >= FUZZY_WORD_SIMILARITY


def _matches_word_for_word(heard: list[str], form: list[str]) -> bool:
    """Whether the response is the form, word for word."""
    return len(heard) == len(form) and all(
        _same_word(h, f) for h, f in zip(heard, form)
    )


def _digits(words: list[str]) -> list[str]:
    """Return the numbers among ``words``."""
    return [word for word in words if word.isdigit()]


def _looks_like(heard: str, form: str) -> float:
    """Return how alike two normalized responses are, ignoring spaces."""
    return SequenceMatcher(None, heard.replace(" ", ""), form.replace(" ", "")).ratio()


def _is_initialism(heard: list[str], form: list[str]) -> bool:
    """Whether one side is the initials of the other ("nyc", "new york city")."""
    if len(heard) == 1 and len(form) > 1:
        return heard[0] == "".join(word[0] for word in form)
    if len(form) == 1 and len(heard) > 1:
        return form[0] == "".join(word[0] for word in heard)
    return False


def _shares_a_word(heard: list[str], form: list[str]) -> bool:
    """Whether the response has a meaningful word of the form in it."""
    return any(
        _same_word(h, f)
        for h in heard
        if h not in _MINOR_WORDS
        for f in form
        if f not in _MINOR_WORDS
    )


def judge_response(question: object, transcript: str) -> Ruling:
    """Rule on what a player said in response to ``question``.

    Args:
        question: The clue; its ``answer`` is the correct response.
        transcript: What the player was heard to say.

    Returns:
        The ruling. See the module docstring for when each is given.
    """
    answer = getattr(question, "answer", "")
    forms = accepted_forms(answer)
    response = normalize_response(transcript)
    if not response or not forms:
        return Ruling.UNSURE
    # "What Women Want" may be the response itself, not "what is" + response.
    heard_texts = list(dict.fromkeys([response, normalize_response(transcript, False)]))
    for heard_text, form_text in product(heard_texts, forms):
        heard, form = heard_text.split(), form_text.split()
        if _matches_word_for_word(heard, form) or _is_initialism(heard, form):
            return Ruling.CORRECT
        if _is_a_slip_of(heard_text, form_text):
            return Ruling.CORRECT
    if _is_unrelated(response, [*forms, normalize_response(answer, False)]):
        return Ruling.INCORRECT
    return Ruling.UNSURE


def _is_unrelated(response: str, forms: list[str]) -> bool:
    """Whether a response that didn't match is clearly a different answer.

    It is when it shares no meaningful word with any form and looks nothing
    like one. A form whose numbers differ from the response's doesn't count
    as looking like it ("1958" for 1957). ``forms`` should include the whole
    answer with its extra information, so naming the author of a book
    (*The Very Hungry Caterpillar (by Eric Carle)*) is left to the host.

    Only the response without "what is" is used here; with it, "what is"
    alone makes short answers look alike.
    """
    heard = response.split()
    for form_text in forms:
        form = form_text.split()
        if _shares_a_word(heard, form):
            return False
        if _looks_like(response, form_text) >= INCORRECT_SIMILARITY and _digits(
            heard
        ) == _digits(form):
            return False
    return True


def _is_a_slip_of(heard: str, form: str) -> bool:
    """Whether ``heard`` is ``form`` with a slip that word matching missed.

    This catches speech-to-text writing "light house" for "lighthouse" or
    misspelling a short word. The two must be within one letter of the same
    length, so a response that leaves words out ("Lakers" for "the L.A.
    Lakers") is not a slip.
    """
    heard_letters, form_letters = heard.replace(" ", ""), form.replace(" ", "")
    return (
        _looks_like(heard, form) >= CORRECT_SIMILARITY
        and len(heard_letters) >= FUZZY_RESPONSE_LENGTH
        and abs(len(heard_letters) - len(form_letters)) <= 1
        and _digits(heard.split()) == _digits(form.split())
    )
