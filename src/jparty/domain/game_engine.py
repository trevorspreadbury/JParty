import json
import logging
import os
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import simpleaudio as sa
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QInputDialog, QApplication

matplotlib.use('Agg')  # Use non-interactive backend

from jparty.app.config import EARLY_BUZZ_PENALTY, FJTIME, QUESTIONTIME
from jparty.app.paths import GAME_SCORES_DIR, GAME_STATES_DIR
from jparty.domain.input import MAX_PLAYERS, KeystrokeManager, QuestionTimer, index_to_key
from jparty.domain.models import Board, BuzzAttempt, FinalBoard, GameData, Player, Question
from jparty.domain.state import (
    classify_buzz_phases,
    get_current_game_state,
    load_general_state,
    load_question_history,
    reconstruct_score_history,
    save_general_state,
)
from jparty.ui.widgets.common import CompoundObject, SongPlayer, resource_path


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
        self._resume_state = None

    def startable(self):
        if not self.valid_game():
            return False

        connected_players = len(self.buzzer_controller.connected_players)
        if connected_players == 0:
            return False

        expected_player_count = self.expected_player_count()
        if expected_player_count is not None and connected_players != expected_player_count:
            return False

        return True

    def expected_player_count(self):
        if self._resume_state is None:
            return None
        return self._resume_state.get("player_count")

    def clear_resume_state(self):
        self._resume_state = None

    def prepare_resume_from_dir(self, saved_game_dir):
        from jparty.services.game_loader import get_game

        saved_game_path = Path(saved_game_dir)
        general_file = saved_game_path / "general.json"
        if not general_file.exists():
            raise FileNotFoundError("Saved game folder must contain general.json")

        try:
            with open(general_file, "r") as f:
                general_state = json.load(f)
        except Exception as e:
            raise ValueError(f"Could not load saved game metadata: {e}") from e

        game_id = str(general_state.get("game_id", "")).strip()
        saved_players = general_state.get("players", [])
        if not game_id:
            raise ValueError("Saved game metadata is missing a game_id")
        if not saved_players:
            raise ValueError("Saved game metadata is missing player information")

        self.data = get_game(game_id)
        if not self.valid_game():
            raise ValueError("Saved game points to an invalid or incomplete game")

        self._resume_state = {
            "path": saved_game_path,
            "game_id": game_id,
            "general_state": general_state,
            "player_count": len(saved_players),
        }
        return self._resume_state

    def begin(self):
        self.song_player.play(repeat=True)

    def start_game(self):
        if self._resume_state:
            self._start_resumed_game()
            return

        self.current_round = self.data.rounds[0]
        self.dc.hide_welcome_widgets()
        self.dc.board_widget.load_round(self.current_round)
        self.buzzer_controller.accepting_players = False
        self.song_player.stop()
        self._game_started_at = time.time()
        self._initialize_game_state_dir()
        self._save_general_state()

    def _mark_completed_questions(self, question_history):
        for entry in question_history:
            round_index = entry.get("round_index")
            question_index = entry.get("question_index")
            if (
                round_index is None
                or question_index is None
                or len(question_index) < 2
                or round_index >= len(self.data.rounds)
            ):
                continue

            question_coords = question_index[1]
            if not isinstance(question_coords, (list, tuple)) or len(question_coords) != 2:
                continue

            question = self.data.rounds[round_index].get_question(*question_coords)
            if question is not None:
                question.complete = True

    def _restore_player_scores(self):
        score_history = self._reconstruct_score_history()
        for player in self.players:
            player_scores = score_history.get(player.player_number, [0])
            player.score = player_scores[-1] if player_scores else 0

    def _round_is_complete(self, round_data):
        if isinstance(round_data, FinalBoard):
            return round_data.question.complete
        return all(question.complete for question in round_data.questions)

    def _get_resume_round(self):
        for round_data in self.data.rounds[:-1]:
            if not self._round_is_complete(round_data):
                return round_data
        return self.data.rounds[-1]

    def _start_resumed_game(self):
        resume_state = self._resume_state
        self._game_state_dir = resume_state["path"]
        self._game_started_at = resume_state["general_state"].get("started_at") or time.time()

        self.players = self.buzzer_controller.connected_players
        self._update_player_numbers()

        question_history = self._load_question_history()
        question_history.sort(key=lambda entry: entry.get("question_number", 0))
        self._mark_completed_questions(question_history)
        self._restore_player_scores()

        if question_history:
            self.question_number = max(
                entry.get("question_number", 0) for entry in question_history
            ) + 1
        else:
            self.question_number = 1

        self.current_round = self._get_resume_round()
        self.active_question = None
        self.answering_player = None
        self.previous_answerers = set()
        self.early_buzzes = set()
        self.responses_open_time = None
        self.timer = None

        self.dc.hide_welcome_widgets()
        self.buzzer_controller.accepting_players = False
        self.song_player.stop()
        self.dc.scoreboard.refresh_players()
        for player in self.players:
            self.dc.player_widget(player).update_score()

        if isinstance(self.current_round, FinalBoard):
            self.dc.load_final(self.current_round.question)
            self.active_question = self.current_round.question
            self.start_final()
        else:
            self.dc.board_widget.load_round(self.current_round)

        for player in self.players:
            self._update_lectern_for_player(player)

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
        game_id = self.current_game_id()
        if not game_id:
            return
        self._game_state_dir = GAME_STATES_DIR / self._game_state_dir_name(game_id)
        self._game_state_dir.mkdir(parents=True, exist_ok=True)

    def _game_state_dir_name(self, game_id):
        timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M")
        return f"{game_id}-{timestamp}"

    def current_game_id(self):
        return os.environ.get("JPARTY_GAME_ID", "")

    def _get_current_game_state(self):
        return get_current_game_state(self)

    def _save_general_state(self):
        save_general_state(self)

    def _classify_buzz_phases(self):
        return classify_buzz_phases(self)

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


    def back_to_board(self):
        logging.info("back_to_board")
        
        # Save question history before incrementing question number
        self._flush_question_history()
        
        self.question_number += 1
        self.dc.hide_question()
        self.timer = None
        self.active_question.complete = True
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
        self.set_score(ap, ap.score + ap.wager)
        self.final_judgement_given()

    def final_incorrect_answer(self):
        ap = self.answering_player
        new_score = ap.score - ap.wager
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

    def _load_question_history(self):
        return load_question_history(self)

    def _reconstruct_score_history(self):
        return reconstruct_score_history(self)

    def _load_general_state(self):
        return load_general_state(self)

    def generate_final_score_graph(self, players):
        """create an image of score by question number"""
        # Reconstruct score history from question_history.jsonl
        all_score_history = self._reconstruct_score_history()
        if not all_score_history:
            logging.warning("No score history found to generate graph")
            return
        
        # Get player name mappings
        general_state = self._load_general_state()
        original_player_map = {
            p.get("player_number"): p.get("name", f"Player {p.get('player_number')}")
            for p in general_state.get("players", [])
        }
        current_player_map = {
            p.player_number: p.name for p in self.players
        }
        
        # Determine which players to include
        if players == "original":
            player_numbers = set(original_player_map.keys())
        elif players == "current":
            player_numbers = set(current_player_map.keys())
        elif players == "all":
            player_numbers = set(original_player_map.keys()) | set(current_player_map.keys())
        else:
            logging.error(f"Unknown player set: {players}")
            return
        
        # Filter score history to requested players
        data = {
            pnum: all_score_history[pnum]
            for pnum in player_numbers
            if pnum in all_score_history
        }
        
        if not data:
            logging.warning(f"No score data found for player set: {players}")
            return
        
        game_id = os.environ.get("JPARTY_GAME_ID", "unknown")
        
        # Isolate matplotlib operations to prevent interference with PyQt6
        fig = None
        try:
            # Create matplotlib figure
            fig, ax = plt.subplots(figsize=(10, 6))
            
            # Plot each player's scores
            for player_number, scores in data.items():
                # Get player name, preferring current name if available
                player_name = current_player_map.get(player_number) or original_player_map.get(player_number) or f"Player {player_number}"
                # x_values: 1 = start, 2 = after q1, 3 = after q2, etc.
                x_values = list(range(1, len(scores) + 1))
                ax.plot(x_values, scores, marker='o', label=player_name, linewidth=2, markersize=6)
            
            ax.set_xlabel('Question Number', fontsize=12)
            ax.set_ylabel('Score', fontsize=12)
            ax.set_title(f'Game {game_id}: Player Scores', fontsize=14, fontweight='bold')
            ax.legend(loc='best')
            ax.grid(True, alpha=0.3)
            
            # Save the figure
            GAME_SCORES_DIR.mkdir(exist_ok=True)
            image_path = GAME_SCORES_DIR / f"{game_id}-{players}.jpg"
            
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

    def close(self):
        self.song_player.stop()
        QApplication.quit()

