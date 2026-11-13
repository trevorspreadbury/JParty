"""Coordinate the live flow of a JParty game session.

This module contains the primary gameplay orchestrator. The ``Game`` class ties
together loaded game data, player connections, timers, persistence helpers,
lectern updates, scorekeeping, and UI triggers so a full Jeopardy-style match
can progress from lobby to final score graphs.
"""

import json
import logging
import os
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Thread

import matplotlib
import matplotlib.pyplot as plt
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox, QWidget

matplotlib.use("Agg")
from jparty import __version__
from jparty.app.paths import GAME_SCORES_DIR, GAME_STATES_DIR
from jparty.domain.gameplay import (
    ClueFlow,
    FinalJeopardyFlow,
    PlayerStateBroadcaster,
    ScoreRecorder,
)
from jparty.domain.input import (
    MAX_PLAYERS,
    KeystrokeManager,
    QuestionTimer,
    index_to_key,
)
from jparty.domain.models import FinalBoard, GameData
from jparty.domain.state import (
    HISTORY_FORMAT,
    NO_ANSWER_RESULT,
    PLAYER_RENUMBER_TYPE,
    QUESTION_HISTORY_FILE_NAME,
    SCORE_CORRECTION_TYPE,
    HistoryFileError,
    board_selections_match_original_game_subset,
    classify_buzz_phases,
    clue_player_results,
    clue_score_effects,
    corrected_history_entries,
    current_saved_players,
    get_current_game_state,
    history_score_totals,
    is_question_history_entry,
    load_general_state,
    load_question_history,
    load_saved_game_data,
    read_history_file,
    reconstruct_score_history,
    ruling_score_effect,
    save_general_state,
)
from jparty.services.game_loader import build_game_from_board_selection_configs
from jparty.ui.widgets.common import CompoundObject, SongPlayer

QUESTION_INDEX_PART_COUNT = 2
DEFAULT_DAILY_DOUBLE_WAGER_CAP = 1000


def _ends_with_newline(path: Path) -> bool:
    """Return whether the last byte of a non-empty file is a newline.

    Args:
        path: File to check.

    Returns:
        ``True`` when the file ends with a newline byte.
    """
    with path.open("rb") as file_obj:
        file_obj.seek(-1, os.SEEK_END)
        return file_obj.read(1) == b"\n"


