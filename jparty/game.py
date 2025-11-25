from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import QInputDialog, QApplication


import threading
import time
from dataclasses import dataclass, asdict
from itertools import zip_longest
import os
import sys
import simpleaudio as sa
from collections.abc import Iterable
import logging
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt

from jparty.utils import SongPlayer, resource_path, CompoundObject
from jparty.constants import FJTIME, QUESTIONTIME, REPO_ROOT, EARLY_BUZZ_PENALTY, GAME_STATES_DIR


MAX_PLAYERS = 6
index_to_key = {
    0: Qt.Key.Key_Q,
    1: Qt.Key.Key_W,
    2: Qt.Key.Key_E,
    3: Qt.Key.Key_R,
    4: Qt.Key.Key_T,
    5: Qt.Key.Key_Y,
}

class QuestionTimer(object):
    def __init__(self, interval, f, *args, **kwargs):
        super().__init__()
        self.f = f
        self.args = args
        self.kwargs = kwargs
        self.interval = interval
        self.__thread = None
        self.__start_time = None
        self.__elapsed_time = 0

    def run(self, i):
        thread = self.__thread
        time.sleep(i)
        if thread == self.__thread:
            self.f(*self.args, **self.kwargs)

    def start(self):
        """wrapper for resume"""
        self.resume()

    def cancel(self):
        """wrapper for pause"""
        self.pause()

    def pause(self):
        self.__thread = None
        self.__elapsed_time += time.time() - self.__start_time

    def resume(self):
        self.__thread = threading.Thread(
            target=self.run, args=(self.interval - self.__elapsed_time,)
        )
        self.__thread.start()
        self.__start_time = time.time()


@dataclass
class KeystrokeEvent:
    key: int
    func: callable
    hint_setter: callable = None
    active: bool = False
    persistent: bool = False
    func_args: int = None


class KeystrokeManager(object):
    def __init__(self):
        super().__init__()
        self.__events = {}

    def addEvent(
        self, ident, key, func, hint_setter=None, active=False, persistent=False, func_args=None
    ):
        self.__events[ident] = KeystrokeEvent(
            key, func, hint_setter, active, persistent, func_args
        )

    def call(self, key):
        """this is split in to two for loops so one execution doesnt cause another event to trigger"""
        events_to_call = []
        for ident, event in self.__events.items():
            if event.active and event.key == key:
                logging.info(f"Calling {ident}")
                events_to_call.append(event)
                if not event.persistent:
                    self._deactivate(ident)

        for event in events_to_call:
            if event.func_args is not None:
                event.func(event.func_args)
            else:
                event.func()

    def _activate(self, ident):
        logging.info(f"Activating {ident}")
        e = self.__events[ident]
        e.active = True
        e.hint_setter(True)
        if e.hint_setter:
            e.hint_setter(True)

    def _deactivate(self, ident):
        e = self.__events[ident]
        e.active = False
        if e.hint_setter:
            e.hint_setter(False)

    def activate(self, *idents):
        if isinstance(idents, Iterable):
            for ident in idents:
                self._activate(ident)
        else:
            self._activate(idents)

    def deactivate(self, *idents):
        if isinstance(idents, Iterable):
            for ident in idents:
                self._deactivate(ident)
        else:
            self._deactivate(idents)


@dataclass
class Question:
    index: tuple
    text: str
    answer: str
    category: str
    value: int = -1
    dd: bool = False
    complete: bool = False
    image: bool = False
    image_url: str = None
    actual_results: str = None


@dataclass
class BuzzAttempt:
    player_index: int
    question_index: tuple  # (round_index, question.index)
    timestamp: float
    is_early: bool
    is_success: bool  # Did this buzz result in them answering?
    is_rebound: bool
    in_timeout: bool  # Was this buzz unsuccessful due to being in timeout?


class Board(object):
    size = (6, 5)

    def __init__(self, categories, questions, dj=False):
        self.categories = categories
        self.dj = dj
        if not questions is None:
            self.questions = questions
        else:
            self.questions = []

    def get_question(self, i, j):
        for q in self.questions:
            if q.index == (i, j):
                return q
        return None

    def complete(self):
        return len(self.questions) == 30


