"""Extracted gameplay collaborators used by ``Game``."""

from __future__ import annotations

import logging
import time

import simpleaudio as sa
from PyQt6.QtWidgets import QApplication

from jparty.app.config import EARLY_BUZZ_PENALTY, FJTIME, QUESTIONTIME
from jparty.domain.models import BuzzAttempt, FinalBoard
from jparty.domain.state import MANUAL_SCORE_ADJUSTMENT_TYPE, build_end_game_summary
from jparty.ui.widgets.common import resource_path


class PlayerStateBroadcaster:
    """Own lectern-facing player-state updates for one game session."""

    def __init__(self, game: object) -> None:
        """Store the owning game facade."""
        self.game = game

    def update_player(
        self, player: object, buzzed: bool = False, show_final_answer: bool = False
    ) -> None:
        """Build and emit the latest lectern state for one player."""
        if self.game.buzzer_controller:
            state_dict = self.game.buzzer_controller.get_player_state_dict(player)
            state_dict["buzzed"] = buzzed
            state_dict["active"] = (
                self.game.answering_player is player
                if self.game.answering_player
                else False
            )
            if not show_final_answer:
                state_dict["finalanswer"] = None
            self.game.lectern_update_trigger.emit(player.player_number, state_dict)

    def update_all(self) -> None:
        """Refresh every connected lectern payload."""
        if self.game.buzzer_controller:
            for player in self.game.players:
                self.update_player(player, buzzed=False)

    def set_score(self, player: object, score: object) -> None:
        """Update score displays and lectern state for one player."""
        player.score = score
        self.game.dc.player_widget(player).update_score()
        self.update_player(player)


class ScoreRecorder:
    """Own score mutations and history-entry persistence for one game."""

    def __init__(self, game: object) -> None:
        """Store the owning game facade."""
        self.game = game

    def append_answer_attempt(
        self, player: object, answer_correct: bool, score_before: int, score_after: int
    ) -> None:
        """Append one judged answer attempt for the active clue."""
        if player is None:
            return
        self.game._answer_attempts.append(
            {
                "player_index": player.player_number,
                "answer_correct": answer_correct,
                "timestamp": time.time(),
                "score_before": score_before,
                "score_after": score_after,
            }
        )

    def apply_manual_score_override(self, player: object, new_score: int) -> bool:
        """Log and apply a host-entered manual player score override."""
        if player.score == new_score:
            return False
        history_entry = {
            "type": MANUAL_SCORE_ADJUSTMENT_TYPE,
            "player_index": player.player_number,
            "timestamp": time.time(),
            "score_before": player.score,
            "score_after": new_score,
            "new_score": new_score,
        }
        self.game._append_history_entry(history_entry)
        self.game.player_state_broadcaster.set_score(player, new_score)
        self.game._refresh_score_edit_controls()
        return True

    def flush_question_history(self) -> None:
        """Persist the active clue's history and clear per-question buffers."""
        if not self.game._game_state_dir:
            self.game._initialize_game_state_dir()
        if not self.game._game_state_dir or not self.game._current_question_history:
            logging.error("No game state directory or current question history")
            return
        question_index = self.game._get_question_index()
        if not question_index:
            logging.error("No question index")
            return
        if not self.game.active_question.dd and not isinstance(
            self.game.current_round, FinalBoard
        ):
            buzz_phases = self.game._classify_buzz_phases()
        else:
            buzz_phases = []
        entry = {
            "question_index": list(question_index),
            "question_number": self.game.question_number,
            "round_index": self.game.data.rounds.index(self.game.current_round)
            if self.game.data and self.game.current_round
            else None,
            "category": self.game.active_question.category
            if self.game.active_question
            else "",
            "value": self.game.active_question.value
            if self.game.active_question
            else -1,
            "is_daily_double": self.game.active_question.dd
            if self.game.active_question
            else False,
            "buzz_phases": buzz_phases,
            "answer_attempts": self.game._answer_attempts.copy(),
            "completed_at": time.time(),
        }
        self.game._append_history_entry(entry)
        self.game._current_question_history = None
        self.game._all_buzz_attempts = []
        self.game._answer_attempts = []
        self.game._open_responses_times = []
        self.game._successful_buzz_times = []
        self.game._question_start_time = None
        self.game._refresh_score_edit_controls()