class Game(QObject):
    """Manage one active JParty game, including state, players, and flow."""

    buzz_trigger = pyqtSignal(int)
    new_player_trigger = pyqtSignal()
    stumped_trigger = pyqtSignal()
    final_finished_trigger = pyqtSignal()
    wager_trigger = pyqtSignal(int, int)
    toolate_trigger = pyqtSignal()
    lectern_update_trigger = pyqtSignal(int, dict)

    def __init__(self) -> None:
        """Initialize a game controller with default runtime state.

        Returns:
            ``None``.
        """
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
        self.soliciting_player = False
        self.early_buzzes = set()
        self.responses_open_time = None
        self.song_player = SongPlayer()
        self._judgement_round = 0
        self._sorted_players = None
        self.buzzer_controller = None
        self._question_timer_factory = QuestionTimer
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
            "REVEAL_STUMPED_ANSWER",
            Qt.Key.Key_Space,
            self.reveal_stumped_answer,
            self.spacehints,
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
            "GENERATE_GRAPHS",
            Qt.Key.Key_Space,
            self.generate_final_score_graphs,
            self.spacehints,
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
                lambda x: x,
                active=True,
                persistent=True,
                func_args=player_index,
            )
        self.wager_trigger.connect(self.wager)
        self.buzz_trigger.connect(self.buzz)
        self.new_player_trigger.connect(self.new_player)
        self.stumped_trigger.connect(self.__handle_stumped_timeout)
        self.final_finished_trigger.connect(self.__handle_final_finished_song)
        self.toolate_trigger.connect(self.__toolate)
        self.lectern_update_trigger.connect(self.__broadcast_lectern_update)
        self._game_state_dir = None
        self._pending_history_lines = []
        self._history_save_failing = False
        self._current_question_history = None
        self._all_buzz_attempts = []
        self._answer_attempts = []
        self._question_start_time = None
        self._open_responses_times = []
        self._successful_buzz_times = []
        self._game_started_at = None
        self._history_format = None
        self._started_by_version = None
        # Players as general.json recorded them when the save started; see
        # current_saved_players. None for a fresh game.
        self._starting_roster = None
        self._resume_state = None
        self._selected_round_indices = None
        self._board_selection_configs = None
        self._composed_board_selection_configs = None
        self._composed_game_data = None
        self._session_game_id = ""
        self._reveal_answers_after_triple_stumper = False
        self._awaiting_stumped_answer_reveal = False
        self.player_state_broadcaster = PlayerStateBroadcaster(self)
        self.score_recorder = ScoreRecorder(self)
        self.clue_flow = ClueFlow(self)
        self.final_jeopardy_flow = FinalJeopardyFlow(self)

    def startable(self) -> bool:
        """Determine whether the game can start with the current connections.

        Returns:
            ``True`` when valid game data is loaded and the connected player
            count matches the expected resume state, if any.
        """
        if not self.valid_game():
            return False
        expected_player_count = self.expected_player_count()
        if expected_player_count is not None:
            return self.resume_claims_complete()
        connected_players = len(self.buzzer_controller.connected_players)
        if connected_players == 0:
            return False
        return True

    def expected_player_count(self) -> object:
        """Return the player count required by a resumed session, if any.

        Returns:
            The expected player count from resume metadata, or ``None`` for a
            fresh game.
        """
        if self._resume_state is None:
            return None
        return self._resume_state.get("player_count")

    def clear_resume_state(self) -> None:
        """Discard any prepared resume metadata.

        Returns:
            ``None``.
        """
        self._resume_state = None
        self._selected_round_indices = None
        self._board_selection_configs = None
        self._composed_board_selection_configs = None
        self._composed_game_data = None
        self._session_game_id = ""
        if self.buzzer_controller:
            self.buzzer_controller.clear_saved_player_reclaim()

    def resume_claim_status(self) -> tuple[int, int]:
        """Return current claim progress for a prepared saved-game lobby.

        Returns:
            Tuple of ``(claimed_count, total_count)`` for saved-player reclaim.
        """
        if not self.buzzer_controller:
            return (0, 0)
        return (
            self.buzzer_controller.saved_player_claim_count(),
            self.buzzer_controller.saved_player_total_count(),
        )

    def resume_claims_complete(self) -> bool:
        """Return whether all saved players have been claimed.

        Returns:
            ``True`` when every saved player profile has been reclaimed.
        """
        if self._resume_state is None or not self.buzzer_controller:
            return False
        return self.buzzer_controller.saved_player_claims_complete()

    def set_selected_round_indices(self, indices: object) -> None:
        """Store the original round indices selected for play.

        Args:
            indices: Iterable of zero-based round indices to include when the
                game starts, or ``None`` to fall back to all rounds.

        Returns:
            ``None``.
        """
        if indices is None:
            self._selected_round_indices = None
            return
        self._selected_round_indices = sorted({int(index) for index in indices})

    def set_board_selection_configs(self, configs: object) -> None:
        """Store composed board-selection metadata for advanced game startup.

        Args:
            configs: Iterable of serializable board-selection dictionaries, or
                ``None`` to clear the current advanced configuration.

        Returns:
            ``None``.
        """
        if configs is None:
            self._board_selection_configs = None
            self._composed_board_selection_configs = None
            self._composed_game_data = None
            return
        self._board_selection_configs = deepcopy(list(configs))
        if self._composed_board_selection_configs != self._board_selection_configs:
            self._composed_board_selection_configs = None
            self._composed_game_data = None

    def board_selection_configs(self) -> list[dict]:
        """Return the configured advanced board selections for this session."""
        if not self._board_selection_configs:
            return []
        return deepcopy(self._board_selection_configs)

    def set_composed_game_data(
        self, configs: object, composed_game_data: object | None
    ) -> None:
        """Store the latest composed advanced game for immediate reuse."""
        self._composed_board_selection_configs = (
            deepcopy(list(configs)) if configs is not None else None
        )
        self._composed_game_data = composed_game_data

    def matching_composed_game_data(self, configs: object) -> object | None:
        """Return cached composed game data when it matches the config."""
        normalized_configs = deepcopy(list(configs)) if configs is not None else None
        if normalized_configs != self._composed_board_selection_configs:
            return None
        return deepcopy(self._composed_game_data) if self._composed_game_data else None

    def set_session_game_id(self, game_id: object) -> None:
        """Store the current session identifier used for saves and logging."""
        self._session_game_id = str(game_id or "").strip()

    def set_reveal_answers_after_triple_stumper(self, enabled: bool) -> None:
        """Store whether triple-stumper clues should reveal their answer.

        Args:
            enabled: ``True`` to reveal the answer before leaving the clue.

        Returns:
            ``None``.
        """
        self._reveal_answers_after_triple_stumper = bool(enabled)

    def reveal_answers_after_triple_stumper_enabled(self) -> bool:
        """Return whether triple-stumper clues reveal the answer first."""
        return self._reveal_answers_after_triple_stumper

    def selected_round_indices(self) -> list[int]:
        """Return the configured original round indices for this session.

        Returns:
            Selected zero-based round indices, or all currently loaded rounds
            when no explicit selection has been stored.
        """
        if self._selected_round_indices is not None:
            return list(self._selected_round_indices)
        if self.data is None:
            return []
        return list(range(len(self.data.rounds)))

    def _apply_selected_rounds_to_data(self) -> None:
        """Filter loaded game data down to the currently selected rounds.

        Returns:
            ``None``.
        """
        if self.data is None:
            return
        selected_rounds = [
            self.data.rounds[index]
            for index in self.selected_round_indices()
            if 0 <= index < len(self.data.rounds)
        ]
        self.data = GameData(selected_rounds, self.data.date, self.data.comments)

    def prepare_resume_from_dir(self, saved_game_dir: object) -> object:
        """Load enough metadata to resume a previously saved game session.

        Args:
            saved_game_dir: Filesystem path to a saved game directory containing
                at least ``general.json`` and related session files.

        Returns:
            A dictionary describing the loaded resume state.

        Raises:
            FileNotFoundError: If the provided directory does not contain the
                required metadata file.
            ValueError: If the metadata cannot be loaded or points to an
                invalid game.
            HistoryFileError: If the saved clue history cannot be read. This
                is checked before the game itself is fetched.
        """
        saved_game_path = Path(saved_game_dir)
        general_file = saved_game_path / "general.json"
        if not general_file.exists():
            raise FileNotFoundError("Saved game folder must contain general.json")
        try:
            with general_file.open() as f:
                general_state = json.load(f)
        except Exception as e:
            raise ValueError(f"Could not load saved game metadata: {e}") from e
        game_id = str(general_state.get("game_id", "")).strip()
        saved_players = general_state.get("players", [])
        if not game_id:
            raise ValueError("Saved game metadata is missing a game_id")
        if not saved_players:
            raise ValueError("Saved game metadata is missing player information")
        # Check the history before fetching the game, which can hit the network,
        # so a damaged save fails right away and leaves the game state untouched.
        history_entries = read_history_file(
            saved_game_path / QUESTION_HISTORY_FILE_NAME
        )
        current_players = current_saved_players(saved_players, history_entries)
        saved_game = load_saved_game_data(general_state)
        self.data = saved_game.data
        self.set_board_selection_configs(saved_game.board_selection_configs)
        self.set_selected_round_indices(saved_game.selected_round_indices)
        self.set_reveal_answers_after_triple_stumper(
            general_state.get("reveal_answers_after_triple_stumper", False)
        )
        self.set_session_game_id(general_state.get("game_id", game_id))
        if not self.valid_game():
            raise ValueError("Saved game points to an invalid or incomplete game")
        self._resume_state = {
            "path": saved_game_path,
            "game_id": game_id,
            "general_state": general_state,
            "player_count": len(saved_players),
        }
        if self.buzzer_controller:
            self.buzzer_controller.begin_saved_player_reclaim(current_players)
        return self._resume_state

    def _board_selections_match_original_game_subset(
        self,
        game_id: str,
        game_data: object,
        board_selection_configs: list[dict],
        selected_round_indices: object,
    ) -> bool:
        """Return whether saved board selections describe a simple original-game subset.

        See :func:`board_selections_match_original_game_subset`.
        """
        return board_selections_match_original_game_subset(
            game_id, game_data, board_selection_configs, selected_round_indices
        )

    def begin(self) -> None:
        """Begin the pre-game lobby state by starting the intro music.

        Returns:
            ``None``.
        """
        self.song_player.play(repeat=True)

    def start_game(self) -> None:
        """Start a fresh game or resume a prepared saved session.

        Returns:
            ``None``.
        """
        if self._resume_state and not self._resume_matches_current_game():
            # Resuming would apply the save's history to a different board and
            # overwrite its general.json, so start this board fresh instead.
            logging.error(
                "Prepared resume is for game %r but the current game is %r; "
                "starting a fresh game instead of writing into the save",
                self._resume_state["general_state"].get(
                    "game_id", self._resume_state.get("game_id")
                ),
                self.current_game_id(),
            )
            self._resume_state = None
            if self.buzzer_controller:
                self.buzzer_controller.clear_saved_player_reclaim()
        if self._resume_state:
            self._start_resumed_game()
            return
        if self._board_selection_configs:
            self.data = self.matching_composed_game_data(self._board_selection_configs)
            if self.data is None:
                self.data = build_game_from_board_selection_configs(
                    self._board_selection_configs
                )
                self.set_composed_game_data(self._board_selection_configs, self.data)
        else:
            self._apply_selected_rounds_to_data()
        if not self.data or not self.data.rounds:
            logging.warning("No rounds selected for play")
            return
        self.current_round = self.data.rounds[0]
        self.dc.hide_welcome_widgets()
        self.buzzer_controller.accepting_players = False
        self.song_player.stop()
        self._game_started_at = time.time()
        self._history_format = HISTORY_FORMAT
        self._started_by_version = __version__
        self._starting_roster = None
        self._initialize_game_state_dir()
        self._save_general_state()
        if isinstance(self.current_round, FinalBoard):
            self.dc.load_final(self.current_round.question)
            self.active_question = self.current_round.question
            self.start_final()
        else:
            self.dc.board_widget.load_round(self.current_round)
        Thread(target=self._save_played_game_html, daemon=True).start()
        self._refresh_score_edit_controls()

    def _resume_matches_current_game(self) -> bool:
        """Return whether the prepared resume is for the game about to start.

        ``prepare_resume_from_dir`` sets the session id to the save's
        ``game_id``. Anything that later swaps in a different game (such as a
        Frankenstein board built in advanced mode) changes the session id.

        Returns:
            ``True`` when the save's game id matches ``current_game_id()``.
        """
        saved_game_id = self._resume_state["general_state"].get(
            "game_id", self._resume_state.get("game_id")
        )
        return str(saved_game_id).strip() == str(self.current_game_id()).strip()

    def _save_played_game_html(self) -> None:
        """Persist the current J-Archive game's HTML once play actually begins.

        Returns:
            ``None``.
        """
        from jparty.services.archive_client import (
            GOOGLE_SHEETS_ID_LENGTH,
            save_game_html,
        )

        game_ids = []
        if self._board_selection_configs:
            game_ids = [
                str(selection.get("game_id", "")).strip()
                for selection in self._board_selection_configs
            ]
        else:
            game_ids = [self.current_game_id()]
        for game_id in {game_id for game_id in game_ids if game_id}:
            if len(game_id) >= GOOGLE_SHEETS_ID_LENGTH:
                continue
            try:
                save_game_html(game_id)
            except Exception:
                logging.error("Could not save game HTML for %s", game_id, exc_info=True)

    def _mark_completed_questions(self, question_history: object) -> None:
        """Mark previously played clues as complete from saved history.

        Args:
            question_history: Iterable of persisted question history entries.

        Returns:
            ``None``.
        """
        for entry in question_history:
            round_index = entry.get("round_index")
            question_index = entry.get("question_index")
            if (
                round_index is None
                or question_index is None
                or len(question_index) < QUESTION_INDEX_PART_COUNT
                or (round_index >= len(self.data.rounds))
            ):
                continue
            question_coords = question_index[1]
            if (
                not isinstance(question_coords, list | tuple)
                or len(question_coords) != QUESTION_INDEX_PART_COUNT
            ):
                continue
            question = self.data.rounds[round_index].get_question(*question_coords)
            if question is not None:
                question.complete = True

    def _record_player_renumbering(self) -> bool:
        """Log any seat changes the host made in the resume lobby.

        Players keep their history under the number they were saved with. If
        the host reordered seats, append one ``player_renumber`` line mapping
        saved numbers to current ones, so the history reader can translate
        every earlier line before scores are restored.

        Unlike clue lines, a mapping that fails to save is not kept for a
        later retry. The game stays in the lobby, and pressing Start again
        builds the full mapping again, so a queued copy would be written
        twice and the two would cancel each other out.

        Returns:
            ``True`` when resuming can continue; ``False`` if the mapping
            could not be saved (the host has already been warned).
        """
        mapping = self.buzzer_controller.saved_player_renumbering()
        if all(saved == current for saved, current in mapping.items()):
            return True
        if self._history_file() is None:
            logging.error("No game state directory available for player renumber")
            return False
        self._pending_history_lines.append(
            {
                "type": PLAYER_RENUMBER_TYPE,
                "mapping": {
                    str(saved): current for saved, current in sorted(mapping.items())
                },
                "timestamp": time.time(),
            }
        )
        if self._flush_pending_history(warn_host=False):
            return True
        self._clear_pending_history()
        self.show_host_warning(
            "Seat Order Not Saved",
            "Could not save the new seat order, so the game has not started. "
            "Check that the saved game folder can be written to, then press "
            "Start again.",
        )
        return False

    def _restore_player_scores(self, history_entries: list[dict]) -> None:
        """Restore each connected player's score from persisted history.

        Args:
            history_entries: Raw history entries in file order. Each player's
                total is their last recorded ``score_after``.

        Returns:
            ``None``.
        """
        totals = history_score_totals(history_entries)
        for player in self.players:
            player.score = totals.get(player.player_number, 0)

    def _round_is_complete(self, round_data: object) -> object:
        """Check whether a round has been fully completed.

        Args:
            round_data: Round object to inspect, either a standard board or the
                final board.

        Returns:
            ``True`` when the round's clues are all marked complete.
        """
        if isinstance(round_data, FinalBoard):
            return round_data.question.complete
        return all(question.complete for question in round_data.questions)

    def _get_resume_round(self) -> object:
        """Return the first incomplete round when resuming a session.

        Returns:
            The current round object that gameplay should resume from.
        """
        playable_round_indices = self._playable_round_indices()
        if not playable_round_indices:
            return self.data.rounds[-1]
        for round_index in playable_round_indices:
            round_data = self.data.rounds[round_index]
            if isinstance(round_data, FinalBoard):
                continue
            if not self._round_is_complete(round_data):
                return round_data
        return self.data.rounds[playable_round_indices[-1]]

    def _playable_round_indices(self) -> list[int]:
        """Return the currently selected round indices that are valid for play."""
        if not self.data:
            return []
        return [
            index
            for index in self.selected_round_indices()
            if 0 <= index < len(self.data.rounds)
        ]

    def _start_resumed_game(self) -> None:
        """Restore UI and runtime state from the prepared resume metadata.

        Returns:
            ``None``.
        """
        resume_state = self._resume_state
        self._game_state_dir = resume_state["path"]
        self._clear_pending_history()
        self._game_started_at = (
            resume_state["general_state"].get("started_at") or time.time()
        )
        # Keep what the save recorded, so a resumed legacy save stays unmarked.
        self._history_format = resume_state["general_state"].get("history_format")
        self._started_by_version = resume_state["general_state"].get("jparty_version")
        # general.json keeps the numbers the save started with. Seat changes
        # are recorded only as player_renumber lines in the history.
        self._starting_roster = resume_state["general_state"].get("players", [])
        self.players = self.buzzer_controller.claimed_saved_players()
        if not self._record_player_renumbering():
            return
        raw_history = self._load_question_history()
        question_history = [
            entry
            for entry in corrected_history_entries(raw_history)
            if is_question_history_entry(entry)
        ]
        question_history.sort(key=lambda entry: entry.get("question_number", 0))
        self._mark_completed_questions(question_history)
        self._restore_player_scores(raw_history)
        if question_history:
            self.question_number = (
                max(entry.get("question_number", 0) for entry in question_history) + 1
            )
        else:
            self.question_number = 1
        self.current_round = self._get_resume_round()
        self.active_question = None
        self._awaiting_stumped_answer_reveal = False
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
            if self.current_round.question.complete:
                # Final was judged before the app closed, so its wagers and
                # rulings are already in the history. Go to the end of the
                # game instead of opening wagers again.
                self.dc.load_final_judgement()
                self.end_game()
            else:
                self.start_final()
        else:
            self.dc.board_widget.load_round(self.current_round)
            # Space is normally enabled by back_to_board after the last clue, so
            # a session closed on a finished board would otherwise be stuck.
            if self._round_is_complete(self.current_round):
                self.keystroke_manager.activate("NEXT_ROUND")
        for player in self.players:
            self._update_lectern_for_player(player)
        self._save_general_state()
        self._refresh_score_edit_controls()

    def setDisplays(self, host_display: object, main_display: object) -> None:
        """Attach the host and audience display windows to the game.

        Args:
            host_display: Host-facing Qt window that controls gameplay.
            main_display: Audience-facing Qt window that shows the board and
                clues.

        Returns:
            ``None``.
        """
        self.host_display = host_display
        self.main_display = main_display
        self.dc = CompoundObject(host_display, main_display)
        self._refresh_score_edit_controls()

    def setBuzzerController(self, controller: object) -> None:
        """Attach the buzzer controller used for player and lectern I/O.

        Args:
            controller: ``BuzzerController``-like object that manages player
                connections and lectern messages.

        Returns:
            ``None``.
        """
        self.buzzer_controller = controller

    def _get_question_index(self) -> object:
        """Return the active clue identifier used in persistence records.

        Returns:
            A ``(round_index, question_index)`` tuple for the active clue, or
            ``None`` when no active clue is available.
        """
        if not self.active_question or not self.data:
            return None
        try:
            round_index = self.data.rounds.index(self.current_round)
            return (round_index, self.active_question.index)
        except (ValueError, AttributeError):
            return None

    def _initialize_game_state_dir(self) -> None:
        """Create the save directory for the current game session if possible.

        Returns:
            ``None``.
        """
        game_id = self.current_game_id()
        if not game_id:
            return
        self._game_state_dir = GAME_STATES_DIR / self._game_state_dir_name(game_id)
        self._game_state_dir.mkdir(parents=True, exist_ok=True)
        self._clear_pending_history()

    def _game_state_dir_name(self, game_id: object) -> str:
        """Build the timestamped directory name used for saved game state.

        Args:
            game_id: Current game identifier to embed in the directory name.

        Returns:
            A timestamped directory name string.
        """
        timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M")
        return f"{game_id}-{timestamp}"

    def current_game_id(self) -> object:
        """Return the id of the game being set up or played.

        For a Frankenstein game this is the composed session id, not the id of
        any one source game.

        Returns:
            The session game id, or an empty string when none is set.
        """
        return self._session_game_id

    def _get_current_game_state(self) -> object:
        """Return the serializable high-level state for this session.

        Returns:
            A dictionary describing the current game state.
        """
        return get_current_game_state(self)

    def _save_general_state(self) -> None:
        """Persist the high-level session metadata for the current game.

        Returns:
            ``None``.
        """
        save_general_state(self)

    def _classify_buzz_phases(self) -> object:
        """Return buzz-phase summaries for the current clue.

        Returns:
            A list describing main and rebound buzz windows for persistence.
        """
        return classify_buzz_phases(self)

    def _history_file(self) -> object:
        """Return the current session's question-history JSONL path.

        Returns:
            The ``question_history.jsonl`` path for the current session.
        """
        if not self._game_state_dir:
            self._initialize_game_state_dir()
        if not self._game_state_dir:
            return None
        return self._game_state_dir / QUESTION_HISTORY_FILE_NAME

    def _append_history_entry(self, entry: dict) -> bool:
        """Append a history record to the current session JSONL file.

        The entry joins the queue of unsaved lines, and the whole queue is
        written in order. If the write fails (for example, the disk is full or
        another program briefly locks the file), the lines stay queued and are
        written again in front of the next entry. The file therefore never
        skips a line, so its score chain stays intact.

        Args:
            entry: Serializable history entry to append.

        Returns:
            ``True`` when the entry and every earlier queued line were saved.
        """
        if self._history_file() is None:
            logging.error("No game state directory available for history append")
            return False
        self._pending_history_lines.append(entry)
        return self._flush_pending_history()

    def _flush_pending_history(self, warn_host: bool = True) -> bool:
        """Write every queued history line to the session file, oldest first.

        The lines are written in a single ``write``, then flushed. If the file
        does not end with a newline (for example, after a hand repair), one is
        written first so the new lines start on their own line. If anything
        fails, the file is truncated back to its previous size so no partial
        line is left behind, and the lines stay queued. The host is warned on
        the first failure in a row only.

        Args:
            warn_host: Whether to show the "Clue History Not Saved" warning
                on failure. Callers that show their own warning pass ``False``.

        Returns:
            ``True`` when nothing is left in the queue.
        """
        if not self._pending_history_lines:
            return True
        history_file = self._history_file()
        if history_file is None:
            return False
        size_before = history_file.stat().st_size if history_file.exists() else 0
        try:
            text = "".join(
                json.dumps(entry) + "\n" for entry in self._pending_history_lines
            )
            if size_before and not _ends_with_newline(history_file):
                text = "\n" + text
            with history_file.open("a", encoding="utf-8", newline="\n") as file_obj:
                file_obj.write(text)
                file_obj.flush()
        except Exception as exc:
            logging.error("Error appending question history: %s", exc, exc_info=True)
            try:
                with history_file.open("r+b") as file_obj:
                    file_obj.truncate(size_before)
            except OSError:
                logging.error("Could not roll back question history", exc_info=True)
            if warn_host and not self._history_save_failing:
                self._history_save_failing = True
                reason = getattr(exc, "strerror", None) or exc
                self.show_host_warning(
                    "Clue History Not Saved",
                    f"Could not save clue history: {reason}.\n\n"
                    "JParty is keeping the unsaved clues and will try again "
                    "after the next clue. The saved game is still safe to "
                    "load, but it will be missing these clues if the problem "
                    "continues until you close the game.",
                )
            return False
        if self._history_save_failing:
            logging.info(
                "Saved %d delayed question history lines",
                len(self._pending_history_lines),
            )
        self._clear_pending_history()
        return True

    def _finish_pending_history(self) -> None:
        """Make a last attempt to save queued lines before the session ends.

        If the lines still cannot be written, the host is told how many are
        missing from the save. The file on disk still loads, and resumes from
        before those lines.

        Returns:
            ``None``.
        """
        if not self._flush_pending_history():
            self.show_host_warning(
                "Clue History Not Saved",
                f"Could not save the last {len(self._pending_history_lines)} "
                "clue history entries. The saved game will still load, but it "
                "resumes from before those clues.",
            )
        self._clear_pending_history()

    def _clear_pending_history(self) -> None:
        """Drop queued history lines, for example when a session ends.

        Returns:
            ``None``.
        """
        self._pending_history_lines = []
        self._history_save_failing = False

    def show_host_warning(self, title: str, text: str) -> None:
        """Show a warning dialog to the host.

        Args:
            title: Dialog title.
            text: Message body.

        Returns:
            ``None``.
        """
        parent = self.host_display if isinstance(self.host_display, QWidget) else None
        QMessageBox.warning(parent, title, text)

    def show_history_error(self, error: HistoryFileError) -> None:
        """Tell the host that the saved clue history could not be read.

        Args:
            error: The history read failure.

        Returns:
            ``None``.
        """
        logging.error("%s", error)
        self.show_host_warning("Saved Clue History Error", str(error))

    def _refresh_score_edit_controls(self) -> None:
        """Refresh the enabled state of host score-edit controls.

        Returns:
            ``None``.
        """
        scoreboard = getattr(self.host_display, "scoreboard", None)
        if scoreboard is not None and hasattr(scoreboard, "refresh_score_edit_button"):
            scoreboard.refresh_score_edit_button()

    def can_open_score_editor(self) -> bool:
        """Return whether the host score-correction dialog should be enabled.

        Returns:
            ``True`` when there is saved non-final clue history and no active
            clue interaction is in progress.
        """
        if self.active_question is not None or self.soliciting_player:
            return False
        try:
            return bool(self.get_recent_score_corrections(limit=1))
        except HistoryFileError:
            # Keep the button usable so clicking it shows the host the error.
            return True

    def _question_from_history_entry(self, entry: dict) -> object:
        """Resolve the question object referenced by a saved clue history entry.

        Args:
            entry: Persisted clue history entry.

        Returns:
            Matching question object, or ``None`` when unavailable.
        """
        question_index = entry.get("question_index")
        round_index = entry.get("round_index")
        if (
            not self.data
            or question_index is None
            or round_index is None
            or len(question_index) < QUESTION_INDEX_PART_COUNT
            or round_index >= len(self.data.rounds)
        ):
            return None
        question_coords = question_index[1]
        if (
            not isinstance(question_coords, list | tuple)
            or len(question_coords) != QUESTION_INDEX_PART_COUNT
        ):
            return None
        return self.data.rounds[round_index].get_question(*question_coords)

    def get_recent_score_corrections(self, limit: int = 5) -> list[dict]:
        """Return recent standard-clue history entries for the score editor.

        Args:
            limit: Maximum number of clue entries to return.

        Returns:
            Newest-first list of score-correction view models showing each
            clue's current (corrected) ruling.

        Raises:
            HistoryFileError: If the history file cannot be read.
        """
        entries = corrected_history_entries(self._load_question_history())
        recent_entries = []
        for entry in entries:
            if not is_question_history_entry(entry):
                continue
            question = self._question_from_history_entry(entry)
            if question is None or isinstance(
                self.data.rounds[entry["round_index"]], FinalBoard
            ):
                continue
            player_states = {
                player.player_number: clue_player_results(entry).get(
                    player.player_number, NO_ANSWER_RESULT
                )
                for player in self.players
            }
            recent_entries.append(
                {
                    "question_number": entry.get("question_number"),
                    "category": entry.get("category", ""),
                    "value": entry.get("value", 0),
                    "answer": question.answer,
                    "is_daily_double": bool(entry.get("is_daily_double")),
                    "player_states": player_states,
                }
            )
        recent_entries.sort(
            key=lambda entry: entry.get("question_number", 0), reverse=True
        )
        return recent_entries[:limit]

    def apply_question_history_corrections(self, corrections: list[dict]) -> bool:
        """Record host score-correction edits as appended history lines.

        Each changed clue appends one ``score_correction`` line holding the
        corrected ruling and, for every affected player, the score change
        applied to their current total. The history file is never rewritten.

        Args:
            corrections: Edited clue payloads keyed by ``question_number``.

        Returns:
            ``True`` when any correction was recorded. A correction that could
            not be written yet stays queued; see :meth:`_append_history_entry`.

        Raises:
            HistoryFileError: If the history file cannot be read.
        """
        if not corrections:
            return False
        raw_entries = self._load_question_history()
        effective_entries = {
            entry.get("question_number"): entry
            for entry in corrected_history_entries(raw_entries)
            if is_question_history_entry(entry)
        }
        totals = history_score_totals(raw_entries)
        correction_lines = []
        for correction in sorted(
            corrections, key=lambda correction: correction["question_number"]
        ):
            question_number = correction["question_number"]
            entry = effective_entries.get(question_number)
            if entry is None:
                continue
            current_results = clue_player_results(entry)
            current_states = {
                player.player_number: current_results.get(
                    player.player_number, NO_ANSWER_RESULT
                )
                for player in self.players
            }
            corrected_states = {
                int(player_index): result
                for player_index, result in correction["player_states"].items()
            }
            current_value = int(entry.get("value", 0) or 0)
            corrected_value = (
                int(correction["value"])
                if entry.get("is_daily_double")
                else current_value
            )
            if corrected_states == current_states and corrected_value == current_value:
                continue
            current_effects = clue_score_effects(entry)
            adjustments = []
            for player_index in sorted(set(current_effects) | set(corrected_states)):
                change = ruling_score_effect(
                    corrected_states.get(player_index, NO_ANSWER_RESULT),
                    corrected_value,
                ) - current_effects.get(player_index, 0)
                if not change:
                    continue
                score_before = totals.get(player_index, 0)
                totals[player_index] = score_before + change
                adjustments.append(
                    {
                        "player_index": player_index,
                        "score_before": score_before,
                        "score_after": score_before + change,
                    }
                )
            correction_line = {
                "type": SCORE_CORRECTION_TYPE,
                "question_number": question_number,
                "timestamp": time.time(),
                "player_states": {
                    str(player_index): result
                    for player_index, result in sorted(corrected_states.items())
                },
            }
            if entry.get("is_daily_double"):
                correction_line["value"] = corrected_value
            correction_line["adjustments"] = adjustments
            correction_lines.append(correction_line)

        players_by_number = {player.player_number: player for player in self.players}
        for correction_line in correction_lines:
            self._append_history_entry(correction_line)
            for adjustment in correction_line["adjustments"]:
                player = players_by_number.get(adjustment["player_index"])
                if player is not None:
                    self.set_score(player, adjustment["score_after"])
        self._refresh_score_edit_controls()
        return bool(correction_lines)

    def apply_manual_score_override(self, player: object, new_score: int) -> bool:
        """Log and apply a host-entered manual player score override.

        Args:
            player: Player whose score should be overridden.
            new_score: Replacement score value.

        Returns:
            ``True`` when the override was applied.
        """
        return self.score_recorder.apply_manual_score_override(player, new_score)

    def _flush_question_history(self) -> None:
        """Persist the active clue's history and clear per-question buffers.

        Returns:
            ``None``.
        """
        self.score_recorder.flush_question_history()

    def arrowhints(self, val: object) -> None:
        """Update host UI arrow-key hints.

        Args:
            val: Boolean-like flag indicating whether the hints should show as
                active.

        Returns:
            ``None``.
        """
        self.host_display.borders.arrowhints(val)

    def spacehints(self, val: object) -> None:
        """Update host UI space-bar hints.

        Args:
            val: Boolean-like flag indicating whether the hints should show as
                active.

        Returns:
            ``None``.
        """
        self.host_display.borders.spacehints(val)

    def new_player(self) -> None:
        """Refresh local player state after a new player connects.

        Returns:
            ``None``.
        """
        self.players = self.buzzer_controller.connected_players
        if not self.buzzer_controller.in_saved_player_reclaim_mode():
            self._update_player_numbers()
        self.dc.scoreboard.refresh_players()
        self._refresh_score_edit_controls()
        self.host_display.welcome_widget.check_start()
        for player in self.players:
            self._update_lectern_for_player(player)

    def remove_player(self, player: object) -> None:
        """Remove a player from the active roster and refresh displays.

        Args:
            player: Connected player object to remove.

        Returns:
            ``None``.

        In the resume lobby this releases the player's saved slot instead, so
        another phone can claim it without renumbering anyone else.
        """
        if self._in_saved_player_reclaim_mode():
            if not self.buzzer_controller.release_saved_player(player):
                return
            self.players = self.buzzer_controller.connected_players
        else:
            self.players.remove(player)
            self.buzzer_controller.close_socket(player.waiter)
            self._update_player_numbers()
        self.dc.scoreboard.refresh_players()
        self._refresh_score_edit_controls()
        self.host_display.welcome_widget.check_start()
        for player in self.players:
            self._update_lectern_for_player(player)

    def move_player_up(self, player: object) -> None:
        """Move a player one slot earlier in the roster order.

        Args:
            player: Connected player object to reorder.

        Returns:
            ``None``.
        """
        if player not in self.players:
            return
        if self._in_saved_player_reclaim_mode():
            self._move_saved_player(player, -1)
            return
        index = self.players.index(player)
        if index > 0:
            (self.players[index], self.players[index - 1]) = (
                self.players[index - 1],
                self.players[index],
            )
            self._update_player_numbers()
            self.dc.scoreboard.refresh_players()
            self._refresh_score_edit_controls()
            self._update_all_lecterns()

    def move_player_down(self, player: object) -> None:
        """Move a player one slot later in the roster order.

        Args:
            player: Connected player object to reorder.

        Returns:
            ``None``.
        """
        if player not in self.players:
            return
        if self._in_saved_player_reclaim_mode():
            self._move_saved_player(player, 1)
            return
        index = self.players.index(player)
        if index < len(self.players) - 1:
            (self.players[index], self.players[index + 1]) = (
                self.players[index + 1],
                self.players[index],
            )
            self._update_player_numbers()
            self.dc.scoreboard.refresh_players()
            self._refresh_score_edit_controls()
            self._update_all_lecterns()

    def _in_saved_player_reclaim_mode(self) -> bool:
        """Return whether the lobby is reclaiming players from a saved game."""
        return bool(
            self.buzzer_controller
            and self.buzzer_controller.in_saved_player_reclaim_mode()
        )

    def _move_saved_player(self, player: object, offset: int) -> None:
        """Move a reclaimed player one seat and refresh the lobby.

        Args:
            player: Claimed player to move.
            offset: ``-1`` for one seat earlier, ``1`` for one seat later.

        Returns:
            ``None``.
        """
        if not self.buzzer_controller.move_saved_player(player, offset):
            return
        self.players = self.buzzer_controller.connected_players
        self.dc.scoreboard.refresh_players()
        self._refresh_score_edit_controls()
        self._update_all_lecterns()

    def _update_player_numbers(self) -> None:
        """Renumber players and remap their keyboard shortcuts by position.

        In the resume lobby, numbers come from seats instead (see
        ``BuzzerController.seat_order``), so this does nothing.

        Returns:
            ``None``.
        """
        if self._in_saved_player_reclaim_mode():
            return
        for i, player in enumerate(self.players):
            player.player_number = i
            player.key = index_to_key[i]

    def _update_all_lecterns(self) -> None:
        """Broadcast refreshed state to every connected lectern.

        Returns:
            ``None``.
        """
        self.player_state_broadcaster.update_all()

    def valid_game(self) -> object:
        """Check whether loaded game data contains complete rounds.

        Returns:
            ``True`` when ``self.data`` is present and contains at least one
            playable round.
        """
        return self.data is not None and bool(self.data.rounds)

    def open_responses(self) -> None:
        """Open the buzz window for the active clue and start the clue timer.

        Returns:
            ``None``.
        """
        self.clue_flow.open_responses()

    def close_responses(self) -> None:
        """Close the current buzz window without clearing clue state.

        Returns:
            ``None``.
        """
        self.clue_flow.close_responses()

    def keyboard_buzz(self) -> None:
        """Trigger a buzz for the first keyboard-controlled player.

        Returns:
            ``None``.
        """
        self.buzz(0)

    def buzz(self, i_player: object) -> None:
        """Handle a player's buzz attempt for the active clue.

        Args:
            i_player: Zero-based player index identifying who buzzed.

        Returns:
            ``None``.
        """
        self.clue_flow.buzz(i_player)

    def answer_given(self) -> None:
        """Clear answer-resolution UI state after a judgment is made.

        Returns:
            ``None``.
        """
        self.clue_flow.answer_given()

    def back_to_board(self) -> None:
        """Return from a clue view to the board and advance question tracking.

        Returns:
            ``None``.
        """
        self.clue_flow.back_to_board()

    def accept_image(self) -> None:
        """Accept the proposed clue image and continue loading the question.

        Returns:
            ``None``.
        """
        logging.info("Proposed question image accepted")
        self.load_question(self.active_question)

    def no_image_needed(self) -> None:
        """Skip clue image display and continue loading the question.

        Returns:
            ``None``.
        """
        logging.info("No image needed for question")
        self.active_question.image = False
        self.active_question.image_url = None
        self.load_question(self.active_question)

    def next_round(self) -> None:
        """Advance from the current round to the next round in the game.

        Returns:
            ``None``.
        """
        logging.info("next round")
        playable_round_indices = self._playable_round_indices()
        i = self.data.rounds.index(self.current_round)
        logging.info(f"ROUND {i}")
        future_round_indices = [
            round_index for round_index in playable_round_indices if round_index > i
        ]
        if not future_round_indices:
            # Only reached from a regular board: a Final round ends through
            # FinalJeopardyFlow, so no final window exists yet.
            self.dc.load_final_judgement()
            self.end_game()
            return
        self.current_round = self.data.rounds[future_round_indices[0]]
        if isinstance(self.current_round, FinalBoard):
            self.dc.load_final(self.current_round.question)
            self.active_question = self.current_round.question
            self.start_final()
        else:
            self.dc.board_widget.load_round(self.current_round)
        self._refresh_score_edit_controls()

    def start_final(self) -> None:
        """Begin the Final Jeopardy wagering phase.

        Returns:
            ``None``.
        """
        logging.info("start final")
        for player in self.players:
            self.dc.player_widget(player).set_lights(True)
        self.buzzer_controller.open_wagers()
        self._refresh_score_edit_controls()

    def wager(self, i_player: object, amount: object) -> None:
        """Record a Final Jeopardy wager from a player.

        Args:
            i_player: Zero-based player index submitting the wager.
            amount: Wager amount chosen by the player.

        Returns:
            ``None``.
        """
        player = self.players[i_player]
        player.wager = amount
        self.dc.player_widget(player).set_lights(False)
        logging.info(f"{player} wagered {amount}")
        if all(p.wager is not None for p in self.players):
            self.host_display.question_widget.hint_label.setText(
                "Press space to show clue!"
            )
            self.keystroke_manager.activate("OPEN_FINAL")

    def answer(self, player: object, guess: object) -> None:
        """Store a player's Final Jeopardy response text.

        Args:
            player: Player submitting the response.
            guess: Final response text entered by the player.

        Returns:
            ``None``.

        An empty guess never replaces an answer the player already gave. When
        time runs out, each phone resubmits whatever is in its answer box, and
        a phone whose page reloaded after answering has an empty box.
        """
        if not str(guess or "").strip() and player.finalanswer:
            logging.info(f"{player} sent an empty guess; keeping earlier answer")
            return
        player.finalanswer = guess
        logging.info(f"{player} guessed {guess}")

    def final_open_responses(self) -> None:
        """Open Final Jeopardy answer entry and start the music timer.

        Returns:
            ``None``.
        """
        self.final_jeopardy_flow.open_responses()

    def final_next_player(self) -> None:
        """Advance Final Jeopardy judging to the next player.

        Returns:
            ``None``.
        """
        self.final_jeopardy_flow.next_player()

    def final_show_answer(self) -> None:
        """Reveal the current player's Final Jeopardy response.

        Returns:
            ``None``.
        """
        self.final_jeopardy_flow.show_answer()

    def final_correct_answer(self) -> None:
        """Apply a correct Final Jeopardy ruling to the active player.

        Returns:
            ``None``.
        """
        self.final_jeopardy_flow.correct_answer()

    def final_incorrect_answer(self) -> None:
        """Apply an incorrect Final Jeopardy ruling to the active player.

        Returns:
            ``None``.
        """
        self.final_jeopardy_flow.incorrect_answer()

    def final_judgement_given(self) -> None:
        """Finalize one Final Jeopardy judgment and ready the next step.

        Returns:
            ``None``.
        """
        self.final_jeopardy_flow.judgement_given()

    def final_finished_song(self) -> None:
        """Handle the end of the Final Jeopardy think music.

        The music timer calls this from its own thread, so the work is sent
        to the game object's Qt thread through a signal.

        Returns:
            ``None``.
        """
        self.final_finished_trigger.emit()

    def __handle_final_finished_song(self) -> None:
        """Run end-of-music handling on the game object's Qt thread.

        The timeout is queued, so the game may have been closed before it
        arrives. It is ignored unless Final Jeopardy is still being played.

        Returns:
            ``None``.
        """
        if not isinstance(self.current_round, FinalBoard):
            logging.info("Ignoring Final Jeopardy timeout: not in Final Jeopardy")
            return
        self.final_jeopardy_flow.finished_song()

    def end_game(self) -> None:
        """Determine winners, update the UI, and move toward score graphs.

        Returns:
            ``None``.
        """
        self.final_jeopardy_flow.end_game()

    def generate_final_score_graphs(self) -> None:
        """Build and show the end-of-game audience summary screen.

        Returns:
            ``None``.
        """
        self._flush_pending_history()
        self.final_jeopardy_flow.generate_final_score_graphs()

    def _load_question_history(self) -> object:
        """Load per-question history for the current game session.

        Queued lines are retried first. Any that still could not be written
        are included after the saved lines.

        Returns:
            A list of question history entries.
        """
        self._flush_pending_history()
        return load_question_history(self)

    def _reconstruct_score_history(self) -> object:
        """Rebuild player score progressions from saved history.

        Returns:
            A mapping from player index to score-by-question lists.
        """
        return reconstruct_score_history(self)

    def _load_general_state(self) -> object:
        """Load saved high-level metadata for the current session.

        Returns:
            A dictionary containing persisted general session state.
        """
        return load_general_state(self)

    def generate_final_score_graph(self, players: object) -> None:
        """Generate and save a score-by-question graph for a player subset.

        Args:
            players: Player set selector, typically ``"original"``,
                ``"current"``, or ``"all"``.

        Returns:
            ``None``.
        """
        all_score_history = self._reconstruct_score_history()
        if not all_score_history:
            logging.warning("No score history found to generate graph")
            return
        general_state = self._load_general_state()
        saved_players = current_saved_players(
            general_state.get("players", []), self._load_question_history()
        )
        original_player_map = {
            p.get("player_number"): p.get("name", f"Player {p.get('player_number')}")
            for p in saved_players
        }
        current_player_map = {p.player_number: p.name for p in self.players}
        if players == "original":
            player_numbers = set(original_player_map.keys())
        elif players == "current":
            player_numbers = set(current_player_map.keys())
        elif players == "all":
            player_numbers = set(original_player_map.keys()) | set(
                current_player_map.keys()
            )
        else:
            logging.error(f"Unknown player set: {players}")
            return
        data = {
            pnum: all_score_history[pnum]
            for pnum in player_numbers
            if pnum in all_score_history
        }
        if not data:
            logging.warning(f"No score data found for player set: {players}")
            return
        game_id = self.current_game_id() or "unknown"
        fig = None
        try:
            (fig, ax) = plt.subplots(figsize=(10, 6))
            for player_number, scores in data.items():
                player_name = (
                    current_player_map.get(player_number)
                    or original_player_map.get(player_number)
                    or f"Player {player_number}"
                )
                x_values = list(range(1, len(scores) + 1))
                ax.plot(
                    x_values,
                    scores,
                    marker="o",
                    label=player_name,
                    linewidth=2,
                    markersize=6,
                )
            ax.set_xlabel("Question Number", fontsize=12)
            ax.set_ylabel("Score", fontsize=12)
            ax.set_title(
                f"Game {game_id}: Player Scores", fontsize=14, fontweight="bold"
            )
            ax.legend(loc="best")
            ax.grid(True, alpha=0.3)
            GAME_SCORES_DIR.mkdir(exist_ok=True)
            image_path = GAME_SCORES_DIR / f"{game_id}-{players}.jpg"
            plt.tight_layout()
            fig.savefig(str(image_path), dpi=150, bbox_inches="tight")
        finally:
            if fig is not None:
                plt.close(fig)
            plt.close("all")
            plt.ioff()
        QApplication.processEvents()

    def close_game(self) -> None:
        """Reset runtime state so the app can return to the lobby.

        Returns:
            ``None``.
        """
        self._finish_pending_history()
        self.buzzer_controller.restart()
        if self.buzzer_controller:
            for player_number in list(
                self.buzzer_controller.lectern_connections.keys()
            ):
                if player_number in self.buzzer_controller.lectern_connections:
                    try:
                        self.buzzer_controller.send_to(
                            self.buzzer_controller.lectern_connections[player_number],
                            "NO_PLAYER",
                            "",
                        )
                    except Exception:
                        logging.error(
                            "Error notifying lectern %s during close_game",
                            player_number,
                            exc_info=True,
                        )
        self.players = []
        self.question_number = 1
        self.active_question = None
        self.current_round = None
        self.answering_player = None
        # Stop the clue or Final Jeopardy timer. Dropping the reference alone
        # leaves its thread running, and it would fire later in the lobby.
        if self.timer:
            self.timer.cancel()
        self.timer = None
        self.accepting_responses = False
        self.data = None
        self._judgement_round = 0
        self.early_buzzes = set()
        self.responses_open_time = None
        self.dc.restart()
        self.begin()
        self._refresh_score_edit_controls()

    def _board_top_clue_value(self) -> int:
        """Return the highest clue value on the current board.

        Played Daily Doubles are skipped, because their value is replaced by
        the wager. Unplayed ones (including the one being wagered on) still
        hold their row value and count, so a board whose top row is all
        Daily Doubles still caps at that row. The cap comes from the board
        itself, not from the round's position, since a game can start with
        any selected round.

        Returns:
            The highest clue value, or the standard first-round cap when the
            board has no usable values.
        """
        values = [
            question.value
            for question in getattr(self.current_round, "questions", [])
            if not (question.dd and question.complete)
            and question.value
            and question.value > 0
        ]
        return max(values, default=DEFAULT_DAILY_DOUBLE_WAGER_CAP)

    def get_dd_wager(self, player: object) -> bool | None:
        """Prompt the active player for a Daily Double wager.

        Args:
            player: Player currently controlling the Daily Double clue.

        Returns:
            ``False`` when the wager prompt is canceled; otherwise the method
            returns ``None`` after applying the wager to the active clue.
        """
        self.answering_player = player
        self.soliciting_player = False
        self._refresh_score_edit_controls()
        max_wager = max(self.answering_player.score, self._board_top_clue_value())
        wager_res = QInputDialog.getInt(
            self.host_display,
            "Wager",
            f"How much do they wager? (min: 5, max: ${max_wager})",
            min=5,
            max=max_wager,
        )
        if not wager_res[1]:
            self.soliciting_player = True
            self._refresh_score_edit_controls()
            return False
        wager = wager_res[0]
        self.active_question.value = wager
        self.keystroke_manager.activate("CORRECT_ANSWER", "INCORRECT_ANSWER")
        self.dc.question_widget.show_question()
        self._refresh_score_edit_controls()

    def load_image_review_screen(self, q: object) -> None:
        """Open the host-side image review screen for a clue.

        Args:
            q: Question object whose associated image should be reviewed.

        Returns:
            ``None``.
        """
        self.active_question = q
        self.host_display.load_image_review_screen(q)

    def load_question(self, q: object) -> None:
        """Load a clue into the displays and initialize per-question tracking.

        Args:
            q: Question object to present.

        Returns:
            ``None``.
        """
        self.clue_flow.load_question(q)

    def open_final(self) -> None:
        """Reveal the Final Jeopardy clue and enable answer entry.

        Returns:
            ``None``.
        """
        self.dc.question_widget.show_question()
        self.keystroke_manager.activate("FINAL_OPEN_RESPONSES")

    def correct_answer(self) -> None:
        """Apply a correct ruling to the active player's clue response.

        Returns:
            ``None``.
        """
        self.clue_flow.correct_answer()

    def incorrect_answer(self) -> None:
        """Apply an incorrect ruling to the active player's clue response.

        Returns:
            ``None``.
        """
        self.clue_flow.incorrect_answer()

    def stumped(self) -> None:
        """Handle a clue expiring without a correct response.

        The clue timer calls this from its own thread, so the work is sent to
        the game object's Qt thread through a signal.

        Returns:
            ``None``.
        """
        self.stumped_trigger.emit()

    def __handle_stumped_timeout(self) -> None:
        """Run stumped handling on the game object's Qt thread.

        The timeout is queued, so a buzz can be handled before it arrives.
        It is ignored unless the buzz window is still open and nobody is
        answering.

        Returns:
            ``None``.
        """
        if not self.accepting_responses or self.answering_player is not None:
            logging.info("Ignoring stumped timeout: responses are closed")
            return
        self.clue_flow.stumped()

    def reveal_stumped_answer(self) -> None:
        """Reveal the current clue answer before returning to the board.

        Returns:
            ``None``.
        """
        self.clue_flow.reveal_stumped_answer()

    def __toolate(self) -> None:
        """Notify the buzzer controller that the response window has ended.

        Returns:
            ``None``.
        """
        self.buzzer_controller.toolate()

    def __broadcast_lectern_update(
        self, player_number: object, state_dict: object
    ) -> None:
        """Send an updated state payload to a specific lectern slot.

        Args:
            player_number: Player slot whose lectern should receive the update.
            state_dict: Serialized player state payload to broadcast.

        Returns:
            ``None``.
        """
        if self.buzzer_controller:
            self.buzzer_controller.broadcast_to_lecterns(player_number, state_dict)

    def _update_lectern_for_player(
        self, player: object, buzzed: object = False, show_final_answer: object = False
    ) -> None:
        """Build and emit the latest lectern state for a player.

        Args:
            player: Player whose lectern state should be refreshed.
            buzzed: Whether the player is currently shown as having buzzed in.
            show_final_answer: Whether the player's Final Jeopardy answer should
                be included in the lectern state.

        Returns:
            ``None``.
        """
        self.player_state_broadcaster.update_player(
            player, buzzed=buzzed, show_final_answer=show_final_answer
        )

    def set_score(self, player: object, score: object) -> None:
        """Update a player's score and refresh related displays.

        Args:
            player: Player whose score should change.
            score: New numeric score to assign.

        Returns:
            ``None``.
        """
        self.player_state_broadcaster.set_score(player, score)

    def adjust_score(self, player: object) -> None:
        """Prompt the host to manually override a player's score.

        Args:
            player: Player whose score should be edited.

        Returns:
            ``None``.
        """
        if self.active_question is not None or self.soliciting_player:
            return
        (new_score, answered) = QInputDialog.getInt(
            self.host_display, "Adjust Score", "Enter a new score:", value=player.score
        )
        if answered:
            self.apply_manual_score_override(player, new_score)

    def close(self) -> None:
        """Stop audio playback and shut down the Qt application.

        Returns:
            ``None``.
        """
        self.song_player.stop()
        QApplication.quit()
