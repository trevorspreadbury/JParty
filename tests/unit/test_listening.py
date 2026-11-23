"""Tests for hearing a spoken response with the microphone and Whisper.

None of these need the optional ``robot`` extra; the audio tests that do are
in ``test_listening_audio.py``.
"""

import pytest

from jparty.services import listening
from jparty.services.listening import SpeechEndpointer, speech_rms_threshold

CHUNK = 0.05  # Seconds of audio per fed chunk.
LOUD = 0.2
QUIET = 0.001


def _feed(endpointer: SpeechEndpointer, rms: float, seconds: float) -> str:
    """Feed ``seconds`` of audio at loudness ``rms``; return the last state."""
    state = endpointer.state
    for _ in range(round(seconds / CHUNK)):
        state = endpointer.feed(rms, CHUNK)
    return state


def test_endpointer_waits_then_ends_after_quiet() -> None:
    """Speech starts on sustained loudness and ends after enough quiet."""
    endpointer = SpeechEndpointer(speech_rms=0.01)
    assert _feed(endpointer, QUIET, 1.0) == "waiting"
    assert _feed(endpointer, LOUD, 1.0) == "speaking"
    assert _feed(endpointer, QUIET, 0.5) == "speaking"  # A pause between words.
    assert _feed(endpointer, LOUD, 0.5) == "speaking"
    assert _feed(endpointer, QUIET, 0.8) == "done"
    assert endpointer.heard_speech is True


def test_a_click_is_not_speech() -> None:
    """Loudness shorter than the start time doesn't count."""
    endpointer = SpeechEndpointer(speech_rms=0.01)
    endpointer.feed(LOUD, CHUNK)
    assert _feed(endpointer, QUIET, 1.0) == "waiting"
    assert endpointer.heard_speech is False


def test_silence_times_out() -> None:
    """A player who says nothing for five seconds has not answered."""
    endpointer = SpeechEndpointer(speech_rms=0.01)
    assert _feed(endpointer, QUIET, 4.9) == "waiting"
    assert _feed(endpointer, QUIET, 0.1) == "done"
    assert endpointer.heard_speech is False


def test_a_response_in_a_noisy_room_still_ends() -> None:
    """Noise above the threshold is quiet compared with the player's voice."""
    endpointer = SpeechEndpointer(speech_rms=0.01)
    noise = 0.02
    assert _feed(endpointer, noise, 0.5) == "speaking"
    _feed(endpointer, LOUD, 1.0)
    assert _feed(endpointer, noise, 0.8) == "done"


def test_a_response_is_cut_off_at_the_time_limit() -> None:
    """Endless speech, or endless noise, stops at the maximum length."""
    endpointer = SpeechEndpointer(speech_rms=0.01)
    assert _feed(endpointer, LOUD, 7.9) == "speaking"
    assert _feed(endpointer, LOUD, 0.1) == "done"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("", 0.01), ("0.004", 0.004), ("loud", 0.01), ("-1", 0.01)],
)
def test_speech_threshold_can_be_tuned(value: str, expected: float) -> None:
    """JPARTY_SPEECH_RMS overrides the threshold when it is a positive number."""
    assert speech_rms_threshold({"JPARTY_SPEECH_RMS": value}) == expected


def test_packaged_app_says_it_has_no_speech_to_text(monkeypatch: object) -> None:
    """The frozen app explains that speech-to-text isn't shipped yet."""
    monkeypatch.setattr(listening.sys, "frozen", True, raising=False)
    assert "packaged app" in listening.listening_unavailable_reason()


def test_listening_needs_speech_to_text(monkeypatch: object) -> None:
    """Without faster-whisper, the reason says how to get it."""
    monkeypatch.setattr(listening.importlib.util, "find_spec", lambda name: None)
    reason = listening.listening_unavailable_reason()
    assert "robot" in reason
    assert listening.create_microphone_listener() is None