class ClueFlow:
    """Own standard clue lifecycle behavior."""

    def __init__(self, game: object) -> None:
        """Store the owning game facade."""
        self.game = game

    def open_responses(self) -> None:
        """Open the buzz window for the active clue."""
        self.game.responses_open_time = time.time()
        self.game._open_responses_times.append(self.game.responses_open_time)
        self.game.dc.borders.lights(True)
        self.game.accepting_responses = True
        if not self.game.timer:
            self.game.timer = self.game._question_timer_factory(
                QUESTIONTIME, self.game.stumped
            )
        self.game.timer.start()

    def close_responses(self) -> None:
        """Close the current buzz window without clearing clue state."""
        self.game.timer.pause()
        self.game.accepting_responses = False
        self.game.dc.borders.lights(True)

    def buzz(self, i_player: object) -> None:
        """Handle one player's buzz attempt."""
        if not isinstance(i_player, int) or not 0 <= i_player < len(self.game.players):
            logging.warning("Ignoring buzz for invalid player index: %s", i_player)
            return
        player = self.game.players[i_player]
        if self.game.active_question is None:
            self.game.dc.player_widget(player).buzz_hint()
            return
        if player in self.game.previous_answerers:
            return
        current_time = time.time()
        question_index = self.game._get_question_index()
        early_buzz = False
        successful_buzz = False
        in_timeout = False
        if not self.game.accepting_responses:
            if not self.game.previous_answerers:
                self.game.early_buzzes.add(i_player)
                early_buzz = True
                logging.info("Early buzz recorded: player %s", i_player)
        elif (
            i_player in self.game.early_buzzes
            and current_time - self.game.responses_open_time < EARLY_BUZZ_PENALTY
        ):
            in_timeout = True
            logging.info("Early buzz timeout: player %s ignored", i_player)
        else:
            self.game.accepting_responses = False
            self.game.timer.pause()
            self.game.previous_answerers.add(player)
            self.game.answering_player = player
            successful_buzz = True
            logging.info("Successful buzz recorded: player %s", i_player)
            self.game.dc.player_widget(player).run_lights()
            self.game.player_state_broadcaster.update_player(player, buzzed=True)
            self.game.keystroke_manager.activate("CORRECT_ANSWER", "INCORRECT_ANSWER")
            self.game.dc.borders.lights(False)
            self.game._successful_buzz_times.append(current_time)
        self.game._all_buzz_attempts.append(
            BuzzAttempt(
                player_index=i_player,
                question_index=question_index,
                timestamp=current_time,
                is_early=early_buzz,
                is_success=successful_buzz,
                is_rebound=False,
                in_timeout=in_timeout,
            )
        )

    def answer_given(self) -> None:
        """Clear answer-resolution UI state after a judgment."""
        self.game.keystroke_manager.deactivate("CORRECT_ANSWER", "INCORRECT_ANSWER")
        self.game.dc.player_widget(self.game.answering_player).stop_lights()
        answering_player = self.game.answering_player
        self.game.answering_player = None
        if answering_player:
            self.game.player_state_broadcaster.update_player(
                answering_player, buzzed=False
            )

    def back_to_board(self) -> None:
        """Return from a clue view to the board and advance question tracking."""
        logging.info("back_to_board")
        self.game._awaiting_stumped_answer_reveal = False
        self.game.score_recorder.flush_question_history()
        self.game.question_number += 1
        self.game.dc.hide_question()
        self.game.timer = None
        self.game.active_question.complete = True
        self.game.active_question = None
        self.game.previous_answerers = set()
        self.game.early_buzzes = set()
        self.game.responses_open_time = None
        if self.game.answering_player:
            self.game.player_state_broadcaster.update_player(
                self.game.answering_player, buzzed=False
            )
        self.game.answering_player = None
        self.game.player_state_broadcaster.update_all()
        if all(q.complete for q in self.game.current_round.questions):
            logging.info("NEXT ROUND")
            self.game.keystroke_manager.activate("NEXT_ROUND")
        self.game._refresh_score_edit_controls()

    def correct_answer(self) -> None:
        """Apply a correct ruling to the active player's clue response."""
        old_score = self.game.answering_player.score
        new_score = old_score + self.game.active_question.value
        self.game.score_recorder.append_answer_attempt(
            self.game.answering_player, True, old_score, new_score
        )
        if self.game.timer:
            self.game.timer.cancel()
        self.game.player_state_broadcaster.set_score(
            self.game.answering_player, new_score
        )
        self.game.dc.borders.lights(False)
        self.answer_given()
        self.back_to_board()

    def incorrect_answer(self) -> None:
        """Apply an incorrect ruling to the active player's clue response."""
        old_score = self.game.answering_player.score
        new_score = old_score - self.game.active_question.value
        self.game.score_recorder.append_answer_attempt(
            self.game.answering_player, False, old_score, new_score
        )
        self.game.player_state_broadcaster.set_score(
            self.game.answering_player, new_score
        )
        self.answer_given()
        if self.game.active_question.dd:
            self.back_to_board()
        else:
            self.open_responses()
            self.game.timer.resume()

    def stumped(self) -> None:
        """Handle a clue expiring without a correct response."""
        self.game.accepting_responses = False
        self.game.song_player.stumped()
        self.game.dc.borders.flash()
        if self.game.reveal_answers_after_triple_stumper_enabled():
            self.game._awaiting_stumped_answer_reveal = True
            self.game.keystroke_manager.activate("REVEAL_STUMPED_ANSWER")
            return
        self.game._awaiting_stumped_answer_reveal = False
        self.game.keystroke_manager.activate("BACK_TO_BOARD")

    def reveal_stumped_answer(self) -> None:
        """Reveal the current clue answer before returning to the board."""
        if (
            not self.game._awaiting_stumped_answer_reveal
            or self.game.active_question is None
        ):
            return
        self.game._awaiting_stumped_answer_reveal = False
        self.game.dc.question_widget.reveal_answer()
        self.game.keystroke_manager.activate("BACK_TO_BOARD")

    def load_question(self, q: object) -> None:
        """Load a clue into the displays and initialize per-question tracking."""
        self.game.active_question = q
        self.game._awaiting_stumped_answer_reveal = False
        self.game._question_start_time = time.time()
        self.game._all_buzz_attempts = []
        self.game._answer_attempts = []
        self.game._open_responses_times = []
        self.game._successful_buzz_times = []
        question_index = self.game._get_question_index()
        if question_index:
            self.game._current_question_history = {
                "question_index": list(question_index),
                "question_number": self.game.question_number,
                "round_index": self.game.data.rounds.index(self.game.current_round)
                if self.game.data and self.game.current_round
                else None,
                "category": q.category,
                "value": q.value,
                "is_daily_double": q.dd,
            }
        if q.dd:
            logging.info("Daily double!")
            sa.WaveObject.from_wave_file(resource_path("dd.wav")).play()
            self.game.soliciting_player = True
        else:
            self.game.keystroke_manager.activate("OPEN_RESPONSES")
        self.game.dc.load_question(q)
        self.game.dc.remove_card(q)
        self.game._refresh_score_edit_controls()