class FinalBoard(Board):
    size = (1, 1)

    def __init__(self, category, question):
        super().__init__([category], [question], dj=False)
        self.category = category
        self.question = question

    def complete(self):
        return len(self.questions) == 1


@dataclass
class GameData:
    rounds: list
    date: str
    comments: str


class Game(QObject):
    buzz_trigger = pyqtSignal(int)
    new_player_trigger = pyqtSignal()
    wager_trigger = pyqtSignal(int, int)
    toolate_trigger = pyqtSignal()
    lectern_update_trigger = pyqtSignal(int, dict)

    def __init__(self):
        super().__init__()

        self.host_display = None
        self.main_display = None
        self.dc = None
        self.question_number = 1
        self.data = None

        self.current_round = None
        self.players = []
        self.original_players = {}

        self.active_question = None
        self.accepting_responses = False
        self.answering_player = None
        self.previous_answerers = set()
        self.timer = None
        self.soliciting_player = False  # part of selecting who found a daily double
        
        self.early_buzzes = set()
        self.responses_open_time = None

        self.song_player = SongPlayer()
        self.__judgement_round = 0
        self.__sorted_players = None

        self.buzzer_controller = None

        self.keystroke_manager = KeystrokeManager()

        self.keystroke_manager.addEvent(
            "CORRECT_ANSWER", Qt.Key.Key_Left, self.correct_answer, self.arrowhints
        )
        self.keystroke_manager.addEvent(
            "INCORRECT_ANSWER", Qt.Key.Key_Right, self.incorrect_answer, self.arrowhints
        )
        self.keystroke_manager.addEvent(
            "BACK_TO_BOARD", Qt.Key.Key_Space, self.back_to_board, self.spacehints
        )
        self.keystroke_manager.addEvent(
            "OPEN_RESPONSES", Qt.Key.Key_Space, self.open_responses, self.spacehints
        )
        self.keystroke_manager.addEvent(
            "NEXT_ROUND", Qt.Key.Key_Space, self.next_round, self.spacehints
        )
        self.keystroke_manager.addEvent(
            "OPEN_FINAL", Qt.Key.Key_Space, self.open_final, self.spacehints
        )
        self.keystroke_manager.addEvent(
            "CLOSE_GAME", Qt.Key.Key_Space, self.close_game, self.spacehints
        )
        self.keystroke_manager.addEvent(
            "GENERATE_GRAPHS", Qt.Key.Key_Space, self.generate_final_score_graphs, self.spacehints
        )
        self.keystroke_manager.addEvent(
            "FINAL_OPEN_RESPONSES",
            Qt.Key.Key_Space,
            self.final_open_responses,
            self.spacehints,
        )
        self.keystroke_manager.addEvent(
            "FINAL_NEXT_PLAYER",
            Qt.Key.Key_Space,
            self.final_next_player,
            self.spacehints,
        )
        self.keystroke_manager.addEvent(
            "FINAL_SHOW_ANSWER",
            Qt.Key.Key_Space,
            self.final_show_answer,
            self.spacehints,
        )
        self.keystroke_manager.addEvent(
            "FINAL_CORRECT_ANSWER",
            Qt.Key.Key_Left,
            self.final_correct_answer,
            self.arrowhints,
        )
        self.keystroke_manager.addEvent(
            "FINAL_INCORRECT_ANSWER",
            Qt.Key.Key_Right,
            self.final_incorrect_answer,
            self.arrowhints,
        )
        for player_index in range(MAX_PLAYERS):
            self.keystroke_manager.addEvent(
                f"BUZZED_{player_index}",
                index_to_key[player_index],
                self.buzz,
                lambda x: x, #nonsense
                active=True,
                persistent=True,
                func_args=player_index
            )
        self.wager_trigger.connect(self.wager)
        self.buzz_trigger.connect(self.buzz)
        self.new_player_trigger.connect(self.new_player)
        self.toolate_trigger.connect(self.__toolate)
        self.lectern_update_trigger.connect(self.__broadcast_lectern_update)

        # Game state tracking
        self._game_state_dir = None
        self._current_question_history = None
        self._all_buzz_attempts = []  # All buzz attempts for current question
        self._answer_attempts = []  # All answer attempts for current question
        self._question_start_time = None
        self._open_responses_times = []  # List of times when open_responses() was called
        self._successful_buzz_times = []  # List of times when successful buzzes occurred
        self._game_started_at = None

    def startable(self):
        return self.valid_game() and len(self.buzzer_controller.connected_players) > 0

    def begin(self):
        self.song_player.play(repeat=True)

    def start_game(self):
        self.current_round = self.data.rounds[0]
        self.dc.hide_welcome_widgets()
        self.dc.board_widget.load_round(self.current_round)
        self.buzzer_controller.accepting_players = False
        self.song_player.stop()
        self._game_started_at = time.time()
        self._initialize_game_state_dir()
        self._save_general_state()

    def setDisplays(self, host_display, main_display):
        self.host_display = host_display
        self.main_display = main_display
        self.dc = CompoundObject(host_display, main_display)

    def setBuzzerController(self, controller):
        self.buzzer_controller = controller

    def _get_question_index(self):
        """Generate unique question identifier: (round_index, question.index)"""
        if not self.active_question or not self.data:
            return None
        try:
            round_index = self.data.rounds.index(self.current_round)
            return (round_index, self.active_question.index)
        except (ValueError, AttributeError):
            return None

    def _initialize_game_state_dir(self):
        """Initialize game state directory based on game_id"""
        game_id = os.environ.get("JPARTY_GAME_ID")
        if not game_id:
            return
        self._game_state_dir = GAME_STATES_DIR / str(game_id)
        self._game_state_dir.mkdir(parents=True, exist_ok=True)

    def _get_current_game_state(self):
        """Get current general game state as dict"""
        game_id = os.environ.get("JPARTY_GAME_ID", "")
        current_time = time.time()
        return {
            "game_id": game_id,
            "players": [{"name": p.name, "player_number": p.player_number} for p in self.players],
            "started_at": self._game_started_at or current_time,
            "last_updated": current_time,
        }

    def _save_general_state(self):
        """Write/update general.json with current game state"""
        if not self._game_state_dir:
            self._initialize_game_state_dir()
        if not self._game_state_dir:
            return
        
        state = self._get_current_game_state()
        general_file = self._game_state_dir / "general.json"
        
        try:
            with open(general_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving general state: {e}")

    def _classify_buzz_phases(self):
        """Classify all buzz attempts into phases based on timing rules"""
        if not self._all_buzz_attempts:
            return []
        if not self._open_responses_times:
            logging.error("No open responses times found after question completed.")
            return []
        current_time = time.time()
        
        # classify buzzes that are this later/early as part of the previous/next phase
        # (since if someone loses a buzzer race by .01 seconds, they were part of the phase
        # before responses were closed. And if someone loses a buzzer race because they buzzed
        # too soon, they were part of the next phase.)
        BUZZER_PHASE_PADDING = 1 # seconds
        # first phase starts at the question start time
        # subsequent phases start at the time responses were opened
        phase_start_times = [self._question_start_time] + self._open_responses_times[1:]
        # if last answer was correct, the phase ends at the time the 
        #   correct answer was given
        # otherwise, the last time questions were opened, they never closed. 
        #   Current time is used to fill missing last successful buzz time.
        phase_boundaries = []
        for phase_start_time,  successful_buzz_time in zip_longest(phase_start_times,  self._successful_buzz_times, fillvalue=current_time):
            phase_boundaries.append(
                (
                    max(phase_start_time - BUZZER_PHASE_PADDING, self._question_start_time),
                    min(successful_buzz_time + BUZZER_PHASE_PADDING, current_time)
                )
            )
        phases = []
        for phase_start_time, phase_end_time in phase_boundaries:
            current_phase = {
                "phase_type": "main" if phase_start_time == self._question_start_time else "rebound",
                "start_time": phase_start_time,
                "end_time": phase_end_time,
                "buzz_attempts": [
                    asdict(b) for b in self._all_buzz_attempts 
                    if b.timestamp >= phase_start_time and b.timestamp < phase_end_time
                ]
            }
            phases.append(current_phase)
        
        return phases

    def _flush_question_history(self):
        """Append question history to JSONL file, clear current question state"""
        if not self._game_state_dir:
            self._initialize_game_state_dir()
        if not self._game_state_dir or not self._current_question_history:
            logging.error("No game state directory or current question history")
            return
        
        question_index = self._get_question_index()
        if not question_index:
            logging.error("No question index")
            return
        
        # Classify buzz attempts if question was not a daily double
        if not self.active_question.dd:
            buzz_phases = self._classify_buzz_phases()
        else:
            buzz_phases = []

        # Build question history entry
        entry = {
            "question_index": list(question_index),
            "question_number": self.question_number,
            "round_index": self.data.rounds.index(self.current_round) if self.data and self.current_round else None,
            "category": self.active_question.category if self.active_question else "",
            "value": self.active_question.value if self.active_question else -1,
            "is_daily_double": self.active_question.dd if self.active_question else False,
            "buzz_phases": buzz_phases,
            "answer_attempts": self._answer_attempts.copy(),
            "completed_at": time.time(),
        }
        
        history_file = self._game_state_dir / "question_history.jsonl"
        
        try:
            with open(history_file, "a") as f:
                json.dump(entry, f)
                f.write("\n")
        except Exception as e:
            logging.error(f"Error appending question history: {e}")

        # Reset question tracking
        self._current_question_history = None
        self._all_buzz_attempts = []
        self._answer_attempts = []
        self._open_responses_times = []
        self._successful_buzz_times = []
        self._question_start_time = None

    def arrowhints(self, val):
        self.host_display.borders.arrowhints(val)

    def spacehints(self, val):
        self.host_display.borders.spacehints(val)

    def new_player(self):
        self.players = self.buzzer_controller.connected_players
        self._update_player_numbers()
        self.dc.scoreboard.refresh_players()
        self.host_display.welcome_widget.check_start()
        for player in self.players:
            self._update_lectern_for_player(player)

    def remove_player(self, player):
        self.players.remove(player)
        player.waiter.close()
        self._update_player_numbers()
        self.dc.scoreboard.refresh_players()
        self.host_display.welcome_widget.check_start()
        for player in self.players:
            self._update_lectern_for_player(player)

    def move_player_up(self, player):
        if player not in self.players:
            return
        index = self.players.index(player)
        if index > 0:
            self.players[index], self.players[index - 1] = self.players[index - 1], self.players[index]
            self._update_player_numbers()
            self.dc.scoreboard.refresh_players()
            self._update_all_lecterns()

    def move_player_down(self, player):
        if player not in self.players:
            return
        index = self.players.index(player)
        if index < len(self.players) - 1:
            self.players[index], self.players[index + 1] = self.players[index + 1], self.players[index]
            self._update_player_numbers()
            self.dc.scoreboard.refresh_players()
            self._update_all_lecterns()

    def _update_player_numbers(self):
        """Update player_number and key for all players based on their position in the list."""
        for i, player in enumerate(self.players):
            player.player_number = i
            player.key = index_to_key[i]

    def _update_all_lecterns(self):
        """Update all connected lecterns to show the correct player for their position."""
        if self.buzzer_controller:
            for player in self.players:
                self._update_lectern_for_player(player, buzzed=False)

    def valid_game(self):
        return self.data is not None and all(b.complete() for b in self.data.rounds)

    def open_responses(self):
        self.responses_open_time = time.time()
        self._open_responses_times.append(self.responses_open_time)
        self.dc.borders.lights(True)
        self.accepting_responses = True

        if not self.timer:
            self.timer = QuestionTimer(QUESTIONTIME, self.stumped)

        self.timer.start()

    def close_responses(self):
        self.timer.pause()
        self.accepting_responses = False
        self.dc.borders.lights(True)

    def keyboard_buzz(self):
        self.buzz(0)


    def buzz(self, i_player):
        player = self.players[i_player]
        # unlogged buzzes
        if self.active_question is None:
            # question is not loaded. Consider this a test buzz. Light main display
            # and move on.
            self.dc.player_widget(player).buzz_hint()
            return
        elif player in self.previous_answerers:
            # player cannot buzz again. Errant/illegal buzz. Ignore.
            return

        current_time = time.time()
        question_index = self._get_question_index()
        early_buzz = False
        successful_buzz = False
        in_timeout = False

        # If there is an active question but responses are not open,
        # the player has buzzed too early.
        if not self.accepting_responses:
            if not self.previous_answerers:
                # early buzz -- no answer given yet
                self.early_buzzes.add(i_player)
                early_buzz = True
                logging.info(f"Early buzz recorded: player {i_player}")
        # If the player previously buzzed too early and the penalt
        # period has not expired, the player is in timeout.
        elif (
            i_player in self.early_buzzes and 
            (current_time - self.responses_open_time) < EARLY_BUZZ_PENALTY
        ):
            in_timeout = True
            logging.info(
                f"Early buzz timeout: player {i_player} ignored"
            )
        # successful buzz
        else:
            self.accepting_responses = False
            self.timer.pause()
            self.previous_answerers.add(player)
            self.answering_player = player
            successful_buzz = True
            logging.info(f"Successful buzz recorded: player {i_player}")
            self.dc.player_widget(player).run_lights()
            self._update_lectern_for_player(player, buzzed=True)
            self.keystroke_manager.activate("CORRECT_ANSWER", "INCORRECT_ANSWER")
            self.dc.borders.lights(False)
            self._successful_buzz_times.append(current_time)
        
        self._all_buzz_attempts.append(BuzzAttempt(
            player_index=i_player,
            question_index=question_index,
            timestamp=current_time,
            is_early=early_buzz,
            is_success=successful_buzz,
            is_rebound=False,
            in_timeout=in_timeout
        ))
            

    def answer_given(self):
        self.keystroke_manager.deactivate("CORRECT_ANSWER", "INCORRECT_ANSWER")
        self.dc.player_widget(self.answering_player).stop_lights()
        answering_player = self.answering_player
        self.answering_player = None
        if answering_player:
            self._update_lectern_for_player(answering_player, buzzed=False)

    def update_original_player_scores(self):
        buzzed_players = []
        for player, score in self.active_question.actual_results:
            if player not in self.original_players:
                self.original_players[player] = [0 for _ in range(self.question_number)]
            buzzed_players.append(player)
            self.original_players[player].append(score + self.original_players[player][-1])
        for player in self.original_players:
            if player not in buzzed_players:
                self.original_players[player].append(self.original_players[player][-1])

    def back_to_board(self):
        logging.info("back_to_board")
        
        # Save question history before incrementing question number
        self._flush_question_history()
        
        self.question_number += 1
        self.dc.hide_question()
        self.timer = None
        self.active_question.complete = True
        self.update_original_player_scores()
        self.active_question = None
        self.previous_answerers = set()
        self.early_buzzes = set()
        self.responses_open_time = None
        
        
        # Clear active state for all players on lecterns
        if self.answering_player:
            self._update_lectern_for_player(self.answering_player, buzzed=False)
        self.answering_player = None
        # Update all players to ensure lecterns show correct state
        for player in self.players:
            self._update_lectern_for_player(player, buzzed=False)
        
        if all(q.complete for q in self.current_round.questions):
            logging.info("NEXT ROUND")
            self.keystroke_manager.activate("NEXT_ROUND")

    def accept_image(self):
        logging.info("Proposed question image accepted")
        self.load_question(self.active_question)

    def no_image_needed(self):
        logging.info("No image needed for question")
        self.active_question.image = False
        self.active_question.image_url = None
        self.load_question(self.active_question)

    def next_round(self):
        logging.info("next round")
        i = self.data.rounds.index(self.current_round)
        logging.info(f"ROUND {i}")
        self.current_round = self.data.rounds[i + 1]

        if isinstance(self.current_round, FinalBoard):
            self.dc.load_final(self.current_round.question)
            self.active_question = self.current_round.question
            self.update_original_player_scores()
            self.start_final()
        else:
            self.dc.board_widget.load_round(self.current_round)

    def start_final(self):
        logging.info("start final")
        for player in self.players:
            self.dc.player_widget(player).set_lights(True)

        self.buzzer_controller.open_wagers()

    def wager(self, i_player, amount):
        player = self.players[i_player]
        player.wager = amount
        self.dc.player_widget(player).set_lights(False)
        logging.info(f"{player} wagered {amount}")
        if all(p.wager is not None for p in self.players):
            self.host_display.question_widget.hint_label.setText(
                "Press space to show clue!"
            )
            self.keystroke_manager.activate("OPEN_FINAL")

    def answer(self, player, guess):
        player.finalanswer = guess
        logging.info(f"{player} guessed {guess}")

    def final_open_responses(self):
        self.dc.borders.lights(True)
        self.buzzer_controller.prompt_answers()

        self.song_player.final()

        self.timer = QuestionTimer(FJTIME, self.final_finished_song)
        self.timer.start()

    def final_next_player(self):
        for p in self.players:
            self.dc.player_widget(p).set_lights(False)

        if self.__judgement_round == 0:
            self.dc.load_final_judgement()
            self.__sorted_players = sorted(self.players, key=lambda x: x.score)

        elif self.__judgement_round == len(self.players):
            self.end_game()
            return

        self.answering_player = self.__sorted_players[self.__judgement_round]

        self.dc.player_widget(self.answering_player).set_lights(True)

        self.dc.final_window.guess_label.setText("")
        self.dc.final_window.wager_label.setText("")
        
        # Update lectern to show player name (answer will be shown in final_show_answer)
        self._update_lectern_for_player(self.answering_player, show_final_answer=False)

        self.keystroke_manager.activate("FINAL_SHOW_ANSWER")

    def final_show_answer(self):
        answer = self.answering_player.finalanswer
        if answer == "":
            answer = "________"

        self.dc.final_window.guess_label.setText(answer)
        # Update lectern to show final answer
        self._update_lectern_for_player(self.answering_player, show_final_answer=True)
        self.keystroke_manager.activate(
            "FINAL_CORRECT_ANSWER", "FINAL_INCORRECT_ANSWER"
        )

    def final_correct_answer(self):
        ap = self.answering_player
        new_score = ap.score + ap.wager
        ap.update_scores(self.question_number, new_score)
        self.set_score(ap, ap.score + ap.wager)
        self.final_judgement_given()

    def final_incorrect_answer(self):
        ap = self.answering_player
        new_score = ap.score - ap.wager
        ap.update_scores(self.question_number, new_score)
        self.set_score(ap, new_score)
        self.final_judgement_given()

    def final_judgement_given(self):
        self.keystroke_manager.deactivate(
            "FINAL_CORRECT_ANSWER", "FINAL_INCORRECT_ANSWER"
        )
        self.dc.final_window.wager_label.setText(str(self.answering_player.wager))
        self.keystroke_manager.activate("FINAL_NEXT_PLAYER")
        self.__judgement_round += 1

    def final_finished_song(self):
        logging.info("Final song ended")
        self.toolate_trigger.emit()
        self.accepting_responses = False
        self.dc.borders.flash()
        self.keystroke_manager.activate("FINAL_NEXT_PLAYER")

    def end_game(self):
        top_score = max([p.score for p in self.players])
        winners = [p for p in self.players if p.score == top_score]
        for w in winners:
            self.dc.player_widget(w).set_lights(True)

        if len(winners) == 1:
            self.dc.final_window.show_winner(winners[0])
        else:
            self.dc.final_window.show_tie()

        # self.generate_final_score_graph()
        logging.info("Game over!")
        self.keystroke_manager.activate("GENERATE_GRAPHS")

    def generate_final_score_graphs(self):
        self.keystroke_manager.deactivate("GENERATE_GRAPHS")
        
        for player_set in ["original", "current", "all"]:
            self.generate_final_score_graph(player_set)
        
        # Ensure PyQt6 GUI is fully updated after all matplotlib operations
        QApplication.processEvents()
        
        self.dc.load_final_graphs()
        self.keystroke_manager.activate("CLOSE_GAME")

    def generate_final_score_graph(self, players):
        """create an image of score by question number"""
        current_player_data = {player.player_number : player.score_by_question for player in self.players}
        if players == "original":
            data = self.original_players
        elif players == "current":
            data = current_player_data
        elif players == "all":
            data = current_player_data | self.original_players
        
        game_id = os.environ["JPARTY_GAME_ID"]
        
        # Isolate matplotlib operations to prevent interference with PyQt6
        fig = None
        try:
            # Create matplotlib figure
            fig, ax = plt.subplots(figsize=(10, 6))
            
            # Plot each player's scores
            for player, scores in data.items():
                x_values = list(range(1, len(scores)+1))
                ax.plot(x_values, scores, marker='o', label=str(player), linewidth=2, markersize=6)
            
            ax.set_xlabel('Question Number', fontsize=12)
            ax.set_ylabel('Score', fontsize=12)
            ax.set_title(f'Game {game_id}:Player Scores', fontsize=14, fontweight='bold')
            ax.legend(loc='best')
            ax.grid(True, alpha=0.3)
            
            # Save the figure
            games_scores_dir = REPO_ROOT / "jparty" / "data" / "game_scores"
            games_scores_dir.mkdir(exist_ok=True)
            image_path = games_scores_dir / f"{game_id}-{players}.jpg"
            
            plt.tight_layout()
            fig.savefig(str(image_path), dpi=150, bbox_inches='tight')
        finally:
            # Always clean up matplotlib state
            if fig is not None:
                plt.close(fig)  # Close figure to free memory
            plt.close('all')  # Close all figures to ensure clean state
            # Ensure matplotlib doesn't interfere with PyQt6
            plt.ioff()  # Turn off interactive mode
        
        # Process PyQt6 events to ensure GUI stays responsive
        QApplication.processEvents()

    def close_game(self):
        self.buzzer_controller.restart()
        # Notify all lecterns that players are cleared
        if self.buzzer_controller:
            for player_number in list(self.buzzer_controller.lectern_connections.keys()):
                if player_number in self.buzzer_controller.lectern_connections:
                    try:
                        self.buzzer_controller.lectern_connections[player_number].send("NO_PLAYER", "")
                    except:
                        pass
        self.players = []
        self.original_players = {}
        self.question_number = 1
        self.active_question = None
        self.current_round = None
        self.answering_player = None
        self.timer = None
        self.data = None
        self.__judgement_round = 0
        self.early_buzzes = set()
        self.responses_open_time = None
        self.dc.restart()
        self.begin()

    def get_dd_wager(self, player):
        self.answering_player = player
        self.soliciting_player = False
        try:
            logging.info(f"Current round is: {self.current_round}")
            logging.info(f"Rounds are {self.data.rounds}")
            round_index = self.data.rounds.index(self.current_round)
        except:
            round_index = 1

        max_wager = max(
            self.answering_player.score,
            1000 if round_index == 0 else 2000)
        wager_res = QInputDialog.getInt(
            self.host_display,
            "Wager",
            f"How much do they wager? (min: 5, max: ${max_wager})",
            min=5,
            max=max_wager,
        )
        if not wager_res[1]:
            self.soliciting_player = True
            return False

        wager = wager_res[0]
        self.active_question.value = wager

        self.keystroke_manager.activate("CORRECT_ANSWER", "INCORRECT_ANSWER")
        self.dc.question_widget.show_question()

    def load_image_review_screen(self, q):
        self.active_question = q
        self.host_display.load_image_review_screen(q)


    def load_question(self, q):
        self.active_question = q
        # Initialize question tracking
        self._question_start_time = time.time()
        self._all_buzz_attempts = []
        self._answer_attempts = []
        self._open_responses_times = []
        self._successful_buzz_times = []
        
        # Initialize question history entry
        question_index = self._get_question_index()
        if question_index:
            self._current_question_history = {
                "question_index": list(question_index),
                "question_number": self.question_number,
                "round_index": self.data.rounds.index(self.current_round) if self.data and self.current_round else None,
                "category": q.category,
                "value": q.value,
                "is_daily_double": q.dd,
            }
        
        if q.dd:
            logging.info("Daily double!")
            wo = sa.WaveObject.from_wave_file(resource_path("dd.wav"))
            wo.play()
            self.soliciting_player = True
        else:
            self.keystroke_manager.activate("OPEN_RESPONSES")
        self.dc.load_question(q)
        self.dc.remove_card(q)

    def open_final(self):
        self.dc.question_widget.show_question()
        self.keystroke_manager.activate("FINAL_OPEN_RESPONSES")

    def correct_answer(self):
        old_score = self.answering_player.score
        new_score = old_score + self.active_question.value
        # Record answer attempt
        if self.answering_player:
            self._answer_attempts.append({
                "player_index": self.answering_player.player_number,
                "answer_correct": True,
                "timestamp": time.time(),
                "score_before": old_score,
                "score_after": new_score,
            })
        
        self.answering_player.update_scores(self.question_number, new_score)
        if self.timer:
            self.timer.cancel()

        self.set_score(
            self.answering_player,
            new_score,
        )
        self.dc.borders.lights(False)
        self.answer_given()
        self.back_to_board()

    def incorrect_answer(self):
        old_score = self.answering_player.score
        new_score = old_score - self.active_question.value
        # Record answer attempt
        if self.answering_player:
            self._answer_attempts.append({
                "player_index": self.answering_player.player_number,
                "answer_correct": False,
                "timestamp": time.time(),
                "score_before": old_score,
                "score_after": new_score,
            })
        self.answering_player.update_scores(self.question_number, new_score) 
        self.set_score(
            self.answering_player,
            new_score,
        )
        self.answer_given()
        if self.active_question.dd:
            self.back_to_board()
        else:
            self.open_responses()
            self.timer.resume()

    def stumped(self):
        self.accepting_responses = False
        sa.WaveObject.from_wave_file(resource_path("stumped.wav")).play()
        self.dc.borders.flash()
        self.keystroke_manager.activate("BACK_TO_BOARD")

    def __toolate(self):
        self.buzzer_controller.toolate()

    def __broadcast_lectern_update(self, player_number, state_dict):
        if self.buzzer_controller:
            self.buzzer_controller.broadcast_to_lecterns(player_number, state_dict)

    def _update_lectern_for_player(self, player, buzzed=False, show_final_answer=False):
        if self.buzzer_controller:
            state_dict = self.buzzer_controller.get_player_state_dict(player)
            state_dict["buzzed"] = buzzed
            state_dict["active"] = (self.answering_player is player) if self.answering_player else False
            # Only include finalanswer if we're showing it
            if not show_final_answer:
                state_dict["finalanswer"] = None
            self.lectern_update_trigger.emit(player.player_number, state_dict)

    def set_score(self, player, score):
        player.score = score
        self.dc.player_widget(player).update_score()
        self._update_lectern_for_player(player)

    def adjust_score(self, player):
        new_score, answered = QInputDialog.getInt(
            self.host_display,
            "Adjust Score",
            "Enter a new score:",
            value=player.score,
        )
        if answered:
            self.set_score(player, new_score)
        player.score_by_question[-1] = new_score

    def close(self):
        self.song_player.stop()
        QApplication.quit()


class Player(object):
    def __init__(self, name, waiter, player_number):
        self.name = name
        self.token = os.urandom(15)
        # score at index 0 is start of game, 1 after first question
        self.score_by_question = [0]
        self.score = 0
        self.waiter = waiter
        self.wager = None
        self.finalanswer = ""
        self.page = "buzz"
        self.player_number = player_number
        self.key = index_to_key[player_number]

    def __hash__(self):
        return int.from_bytes(self.token, sys.byteorder)

    def state(self):
        return {"page": self.page, "score": self.score}
    
    def update_scores(self, question_number, new_score):
        """update players score"""
        if (len(self.score_by_question)) == question_number:
            self.score_by_question.append(new_score)
        else:
            for _ in range(question_number - len(self.score_by_question)):
                self.score_by_question.append(self.score_by_question[-1])
            self.score_by_question.append(new_score)

