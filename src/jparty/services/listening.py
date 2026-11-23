"""Hear a player's spoken response with the microphone and Whisper.

``MicrophoneListener`` is the robot host's listener (see
``jparty.domain.robot_host``). It records from the computer's default
microphone until the player has finished speaking, then transcribes the
recording with Whisper (the ``faster-whisper`` package) on a worker thread.

Speech-to-text is optional: install it with the ``robot`` extra
(``uv sync --extra robot`` or ``pip install "jparty[robot]"``). Without it, or
without a microphone, :func:`listening_unavailable_reason` says why and
:func:`create_microphone_listener` returns ``None``.

The first time it is used, Whisper downloads its model (about 140 MB for
``base.en``) and keeps it in the Hugging Face cache.
"""

import importlib.util
import logging
import os
import sys
import threading
from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal

WHISPER_MODEL_ENV = "JPARTY_WHISPER_MODEL"
DEFAULT_WHISPER_MODEL = "base.en"
WHISPER_SAMPLE_RATE = 16000

SPEECH_RMS_ENV = "JPARTY_SPEECH_RMS"
# Loudness (RMS of samples scaled to -1..1) above which the microphone is
# taken to be hearing speech: -40 dBFS. Set low on purpose, since missing a
# response rules it wrong, while hearing noise as speech only means
# recording until the time limit and Whisper's own filter hearing nothing.
# Change it with JPARTY_SPEECH_RMS; each response's loudness is logged.
SPEECH_RMS = 0.01
# Once speech has started, audio this far below the loudest part counts as
# quiet, so the response can end in a noisy room.
END_FRACTION_OF_PEAK = 0.15
# Loud audio must last this long to count as the start of speech, so a
# click or a bump doesn't.
SPEECH_START_SECONDS = 0.1
# A player who says nothing for this long after buzzing has not answered.
START_TIMEOUT_SECONDS = 5.0
# This much quiet after speech means the player has finished.
END_SILENCE_SECONDS = 0.8
# No response is recorded for longer than this.
MAX_RESPONSE_SECONDS = 8.0
# Chunk durations add up with rounding error; a limit this close is reached.
_TIME_TOLERANCE = 1e-6


def speech_rms_threshold(env: object = None) -> float:
    """Return the speech threshold, from ``JPARTY_SPEECH_RMS`` if set."""
    value = (os.environ if env is None else env).get(SPEECH_RMS_ENV, "")
    try:
        threshold = float(value)
    except ValueError:
        return SPEECH_RMS
    return threshold if threshold > 0 else SPEECH_RMS


class SpeechEndpointer:
    """Decide from loudness alone when a spoken response starts and ends.

    Feed it the loudness of each chunk of audio as it arrives. It reports
    ``"waiting"`` until speech starts, ``"speaking"`` while it goes on, and
    ``"done"`` once the player has finished, has said nothing in time, or
    has spoken for the maximum length.

    Speech starts when audio stays above ``speech_rms`` for
    ``start_seconds``. It ends after ``end_silence`` of audio below both
    ``speech_rms`` and a fraction of the loudest audio heard. So in a noisy
    room, where the noise alone is above ``speech_rms``, a response still
    ends once the player stops talking.
    """

    def __init__(
        self,
        speech_rms: float | None = None,
        start_seconds: float = SPEECH_START_SECONDS,
        start_timeout: float = START_TIMEOUT_SECONDS,
        end_silence: float = END_SILENCE_SECONDS,
        max_length: float = MAX_RESPONSE_SECONDS,
        end_fraction: float = END_FRACTION_OF_PEAK,
    ) -> None:
        """Store the thresholds; see the module constants for the defaults."""
        self.speech_rms = speech_rms if speech_rms else speech_rms_threshold()
        self.start_seconds = start_seconds
        self.start_timeout = start_timeout
        self.end_silence = end_silence
        self.max_length = max_length
        self.end_fraction = end_fraction
        self.heard_speech = False
        self.state = "waiting"
        self.peak = 0.0
        self.quietest = None
        self._elapsed = 0.0
        self._loud = 0.0
        self._quiet = 0.0

    def feed(self, rms: float, seconds: float) -> str:
        """Take one chunk's loudness and duration; return the new state."""
        if self.state == "done":
            return self.state
        self._elapsed += seconds
        self.peak = max(self.peak, rms)
        self.quietest = rms if self.quietest is None else min(self.quietest, rms)
        if not self.heard_speech:
            self._loud = self._loud + seconds if rms >= self.speech_rms else 0.0
            if self._loud >= self.start_seconds - _TIME_TOLERANCE:
                self.heard_speech = True
                self.state = "speaking"
        else:
            quiet_below = max(self.speech_rms, self.peak * self.end_fraction)
            self._quiet = self._quiet + seconds if rms < quiet_below else 0.0
        elapsed = self._elapsed + _TIME_TOLERANCE
        if elapsed >= self.max_length:
            self.state = "done"
        elif self.heard_speech and self._quiet + _TIME_TOLERANCE >= self.end_silence:
            self.state = "done"
        elif not self.heard_speech and elapsed >= self.start_timeout:
            self.state = "done"
        return self.state