class FinalJeopardyFlow:
    """Own Final Jeopardy lifecycle behavior."""

    def __init__(self, game: object) -> None:
        """Store the owning game facade."""
        self.game = game

    def open_responses(self) -> None:
        """Open Final Jeopardy answer entry and start the music timer."""
        self.game._all_buzz_attempts = []
        self.game._answer_attempts = []
        self.game._open_responses_times = []
        self.game._successful_buzz_times = []
        question_index = self.game._get_question_index()
        if question_index:
            self.game._current_question_history = {
                "question_index": list(question_index),
                "question_number": self.game.question_number,
                "round_index": self.game.data.rounds.index(self.game.current_round)
                if self.game.data and self.game.current_round
                else None,
                "category": self.game.active_question.category
                if self.game.active_question
                else "",
                "value": self.game.active_question.value
                if self.game.active_question
                else -1,
                "is_daily_double": False,
            }
        self.game.dc.borders.lights(True)
        self.game.buzzer_controller.prompt_answers()
        self.game.song_player.final()
        self.game.timer = self.game._question_timer_factory(
            FJTIME, self.game.final_finished_song
        )
        self.game.timer.start()

    def next_player(self) -> None:
        """Advance Final Jeopardy judging to the next player."""
        for player in self.game.players:
            self.game.dc.player_widget(player).set_lights(False)
        if self.game._judgement_round == 0:
            self.game.dc.load_final_judgement()
            self.game._sorted_players = sorted(
                self.game.players, key=lambda player: player.score
            )
        elif self.game._judgement_round == len(self.game.players):
            self.game.end_game()
            return
        self.game.answering_player = self.game._sorted_players[
            self.game._judgement_round
        ]
        self.game.dc.player_widget(self.game.answering_player).set_lights(True)
        self.game.dc.final_window.guess_label.setText("")
        self.game.dc.final_window.wager_label.setText("")
        self.game.player_state_broadcaster.update_player(
            self.game.answering_player, show_final_answer=False
        )
        self.game.keystroke_manager.activate("FINAL_SHOW_ANSWER")

    def show_answer(self) -> None:
        """Reveal the current player's Final Jeopardy response."""
        answer = self.game.answering_player.finalanswer
        if answer == "":
            answer = "________"
        self.game.dc.final_window.guess_label.setText(answer)
        self.game.player_state_broadcaster.update_player(
            self.game.answering_player, show_final_answer=True
        )
        self.game.keystroke_manager.activate(
            "FINAL_CORRECT_ANSWER", "FINAL_INCORRECT_ANSWER"
        )

    def correct_answer(self) -> None:
        """Apply a correct Final Jeopardy ruling to the active player."""
        answering_player = self.game.answering_player
        old_score = answering_player.score
        new_score = old_score + answering_player.wager
        self.game.score_recorder.append_answer_attempt(
            answering_player, True, old_score, new_score
        )
        self.game.player_state_broadcaster.set_score(answering_player, new_score)
        self.judgement_given()

    def incorrect_answer(self) -> None:
        """Apply an incorrect Final Jeopardy ruling to the active player."""
        answering_player = self.game.answering_player
        old_score = answering_player.score
        new_score = old_score - answering_player.wager
        self.game.score_recorder.append_answer_attempt(
            answering_player, False, old_score, new_score
        )
        self.game.player_state_broadcaster.set_score(answering_player, new_score)
        self.judgement_given()

    def judgement_given(self) -> None:
        """Finalize one Final Jeopardy judgment and ready the next step."""
        self.game.keystroke_manager.deactivate(
            "FINAL_CORRECT_ANSWER", "FINAL_INCORRECT_ANSWER"
        )
        self.game.dc.final_window.wager_label.setText(
            str(self.game.answering_player.wager)
        )
        self.game.keystroke_manager.activate("FINAL_NEXT_PLAYER")
        self.game._judgement_round += 1

    def finished_song(self) -> None:
        """Handle the end of the Final Jeopardy think music."""
        logging.info("Final song ended")
        self.game.toolate_trigger.emit()
        self.game.accepting_responses = False
        self.game.dc.borders.flash()
        self.game.keystroke_manager.activate("FINAL_NEXT_PLAYER")
        self.game._refresh_score_edit_controls()

    def end_game(self) -> None:
        """Determine winners and move toward score graphs."""
        if (
            isinstance(self.game.current_round, FinalBoard)
            and self.game.active_question is not None
            and self.game._current_question_history
        ):
            self.game.score_recorder.flush_question_history()
        top_score = max(player.score for player in self.game.players)
        winners = [player for player in self.game.players if player.score == top_score]
        for winner in winners:
            self.game.dc.player_widget(winner).set_lights(True)
        if len(winners) == 1:
            self.game.dc.final_window.show_winner(winners[0])
        else:
            self.game.dc.final_window.show_tie()
        logging.info("Game over!")
        self.game.keystroke_manager.activate("GENERATE_GRAPHS")

    def generate_final_score_graphs(self) -> None:
        """Build and show the end-of-game audience summary screen."""
        self.game.keystroke_manager.deactivate("GENERATE_GRAPHS")
        summary = build_end_game_summary(self.game)
        QApplication.processEvents()
        self.game.main_display.load_end_game_summary(summary)
        self.game.keystroke_manager.activate("CLOSE_GAME")
