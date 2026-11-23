"""Read clues aloud and open responses once a clue has been read.

This is the first piece of a host-less game: the computer reads each clue,
and opening responses after a regular clue no longer needs the host's Space.
The host still picks clues, takes Daily Double wagers and rules on answers.

The reader acts through the same keystroke events the host uses, so the host
can always step in first. Pressing Space before a clue has been read opens
responses as usual and stops the reading.
"""

from collections.abc import Callable

from jparty.services.speech import Speaker, speakable_text


class ClueReader:
    """Read the active clue aloud at the points where a host would."""

    def __init__(self, game: object, speaker: object = None) -> None:
        """Store the game and the speaker used to read aloud.

        Args:
            game: Owning ``Game``.
            speaker: ``Speaker``-like object with ``say`` and ``stop``.
                Defaults to the system's text-to-speech voice.
        """
        self.game = game
        self.speaker = speaker if speaker is not None else Speaker()
        self.enabled = False

    def set_enabled(self, enabled: bool) -> None:
        """Turn reading aloud on or off, stopping any reading in progress.

        Turning it on starts the voice right away, while the host is still
        setting up, rather than on the first clue.
        """
        self.enabled = bool(enabled)
        if self.enabled:
            self.speaker.prepare()
        else:
            self.stop()

    def stop(self) -> None:
        """Stop reading at once."""
        self.speaker.stop()

    def clue_shown(self, question: object) -> None:
        """Read a clue, then open responses if they are still closed.

        Callers don't call this for a Daily Double, which is read after the
        wager instead; see :meth:`daily_double_shown`.
        """
        if not self.enabled:
            return
        self._say(
            question.text,
            lambda: self._trigger_for(question, "OPEN_RESPONSES"),
        )

    def daily_double_shown(
        self, question: object, on_finished: Callable[[], None] | None = None
    ) -> None:
        """Read a Daily Double clue once its wager is in.

        Only the player who found it answers, so there is no buzzer to open.

        Args:
            question: The Daily Double clue.
            on_finished: Called once the clue has been read; not called when
                it isn't read.
        """
        if self.enabled:
            self._say(question.text, on_finished)

    def final_shown(self, question: object) -> None:
        """Read the Final clue, then start the think music."""
        if not self.enabled:
            return
        self._say(
            question.text,
            lambda: self._trigger_for(question, "FINAL_OPEN_RESPONSES"),
        )

    def answer_revealed(
        self, question: object, on_finished: Callable[[], None] | None = None
    ) -> None:
        """Read the correct response the host just revealed.

        Args:
            question: The clue whose answer was revealed.
            on_finished: Called once the answer has been read; not called when
                it isn't read.
        """
        if not self.enabled:
            return
        answer = speakable_text(question.answer)
        if answer:
            self.speaker.say(f"The correct response is {answer}.", on_finished)

    def say(self, text: str) -> None:
        """Read a short line such as a ruling, cutting off any reading."""
        if self.enabled:
            self._say(text)

    def _say(self, text: object, on_finished: object = None) -> None:
        """Read ``text`` once cleaned up, if anything is left to read."""
        self.speaker.say(speakable_text(text), on_finished)

    def _trigger_for(self, question: object, ident: str) -> None:
        """Fire event ``ident`` if ``question`` is still the clue on screen.

        The event is only fired while it is active, so a host who already
        pressed Space, or a clue already left behind, is not acted on twice.
        """
        if self.game.active_question is question:
            self.game.keystroke_manager.trigger(ident)