def pcm_to_mono(raw: bytes, sample_format: str, channels: int) -> object:
    """Convert raw PCM bytes to mono float samples between -1 and 1.

    Args:
        raw: Interleaved PCM data.
        sample_format: ``"uint8"``, ``"int16"``, ``"int32"`` or ``"float"``.
        channels: Number of interleaved channels.

    Returns:
        A 1-D ``numpy.float32`` array.
    """
    import numpy as np

    dtype, offset, scale = {
        "uint8": (np.uint8, 128.0, 128.0),
        "int16": (np.int16, 0.0, 32768.0),
        "int32": (np.int32, 0.0, 2147483648.0),
        "float": (np.float32, 0.0, 1.0),
    }[sample_format]
    samples = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    samples = (samples - offset) / scale
    channels = max(1, channels)
    usable = len(samples) - len(samples) % channels
    return samples[:usable].reshape(-1, channels).mean(axis=1)


def resample(samples: object, rate: int, target: int = WHISPER_SAMPLE_RATE) -> object:
    """Resample mono ``samples`` from ``rate`` to ``target`` Hz.

    Linear interpolation is plenty for speech recognition.
    """
    import numpy as np

    if rate == target or len(samples) == 0:
        return samples.astype(np.float32)
    count = int(round(len(samples) * target / rate))
    positions = np.linspace(0, len(samples) - 1, count)
    return np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)


def rms(samples: object) -> float:
    """Return the root-mean-square loudness of float ``samples``."""
    import numpy as np

    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


