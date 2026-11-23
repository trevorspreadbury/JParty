"""Read text aloud with the computer's text-to-speech voices.

``Speaker`` wraps Qt's ``QTextToSpeech`` so the game can say a clue and hear
back once it has been read in full. ``speakable_text`` turns clue and answer
text from J-Archive or a Google Sheet into something a voice reads cleanly.
"""

import html
import logging
import re
from collections.abc import Callable

from PyQt6.QtCore import QObject

_TAG = re.compile(r"<[^>]+>")
_BLANK = re.compile(r"_{2,}")
_BRACKETS = re.compile(r"[()\[\]{}]")
_ESCAPED_QUOTE = re.compile(r"\\(['\"])")
_SPACES = re.compile(r"\s+")


def speakable_text(text: object) -> str:
    """Return ``text`` cleaned up for a text-to-speech voice.

    HTML tags and entities are removed, backslash-escaped quotes are
    unescaped, a run of underscores (a fill-in-the-blank clue) is read as
    "blank", and brackets are dropped but their words kept, so the answer
    ``(Abraham) Lincoln`` is read as "Abraham Lincoln".

    Args:
        text: Clue or answer text. ``None`` reads as an empty string.

    Returns:
        The cleaned text, which is empty when there is nothing to read.
    """
    if text is None:
        return ""
    cleaned = html.unescape(_TAG.sub(" ", str(text)))
    cleaned = _ESCAPED_QUOTE.sub(r"\1", cleaned)
    cleaned = _BLANK.sub(" blank ", cleaned)
    cleaned = _BRACKETS.sub(" ", cleaned)
    return _SPACES.sub(" ", cleaned).strip()


def _default_engine_factory() -> object:
    """Create Qt's text-to-speech engine with the platform's default voice."""
    from PyQt6.QtTextToSpeech import QTextToSpeech

    return QTextToSpeech()


class Speaker(QObject):
    """Say one piece of text at a time and report when it has been read.

    The Qt engine is created the first time it is needed, so a game that
    never reads aloud never loads it. When the engine can't be created or
    reports an error, nothing is read and no callback runs. That way a game
    falls back to the host pressing Space rather than moving on unread.
    """

    def __init__(self, engine_factory: Callable[[], object] | None = None) -> None:
        """Store how to build the engine without building it yet.

        Args:
            engine_factory: Returns a ``QTextToSpeech``-like object. Defaults
                to Qt's engine; tests pass a fake.
        """
        super().__init__()
        self._engine_factory = engine_factory or _default_engine_factory
        self._engine = None
        self._engine_failed = False
        self._on_finished = None
        # True once the engine has started on the current text. An engine can
        # report Ready for the text that stop() cut off after say() has queued
        # new text, and that must not count as the new text being finished.
        self._started = False

    @property
    def available(self) -> bool:
        """Whether text can be read aloud, creating the engine if needed."""
        return self._ensure_engine() is not None

    def prepare(self) -> bool:
        """Create the engine now, so the first reading doesn't wait for it.

        Returns:
            Whether text can be read aloud.
        """
        return self.available

    def _ensure_engine(self) -> object | None:
        """Return the engine, creating it on first use; ``None`` if unusable."""
        if self._engine is not None or self._engine_failed:
            return self._engine
        try:
            engine = self._engine_factory()
        except Exception:
            logging.exception("Could not start text-to-speech")
            self._engine_failed = True
            return None
        from PyQt6.QtTextToSpeech import QTextToSpeech

        if engine.state() == QTextToSpeech.State.Error:
            logging.error("Text-to-speech is unavailable: %s", engine.errorString())
            self._engine_failed = True
            return None
        engine.stateChanged.connect(self._on_state_changed)
        self._engine = engine
        logging.info("Text-to-speech engine ready")
        return engine

    def say(self, text: str, on_finished: Callable[[], None] | None = None) -> bool:
        """Start reading ``text`` aloud, cutting off anything still being read.

        Args:
            text: What to read. Blank text is not read.
            on_finished: Called once the whole text has been read. It is not
                called when the reading is stopped or fails.

        Returns:
            ``True`` when reading started; ``False`` when the text was blank or
            text-to-speech is unavailable.
        """
        self.stop()
        if not text or not text.strip():
            return False
        engine = self._ensure_engine()
        if engine is None:
            return False
        self._on_finished = on_finished
        self._started = False
        engine.say(text)
        return True

    def stop(self) -> None:
        """Stop reading at once, dropping the pending callback."""
        self._on_finished = None
        self._started = False
        if self._engine is not None:
            self._engine.stop()

    def _on_state_changed(self, state: object) -> None:
        """Run the pending callback when the engine finishes the current text.

        Args:
            state: The engine's new ``QTextToSpeech.State``.
        """
        from PyQt6.QtTextToSpeech import QTextToSpeech

        if state == QTextToSpeech.State.Speaking:
            self._started = True
            return
        if state == QTextToSpeech.State.Error:
            logging.error("Text-to-speech failed: %s", self._engine.errorString())
            self._on_finished = None
            self._started = False
            return
        if state != QTextToSpeech.State.Ready or not self._started:
            return
        callback = self._on_finished
        self._on_finished = None
        self._started = False
        if callback is not None:
            callback()
