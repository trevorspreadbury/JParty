"""Tests for recording and transcribing a spoken response.

No microphone or speech model is used: audio is fed in directly and the
transcriber is faked. These need numpy, which comes with the optional
``robot`` extra, and are skipped without it.
"""

import pytest

np = pytest.importorskip("numpy", reason="needs the robot extra")

from jparty.services import listening  # noqa: E402
from jparty.services.listening import (  # noqa: E402
    MicrophoneListener,
    SpeechEndpointer,
)

CHUNK = 0.05  # Seconds of audio per fed chunk.
LOUD = 0.2
QUIET = 0.001


def test_pcm_to_mono_scales_and_mixes_channels() -> None:
    """Stereo int16 becomes mono floats between -1 and 1."""
    raw = np.array([16384, -16384, 32767, 32767], dtype=np.int16).tobytes()
    mono = listening.pcm_to_mono(raw, "int16", 2)
    assert mono.tolist() == pytest.approx([0.0, 32767 / 32768])


def test_pcm_to_mono_reads_float_and_uint8() -> None:
    """Float samples pass through; unsigned 8-bit is centred on 128."""
    floats = np.array([0.5, -0.5], dtype=np.float32).tobytes()
    assert listening.pcm_to_mono(floats, "float", 1).tolist() == [0.5, -0.5]
    bytes8 = np.array([128, 255], dtype=np.uint8).tobytes()
    assert listening.pcm_to_mono(bytes8, "uint8", 1).tolist() == pytest.approx(
        [0.0, 127 / 128]
    )


def test_resample_to_16k() -> None:
    """48 kHz audio becomes a third as many samples at 16 kHz."""
    samples = np.linspace(-1, 1, 4800, dtype=np.float32)
    assert len(listening.resample(samples, 48000)) == 1600
    assert listening.resample(samples, 16000) is not samples


def test_rms() -> None:
    """A full-scale square wave has loudness 1; silence has 0."""
    assert listening.rms(np.array([1.0, -1.0], dtype=np.float32)) == 1.0
    assert listening.rms(np.zeros(0, dtype=np.float32)) == 0.0


class FakeTranscriber:
    """Stand-in for Whisper that returns a fixed transcript."""

    def __init__(self, text: str = "Who is Tchaikovsky?") -> None:
        """Start with nothing loaded or transcribed."""
        self.text = text
        self.load_calls = 0
        self.calls = []
        self.error = None

    def load(self) -> None:
        """Record a load."""
        self.load_calls += 1

    def transcribe(self, audio: object, hint: str = "") -> str:
        """Record the audio and hint, then return the transcript."""
        if self.error:
            raise self.error
        self.calls.append((audio, hint))
        return self.text


RATE = 16000


def _chunk(level: float, seconds: float = CHUNK) -> bytes:
    """Return mono float32 audio at loudness ``level``."""
    count = int(RATE * seconds)
    samples = np.full(count, level, dtype=np.float32)
    samples[1::2] *= -1
    return samples.tobytes()


@pytest.fixture()
def listener(monkeypatch: object, qapp: object) -> MicrophoneListener:
    """Return a listener that runs work at once and has no real microphone."""
    transcriber = FakeTranscriber()
    listener = MicrophoneListener(
        transcriber=transcriber,
        endpointer_factory=lambda: SpeechEndpointer(speech_rms=0.01),
        start_thread=lambda work: work(),
    )

    def open_microphone() -> bool:
        listener._format = ("float", 1, RATE, 4)
        listener.opened = getattr(listener, "opened", 0) + 1
        return True

    monkeypatch.setattr(listener, "_open_microphone", open_microphone)
    return listener


def _speak(listener: MicrophoneListener, seconds: float = 1.0) -> None:
    """Feed a spoken response followed by enough quiet to end it."""
    for _ in range(round(seconds / CHUNK)):
        listener.audio_received(_chunk(LOUD))
    for _ in range(round(1.0 / CHUNK)):
        listener.audio_received(_chunk(QUIET))


def test_listener_transcribes_a_response_with_the_hint(
    listener: MicrophoneListener,
) -> None:
    """Once the player stops talking, the recording is transcribed."""
    heard = []
    listener.listen(heard.append, "Tchaikovsky")
    _speak(listener)

    assert heard == ["Who is Tchaikovsky?"]
    [(audio, hint)] = listener.transcriber.calls
    assert hint == "Tchaikovsky"
    assert audio.dtype == np.float32
    assert len(audio) >= RATE  # At least the second of speech.
    listener.audio_received(_chunk(LOUD))
    assert heard == ["Who is Tchaikovsky?"]


def test_listener_reports_silence_without_transcribing(
    listener: MicrophoneListener,
) -> None:
    """Saying nothing in time is reported as an empty response."""
    heard = []
    listener.listen(heard.append)
    for _ in range(round(5.0 / CHUNK)):
        listener.audio_received(_chunk(QUIET))
    assert heard == [""]
    assert listener.transcriber.calls == []


def test_cancelled_listening_reports_nothing(listener: MicrophoneListener) -> None:
    """Audio after cancel() is ignored."""
    heard = []
    listener.listen(heard.append)
    listener.cancel()
    _speak(listener)
    assert heard == []


def test_transcript_for_an_earlier_response_is_dropped(
    listener: MicrophoneListener,
) -> None:
    """A slow transcription that lands after listening moved on is ignored."""
    pending = []
    listener.start_thread = pending.append
    first, second = [], []
    listener.listen(first.append)
    _speak(listener)
    listener.listen(second.append)

    pending[0]()

    assert first == []
    assert second == []


def test_failed_transcription_reports_nothing(listener: MicrophoneListener) -> None:
    """When Whisper fails, the host rules instead."""
    listener.transcriber.error = RuntimeError("model broke")
    heard = []
    listener.listen(heard.append)
    _speak(listener)
    assert heard == []


def test_prepare_loads_the_model_once(listener: MicrophoneListener) -> None:
    """Turning the robot host on starts loading the model, just once."""
    listener.prepare()
    listener.prepare()
    assert listener.transcriber.load_calls == 1


def test_failed_model_load_is_logged_not_raised(
    listener: MicrophoneListener,
) -> None:
    """A download that fails doesn't crash the app."""

    def fail() -> None:
        raise OSError("offline")

    listener.transcriber.load = fail
    listener.prepare()