class WhisperTranscriber:
    """Turn recorded speech into text with a local Whisper model."""

    def __init__(self, model_name: str | None = None) -> None:
        """Store which model to use; it is loaded by :meth:`load`.

        Args:
            model_name: A ``faster-whisper`` model name. Defaults to
                ``JPARTY_WHISPER_MODEL`` or ``base.en``.
        """
        self.model_name = (
            model_name or os.environ.get(WHISPER_MODEL_ENV) or DEFAULT_WHISPER_MODEL
        )
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load the model, downloading it the first time. Blocks; slow."""
        with self._lock:
            self._load_locked()

    def _load_locked(self) -> None:
        """Load the model while holding the lock."""
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        logging.info("Loading Whisper model %s", self.model_name)
        self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        logging.info("Whisper model %s ready", self.model_name)

    def transcribe(self, audio: object, hint: str = "") -> str:
        """Return what was said in 16 kHz mono ``audio``. Blocks.

        Args:
            audio: ``numpy.float32`` samples at 16 kHz.
            hint: Words likely to be said, such as the clue's correct
                response. Whisper then spells names like "Tchaikovsky"
                right instead of guessing.
        """
        with self._lock:
            self._load_locked()
            segments, _info = self._model.transcribe(
                audio,
                language="en",
                beam_size=1,
                initial_prompt=hint or None,
                condition_on_previous_text=False,
                # Noise transcribes to nothing rather than made-up words.
                vad_filter=True,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()


def _start_thread(work: Callable[[], None]) -> None:
    """Run ``work`` on a daemon thread."""
    threading.Thread(target=work, daemon=True).start()


_SAMPLE_FORMATS = {
    "UInt8": "uint8",
    "Int16": "int16",
    "Int32": "int32",
    "Float": "float",
}


class MicrophoneListener(QObject):
    """Record one spoken response at a time and transcribe it.

    It meets the listener contract in ``jparty.domain.robot_host``:
    ``listen(on_heard, hint)`` and ``cancel()``, with ``on_heard`` called on
    the Qt thread.
    """

    _transcribed = pyqtSignal(int, object)

    def __init__(
        self,
        transcriber: object = None,
        device: object = None,
        endpointer_factory: Callable[[], SpeechEndpointer] = SpeechEndpointer,
        start_thread: Callable[[Callable[[], None]], None] = _start_thread,
    ) -> None:
        """Store the pieces; nothing is opened until :meth:`listen`.

        Args:
            transcriber: Has ``load()`` and ``transcribe(audio, hint)``.
                Defaults to :class:`WhisperTranscriber`.
            device: A ``QAudioDevice``. Defaults to the default microphone.
            endpointer_factory: Builds the speech start/end detector.
            start_thread: Runs slow work off the Qt thread.
        """
        super().__init__()
        self.transcriber = transcriber or WhisperTranscriber()
        self.device = device
        self.endpointer_factory = endpointer_factory
        self.start_thread = start_thread
        self._prepared = False
        self._token = 0
        self._on_heard = None
        self._source = None
        self._io = None
        self._chunks = []
        self._endpointer = None
        self._format = None
        self._hint = ""
        self._transcribed.connect(self._deliver)

    def prepare(self) -> None:
        """Start loading the model in the background, once."""
        if self._prepared:
            return
        self._prepared = True

        def load() -> None:
            try:
                self.transcriber.load()
            except Exception:
                logging.exception("Could not load the Whisper model")

        self.start_thread(load)

    def listen(self, on_heard: Callable[[object], None], hint: str = "") -> None:
        """Record until the player finishes, then report what they said.

        Args:
            on_heard: Called on the Qt thread with the transcript, or with
                ``""`` when the player said nothing in time. Not called if
                listening is cancelled, or if recording or transcription
                fails (the host then rules).
            hint: Words likely to be said, passed on to the transcriber.
        """
        self.cancel()
        self._on_heard = on_heard
        self._hint = hint
        self._chunks = []
        self._endpointer = self.endpointer_factory()
        if not self._open_microphone():
            self._on_heard = None

    def cancel(self) -> None:
        """Stop recording and drop any transcription still on its way."""
        self._token += 1
        self._on_heard = None
        self._close_microphone()

    def _open_microphone(self) -> bool:
        """Start recording from the microphone; ``False`` if it can't."""
        from PyQt6.QtMultimedia import QAudioSource, QMediaDevices

        device = self.device or QMediaDevices.defaultAudioInput()
        if device.isNull():
            logging.error("No microphone to listen with")
            return False
        audio_format = device.preferredFormat()
        sample_format = _SAMPLE_FORMATS.get(audio_format.sampleFormat().name)
        if sample_format is None:
            logging.error("Unsupported microphone format %s", audio_format)
            return False
        self._format = (
            sample_format,
            audio_format.channelCount(),
            audio_format.sampleRate(),
            audio_format.bytesPerFrame(),
        )
        self._source = QAudioSource(device, audio_format, self)
        self._io = self._source.start()
        if self._io is None:
            logging.error("Could not start the microphone")
            self._close_microphone()
            return False
        self._io.readyRead.connect(self._read)
        return True

    def _close_microphone(self) -> None:
        """Stop recording, if recording."""
        if self._source is not None:
            self._source.stop()
            self._source.deleteLater()
        self._source = None
        self._io = None

    def _read(self) -> None:
        """Take the audio that has arrived and check whether speech ended."""
        if self._io is None:
            return
        raw = bytes(self._io.readAll())
        if raw:
            self.audio_received(raw)

    def audio_received(self, raw: bytes) -> None:
        """Handle one chunk of raw microphone audio.

        Public so tests can feed audio without a microphone.
        """
        if self._on_heard is None or self._endpointer is None:
            return
        sample_format, channels, rate, _bytes_per_frame = self._format
        samples = pcm_to_mono(raw, sample_format, channels)
        self._chunks.append(samples)
        state = self._endpointer.feed(rms(samples), len(samples) / rate)
        if state == "done":
            self._finish()

    def _finish(self) -> None:
        """Stop recording and transcribe what was heard."""
        import numpy as np

        self._close_microphone()
        endpointer = self._endpointer
        logging.info(
            "Response loudness: peak %.4f, quietest %.4f, speech threshold %.4f",
            endpointer.peak,
            endpointer.quietest or 0.0,
            endpointer.speech_rms,
        )
        if not endpointer.heard_speech:
            logging.info("Robot host heard no response")
            self._deliver(self._token, "")
            return
        _sample_format, _channels, rate, _bytes_per_frame = self._format
        audio = resample(np.concatenate(self._chunks), rate)
        self._chunks = []
        token, hint = self._token, self._hint

        def transcribe() -> None:
            try:
                text = self.transcriber.transcribe(audio, hint)
            except Exception:
                logging.exception("Could not transcribe the response")
                return
            self._transcribed.emit(token, text)

        self.start_thread(transcribe)

    def _deliver(self, token: int, text: object) -> None:
        """Pass a transcript on, unless listening has moved on since."""
        if token != self._token or self._on_heard is None:
            return
        on_heard = self._on_heard
        self._on_heard = None
        on_heard(text)


def listening_unavailable_reason() -> str | None:
    """Return why the robot host can't listen, or ``None`` if it can."""
    if getattr(sys, "frozen", False):
        return (
            "The packaged app doesn't include speech-to-text yet. Run JParty "
            'from source with the "robot" extra to use the robot host.'
        )
    if importlib.util.find_spec("faster_whisper") is None:
        return (
            "Speech-to-text isn't installed. Install JParty with the "
            '"robot" extra to use the robot host.'
        )
    from PyQt6.QtMultimedia import QMediaDevices

    if QMediaDevices.defaultAudioInput().isNull():
        return "No microphone was found."
    return None


def create_microphone_listener() -> MicrophoneListener | None:
    """Return a listener for the default microphone, or ``None`` if unusable."""
    reason = listening_unavailable_reason()
    if reason is not None:
        logging.info("Robot host can't listen: %s", reason)
        return None
    return MicrophoneListener()
