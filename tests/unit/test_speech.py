"""Tests for reading clues aloud with text-to-speech."""

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtTextToSpeech import QTextToSpeech

from jparty.services.speech import Speaker, speakable_text

State = QTextToSpeech.State


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, ""),
        ("   ", ""),
        ("This <i>Hamlet</i> line", "This Hamlet line"),
        ("Tom &amp; Jerry", "Tom & Jerry"),
        ('It\\\'s a \\"test\\"', 'It\'s a "test"'),
        ("To be or ____ to be", "To be or blank to be"),
        ("(Abraham) Lincoln", "Abraham Lincoln"),
        ("Line one\n  line   two", "Line one line two"),
    ],
)
def test_speakable_text_cleans_clue_text(text: object, expected: str) -> None:
    """Markup, escapes, blanks and brackets are turned into plain speech."""
    assert speakable_text(text) == expected


class FakeEngine(QObject):
    """``QTextToSpeech`` stand-in that changes state only when told to."""

    stateChanged = pyqtSignal(object)  # noqa: N815 - mirrors Qt's name

    def __init__(self, state: object = State.Ready) -> None:
        """Start in ``state`` with nothing said."""
        super().__init__()
        self._state = state
        self.said = []
        self.stop_calls = 0

    def state(self) -> object:
        """Return the current state."""
        return self._state

    def errorString(self) -> str:  # noqa: N802 - mirrors Qt's name
        """Return a fixed error message."""
        return "no voice"

    def say(self, text: str) -> None:
        """Record ``text`` without starting to read it."""
        self.said.append(text)

    def stop(self) -> None:
        """Record a stop."""
        self.stop_calls += 1

    def move_to(self, state: object) -> None:
        """Change state and report it, as the real engine does."""
        self._state = state
        self.stateChanged.emit(state)


def test_speaker_reports_when_text_has_been_read() -> None:
    """The callback runs once the engine goes from speaking back to ready."""
    engine = FakeEngine()
    speaker = Speaker(lambda: engine)
    finished = []

    assert speaker.say("A clue", lambda: finished.append(True)) is True
    assert engine.said == ["A clue"]
    engine.move_to(State.Speaking)
    assert finished == []
    engine.move_to(State.Ready)
    assert finished == [True]
    engine.move_to(State.Ready)
    assert finished == [True]


def test_speaker_ignores_ready_from_the_reading_it_cut_off() -> None:
    """A Ready left over from stopping old text doesn't finish the new text."""
    engine = FakeEngine()
    speaker = Speaker(lambda: engine)
    finished = []
    speaker.say("Old clue", lambda: finished.append("old"))
    engine.move_to(State.Speaking)

    speaker.say("New clue", lambda: finished.append("new"))
    engine.move_to(State.Ready)  # From stopping the old clue.
    assert finished == []

    engine.move_to(State.Speaking)
    engine.move_to(State.Ready)
    assert finished == ["new"]


def test_stopping_drops_the_callback() -> None:
    """A stopped reading never reports that it finished."""
    engine = FakeEngine()
    speaker = Speaker(lambda: engine)
    finished = []
    speaker.say("A clue", lambda: finished.append(True))
    engine.move_to(State.Speaking)

    speaker.stop()
    engine.move_to(State.Ready)

    assert finished == []
    assert engine.stop_calls >= 1


def test_engine_error_drops_the_callback() -> None:
    """A reading that fails leaves the host to carry on by hand."""
    engine = FakeEngine()
    speaker = Speaker(lambda: engine)
    finished = []
    speaker.say("A clue", lambda: finished.append(True))
    engine.move_to(State.Speaking)
    engine.move_to(State.Error)
    engine.move_to(State.Ready)
    assert finished == []


def test_blank_text_is_not_read() -> None:
    """There is nothing to wait for when a clue has no text."""
    engine = FakeEngine()
    speaker = Speaker(lambda: engine)
    assert speaker.say("  ", lambda: None) is False
    assert engine.said == []


def test_engine_is_only_created_when_needed() -> None:
    """A game that never reads aloud never starts the engine."""
    created = []
    speaker = Speaker(lambda: created.append(True) or FakeEngine())
    speaker.stop()
    assert created == []
    assert speaker.prepare() is True
    speaker.say("A clue")
    speaker.say("Another clue")
    assert created == [True]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: FakeEngine(State.Error),
        lambda: (_ for _ in ()).throw(RuntimeError("no plugin")),
    ],
    ids=["error-state", "raises"],
)
def test_unusable_engine_reads_nothing(factory: object) -> None:
    """Without a working voice, say() reports that nothing was read."""
    speaker = Speaker(factory)
    assert speaker.available is False
    assert speaker.say("A clue", lambda: None) is False
    speaker.stop()
