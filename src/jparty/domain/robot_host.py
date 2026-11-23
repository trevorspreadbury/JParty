"""Run the answer loop of a clue without a host: listen, rule, move on.

``ClueReader`` reads a clue and opens responses. Then ``RobotHost`` takes over:
when a player buzzes it listens to their response, has it judged, and rules
on it with the same key events the host uses (``CORRECT_ANSWER`` and
``INCORRECT_ANSWER``). When nobody gets a clue, it reads the correct response
and returns to the board.

The host can always step in. An arrow key pressed while the robot is
listening rules as usual and the robot stops listening. When the judge is
unsure, nothing is ruled and the host decides.

Speech-to-text is not part of this module. It is the injected ``listener``,
which must provide:

- ``listen(on_heard)``: start listening for one response, then call
  ``on_heard(transcript)`` on the Qt thread with what was heard, or with
  ``None`` or ``""`` when nothing was said before its time limit.
- ``cancel()``: stop listening; ``on_heard`` must then not be called.

Without a listener the robot host can't be turned on.

Daily Double wagers, picking clues, Final Jeopardy rulings and tiebreaker
clues nobody gets are still the host's.
"""

import logging
from collections.abc import Callable

from PyQt6.QtCore import QTimer

from jparty.domain.judging import Ruling, judge_response

# How long a clue nobody got stays on screen before the board returns, when
# the correct response is not revealed.
STUMPED_PAUSE_MS = 2500


def _qt_later(delay_ms: int, callback: Callable[[], None]) -> None:
    """Run ``callback`` on the Qt event loop after ``delay_ms``."""
    QTimer.singleShot(delay_ms, callback)


class RobotHost:
    """Listen to whoever buzzed, rule on the response and move the clue on."""

    def __init__(
        self,
        game: object,
        listener: object = None,
        judge: Callable[[object, str], Ruling] = judge_response,
        later: Callable[[int, Callable[[], None]], None] = _qt_later,
    ) -> None:
        """Store the game and the pieces the robot host works with.

        Args:
            game: Owning ``Game``.
            listener: Speech-to-text listener; see the module docstring.
                ``None`` means there is none yet.
            judge: Rules on ``(question, transcript)``.
            later: Runs a callback after a delay in milliseconds. Tests pass
                one that runs it at once.
        """
        self.game = game
        self.listener = listener
        self.judge = judge
        self.later = later
        self.enabled = False
        # Bumped whenever listening starts or stops, so a response heard for
        # an earlier buzz is recognised as stale and dropped.
        self._token = 0

    @property
    def available(self) -> bool:
        """Whether there is a listener, so the robot host can be turned on."""
        return self.listener is not None

    def set_enabled(self, enabled: bool) -> bool:
        """Turn the robot host on or off.

        Args:
            enabled: Whether the robot host should run the answer loop.

        Returns:
            Whether it is now on. Turning it on fails without a listener.
        """
        if enabled and not self.available:
            logging.warning("Robot host needs speech-to-text; it stays off")
            enabled = False
        self.enabled = bool(enabled)
        if not self.enabled:
            self.stop()
        return self.enabled

    def stop(self) -> None:
        """Stop listening and forget any response still on its way."""
        self._token += 1
        if self.listener is not None:
            self.listener.cancel()

    def buzz_accepted(self, player: object) -> None:
        """Listen to the player who just won the buzz."""
        if self.enabled:
            self._listen_to(player)

    def daily_double_read(self, question: object) -> None:
        """Listen to the Daily Double player once their clue has been read."""
        if (
            self.enabled
            and self.game.active_question is question
            and self.game.answering_player is not None
        ):
            self._listen_to(self.game.answering_player)

    def clue_stumped(self, question: object) -> None:
        """Move on from a clue nobody got.

        With the reveal option on, the correct response is revealed and read,
        and the board returns once it has been read (``answer_read``).
        Otherwise the board returns after a short pause.
        """
        if not self.enabled:
            return
        if self.game.keystroke_manager.trigger("REVEAL_STUMPED_ANSWER"):
            return
        self.later(
            STUMPED_PAUSE_MS, lambda: self._trigger_for(question, "BACK_TO_BOARD")
        )

    def answer_read(self, question: object) -> None:
        """Return to the board once a revealed answer has been read."""
        if self.enabled:
            self._trigger_for(question, "BACK_TO_BOARD")

    def _listen_to(self, player: object) -> None:
        """Start listening for ``player``'s response to the clue on screen."""
        # Don't talk over the player, or record the robot's own voice.
        self.game.clue_reader.stop()
        self.stop()
        token = self._token
        question = self.game.active_question
        logging.info("Robot host listening to %s", player)
        self.listener.listen(
            lambda transcript: self._heard(token, question, player, transcript)
        )

    def _heard(
        self, token: int, question: object, player: object, transcript: object
    ) -> None:
        """Rule on a response, unless it belongs to an earlier buzz.

        Saying nothing in time is a wrong response, as on the show.
        """
        if (
            token != self._token
            or self.game.active_question is not question
            or self.game.answering_player is not player
        ):
            logging.info("Ignoring a stale response from %s", player)
            return
        transcript = str(transcript or "").strip()
        ruling = self.judge(question, transcript) if transcript else Ruling.INCORRECT
        logging.info("Robot host heard %r from %s: %s", transcript, player, ruling)
        details = {"transcript": transcript}
        if ruling is Ruling.UNSURE:
            # The host's arrow key will record the transcript with its ruling.
            self.game.score_recorder.pending_details = details
            return
        details["ruled_by"] = "robot"
        self.game.score_recorder.pending_details = details
        if ruling is Ruling.CORRECT:
            self.game.keystroke_manager.trigger("CORRECT_ANSWER")
            self.game.clue_reader.say("Correct.")
        else:
            self.game.keystroke_manager.trigger("INCORRECT_ANSWER")
            self.game.clue_reader.say("No.")

    def _trigger_for(self, question: object, ident: str) -> None:
        """Fire event ``ident`` if ``question`` is still the clue on screen."""
        if self.game.active_question is question:
            self.game.keystroke_manager.trigger(ident)
