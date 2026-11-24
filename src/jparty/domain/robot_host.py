"""Run a game without a host: listen, rule, and move the game on.

``ClueReader`` reads a clue and opens responses. Then ``RobotHost`` takes over:
when a player buzzes it listens to their response, has it judged, and rules
on it with the same key events the host uses (``CORRECT_ANSWER`` and
``INCORRECT_ANSWER``). When nobody gets a clue, it reads the correct response
and returns to the board.

The host can always step in. An arrow key pressed while the robot is
listening rules as usual and the robot stops listening. When the judge is
unsure, nothing is ruled and the host decides.

Speech-to-text is not part of this module. It is the injected ``listener``
(``jparty.services.listening.MicrophoneListener`` in the app), which must
provide:

- ``listen(on_heard, hint)``: start listening for one response, then call
  ``on_heard(transcript)`` on the Qt thread with what was heard, or with
  ``None`` or ``""`` when nothing was said before its time limit. ``hint`` is
  the clue's correct response, so names are spelled the way the judge
  expects.
- ``cancel()``: stop listening; ``on_heard`` must then not be called.
- ``prepare()`` (optional): get ready to listen, for example by loading a
  speech model, without blocking.

Without a listener the robot host can't be turned on.

It also moves the game on between clues, each step after a short pause and
through the host's own key events, so a host who presses the key first is
never overridden:

- the next round once a board is cleared (``NEXT_ROUND``);
- Final Jeopardy: it reads the category, opens the clue once every wager is
  in (or after ``FINAL_WAGER_TIMEOUT_MS``, counting a missing wager as $0),
  then reveals and rules on each player's typed answer in turn with the same
  judge, waiting for the host when the judge is unsure;
- the end-of-game summary.

Players pick clues and wager on Daily Doubles from their phones (see
``Game.phones_run_board``). A tiebreaker, which starts by asking for a game,
is still the host's, as are tiebreaker clues nobody gets.
"""

import logging
from collections.abc import Callable

from PyQt6.QtCore import QTimer

from jparty.domain.judging import Ruling, judge_response
from jparty.services.speech import speakable_text

# How long a clue nobody got stays on screen before the board returns, when
# the correct response is not revealed.
STUMPED_PAUSE_MS = 2500
# Pause after a cleared board before the next round.
ROUND_PAUSE_MS = 3000
# The end of the round is announced this long after the board is cleared,
# so the ruling on the last clue ("Correct.") isn't cut off.
ROUND_ANNOUNCE_DELAY_MS = 1000
# Pause between steps of Final Jeopardy (opening the clue, revealing each
# answer, moving to the next player) and before the end-of-game summary.
FINAL_STEP_PAUSE_MS = 2500
# Final opens without a wager that hasn't come in by then, counted as $0.
FINAL_WAGER_TIMEOUT_MS = 60_000


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
        # Bumped by every scheduled step, and when the robot host is turned
        # off, so only the latest step can fire. A step left over from before
        # the host moved things on is dropped.
        self._step = 0

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
        if self.enabled:
            prepare = getattr(self.listener, "prepare", None)
            if prepare is not None:
                prepare()
        else:
            self.stop()
            self._step += 1
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

    def round_over(self) -> None:
        """Move to the next round after a cleared board, following a pause."""
        if not self.enabled:
            return
        self._advance_later("NEXT_ROUND", ROUND_PAUSE_MS)
        step = self._step

        def announce() -> None:
            if step == self._step and self.enabled:
                self.game.clue_reader.say("That's the end of the round.")

        self.later(ROUND_ANNOUNCE_DELAY_MS, announce)

    def final_started(self, board: object) -> None:
        """Read the Final category and stop waiting for wagers in time.

        Args:
            board: The ``FinalBoard`` being played.
        """
        if not self.enabled:
            return
        category = speakable_text(getattr(board, "category", ""))
        if category:
            self.game.clue_reader.say(
                f"The Final Jeopardy category is {category}. Make your wagers."
            )
        self._advance_later("FORCE_OPEN_FINAL", FINAL_WAGER_TIMEOUT_MS)

    def final_wagers_in(self) -> None:
        """Show the Final clue once every wager is in."""
        if self.enabled:
            self._advance_later("OPEN_FINAL", FINAL_STEP_PAUSE_MS)

    def step_ready(self, ident: str) -> None:
        """Take the next step, event ``ident``, after a pause.

        Called when the game activates ``FINAL_NEXT_PLAYER``,
        ``FINAL_SHOW_ANSWER`` or ``GENERATE_GRAPHS``, or ``NEXT_ROUND`` again
        after a tournament's host code.
        """
        if self.enabled:
            self._advance_later(ident, FINAL_STEP_PAUSE_MS)

    def final_answer_shown(self, question: object, player: object) -> None:
        """Rule on a player's typed Final answer once it is shown.

        A blank answer is wrong. When the judge is unsure, the host rules.
        """
        if not self.enabled:
            return
        answer = str(getattr(player, "finalanswer", "") or "").strip()
        ruling = self.judge(question, answer) if answer else Ruling.INCORRECT
        logging.info(
            "Robot host ruled %s's Final answer %r: %s", player, answer, ruling
        )
        if ruling is Ruling.UNSURE:
            return
        self.game.score_recorder.pending_details = {"ruled_by": "robot"}
        if ruling is Ruling.CORRECT:
            self.game.keystroke_manager.trigger("FINAL_CORRECT_ANSWER")
            self.game.clue_reader.say("Correct.")
        else:
            self.game.keystroke_manager.trigger("FINAL_INCORRECT_ANSWER")
            self.game.clue_reader.say("No.")

    def _advance_later(self, ident: str, delay_ms: int) -> None:
        """Fire event ``ident`` after ``delay_ms``, if it is still the next step.

        It fires only if no later step was scheduled meanwhile, the robot
        host is still on, the same round is being played, and the event is
        still waiting for its key.
        """
        self._step += 1
        step = self._step
        round_ = self.game.current_round

        def advance() -> None:
            if (
                step == self._step
                and self.enabled
                and self.game.current_round is round_
            ):
                self.game.keystroke_manager.trigger(ident)

        self.later(delay_ms, advance)

    def _listen_to(self, player: object) -> None:
        """Start listening for ``player``'s response to the clue on screen."""
        # Don't talk over the player, or record the robot's own voice.
        self.game.clue_reader.stop()
        self.stop()
        token = self._token
        question = self.game.active_question
        logging.info("Robot host listening to %s", player)
        self.listener.listen(
            lambda transcript: self._heard(token, question, player, transcript),
            speakable_text(getattr(question, "answer", "")),
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
