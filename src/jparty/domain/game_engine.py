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
import simpleaudio as sa
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QInputDialog

matplotlib.use("Agg")
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
    classify_buzz_phases,
    get_current_game_state,
    is_manual_score_adjustment,
    is_question_history_entry,
    load_general_state,
    load_question_history,
    reconstruct_score_history,
    save_general_state,
)
from jparty.services.game_loader import (
    build_game_from_board_selection_configs,
    standard_board_daily_double_indices,
)
from jparty.ui.widgets.common import CompoundObject, SongPlayer

# Preserve the historical module-level simpleaudio alias used by tests and
# older callers that patch ``jparty.domain.game_engine.sa`` directly.
SIMPLEAUDIO_MODULE = sa

QUESTION_INDEX_PART_COUNT = 2
DEFAULT_RESUME_ROUND_INDEX = 1
DEFAULT_DAILY_DOUBLE_J_ROUND_WAGER = 1000
DEFAULT_DAILY_DOUBLE_DJ_ROUND_WAGER = 2000


class Game(QObject):
    """Manage one active JParty game, including state, players, and flow."""

    buzz_trigger = pyqtSignal(int)
    new_player_trigger = pyqtSignal()
    stumped_trigger = pyqtSignal()
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
        self.toolate_trigger.connect(self.__toolate)
        self.lectern_update_trigger.connect(self.__broadcast_lectern_update)
        self._game_state_dir = None
        self._current_question_history = None
        self._all_buzz_attempts = []
        self._answer_attempts = []
        self._question_start_time = None
        self._open_responses_times = []
        self._successful_buzz_times = []
        self._game_started_at = None
        self._resume_state = None
        self._selected_round_indices = None
        self._board_selection_configs = None
        self._composed_board_selection_configs = None
        self._composed_game_data = None
        self._history_round_indices_original = False
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
        self._history_round_indices_original = False
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
        """
        from jparty.services.game_loader import get_game

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
        self._history_round_indices_original = bool(
            general_state.get("history_round_indices_original", False)
        )
        if not game_id:
            raise ValueError("Saved game metadata is missing a game_id")
        if not saved_players:
            raise ValueError("Saved game metadata is missing player information")
        board_selection_configs = general_state.get("board_selections")
        selected_round_indices = general_state.get("selected_round_indices")
        original_data = None
        is_original_subset_resume = False
        if board_selection_configs:
            source_game_ids = {
                str(selection.get("game_id", "")).strip()
                for selection in board_selection_configs
            }
            if source_game_ids == {game_id}:
                original_data = get_game(game_id)
                is_original_subset_resume = (
                    self._board_selections_match_original_game_subset(
                        game_id,
                        original_data,
                        board_selection_configs,
                        selected_round_indices,
                    )
                )
            if is_original_subset_resume:
                self.data = original_data
                self.set_selected_round_indices(selected_round_indices)
                self.set_board_selection_configs(board_selection_configs)
                self._normalize_resume_history_round_indices(
                    saved_game_path, general_state
                )
            else:
                self.data = build_game_from_board_selection_configs(
                    board_selection_configs
                )
                self.set_board_selection_configs(board_selection_configs)
        else:
            self.data = get_game(game_id)
            self.set_selected_round_indices(selected_round_indices)
            self.set_board_selection_configs(None)
            self._normalize_resume_history_round_indices(saved_game_path, general_state)
        self.set_reveal_answers_after_triple_stumper(
            general_state.get("reveal_answers_after_triple_stumper", False)
        )
        self.set_session_game_id(general_state.get("game_id", game_id))
        if board_selection_configs and not is_original_subset_resume:
            self.set_selected_round_indices(
                list(range(len(self.data.rounds))) if self.data else []
            )
        if not self.valid_game():
            raise ValueError("Saved game points to an invalid or incomplete game")
        self._resume_state = {
            "path": saved_game_path,
            "game_id": game_id,
            "general_state": general_state,
            "player_count": len(saved_players),
        }
        if self.buzzer_controller:
            self.buzzer_controller.begin_saved_player_reclaim(saved_players)
        return self._resume_state

    def _board_selections_match_original_game_subset(
        self,
        game_id: str,
        game_data: object,
        board_selection_configs: list[dict],
        selected_round_indices: object,
    ) -> bool:
        """Return whether saved board selections describe a simple original-game subset."""
        if not game_data or selected_round_indices is None:
            return False
        normalized_indices = [int(index) for index in selected_round_indices]
        if len(board_selection_configs) != len(normalized_indices):
            return False
        for selection, round_index in zip(
            board_selection_configs, normalized_indices, strict=False
        ):
            if str(selection.get("game_id", "")).strip() != game_id:
                return False
            if int(selection.get("source_round_index", -1)) != round_index:
                return False
            if not 0 <= round_index < len(game_data.rounds):
                return False
            round_data = game_data.rounds[round_index]
            expected_board_type = (
                "final" if isinstance(round_data, FinalBoard) else "standard"
            )
            if selection.get("board_type") != expected_board_type:
                return False
            expected_row_values = (
                []
                if isinstance(round_data, FinalBoard)
                else [
                    question.value
                    for question in sorted(
                        getattr(round_data, "questions", []),
                        key=lambda question: question.index,
                    )
                ][:5]
            )
            if list(selection.get("row_values", [])) != expected_row_values:
                return False
            expected_daily_double_indices = (
                []
                if isinstance(round_data, FinalBoard)
                else standard_board_daily_double_indices(round_data)
            )
            if selection.get(
                "daily_double_count", len(expected_daily_double_indices)
            ) != len(expected_daily_double_indices):
                return False
            if list(
                selection.get("daily_double_indices", expected_daily_double_indices)
            ) != (expected_daily_double_indices):
                return False
        return True

    def _normalize_resume_history_round_indices(
        self, saved_game_path: Path, general_state: dict
    ) -> None:
        """Rewrite legacy filtered-round history indices to original indices."""
        if self._history_round_indices_original:
            return
        selected_round_indices = general_state.get("selected_round_indices") or []
        if not selected_round_indices:
            self._history_round_indices_original = True
            return
        selected_round_indices = [int(index) for index in selected_round_indices]
        history_file = saved_game_path / "question_history.jsonl"
        if not history_file.exists():
            self._history_round_indices_original = True
            return
        entries = [
            json.loads(line)
            for line in history_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not entries:
            self._history_round_indices_original = True
            return

        def _legacy_index_detected(index: object) -> bool:
            return (
                isinstance(index, int)
                and 0 <= index < len(selected_round_indices)
                and index not in selected_round_indices
            )

        needs_remap = any(
            _legacy_index_detected(entry.get("round_index"))
            or _legacy_index_detected(
                entry.get("question_index", [None])[0]
                if isinstance(entry.get("question_index"), list | tuple)
                and entry.get("question_index")
                else None
            )
            or any(
                _legacy_index_detected(
                    buzz_attempt.get("question_index", [None])[0]
                    if isinstance(buzz_attempt.get("question_index"), list | tuple)
                    and buzz_attempt.get("question_index")
                    else None
                )
                for phase in entry.get("buzz_phases", [])
                for buzz_attempt in phase.get("buzz_attempts", [])
            )
            for entry in entries
        )
        if not needs_remap:
            self._history_round_indices_original = True
            return

        def _remap_index(index: object) -> object:
            if isinstance(index, int) and 0 <= index < len(selected_round_indices):
                return selected_round_indices[index]
            return index

        for entry in entries:
            entry["round_index"] = _remap_index(entry.get("round_index"))
            question_index = entry.get("question_index")
            if isinstance(question_index, list) and question_index:
                question_index[0] = _remap_index(question_index[0])
            for phase in entry.get("buzz_phases", []):
                for buzz_attempt in phase.get("buzz_attempts", []):
                    buzz_question_index = buzz_attempt.get("question_index")
                    if isinstance(buzz_question_index, list) and buzz_question_index:
                        buzz_question_index[0] = _remap_index(buzz_question_index[0])

        history_file.write_text(
            "\n".join(json.dumps(entry) for entry in entries) + "\n",
            encoding="utf-8",
        )
        general_state["history_round_indices_original"] = True
        (saved_game_path / "general.json").write_text(
            json.dumps(general_state, indent=2),
            encoding="utf-8",
        )
        self._history_round_indices_original = True

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

    def _restore_player_scores(self) -> None:
        """Restore each connected player's score from persisted history.

        Returns:
            ``None``.
        """
        score_history = self._reconstruct_score_history()
        for player in self.players:
            player_scores = score_history.get(player.player_number, [0])
            player.score = player_scores[-1] if player_scores else 0

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
        self._game_started_at = (
            resume_state["general_state"].get("started_at") or time.time()
        )
        self.players = self.buzzer_controller.claimed_saved_players()
        question_history = self._load_question_history()
        question_history.sort(key=lambda entry: entry.get("question_number", 0))
        self._mark_completed_questions(question_history)
        self._restore_player_scores()
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
            self.start_final()
        else:
            self.dc.board_widget.load_round(self.current_round)
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
        """Return the current game id from the process environment.

        Returns:
            The current ``JPARTY_GAME_ID`` value, or an empty string.
        """
        return self._session_game_id or os.environ.get("JPARTY_GAME_ID", "")

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
        return self._game_state_dir / "question_history.jsonl"

    def _append_history_entry(self, entry: dict) -> None:
        """Append a history record to the current session JSONL file.

        Args:
            entry: Serializable history entry to append.

        Returns:
            ``None``.
        """
        history_file = self._history_file()
        if history_file is None:
            logging.error("No game state directory available for history append")
            return
        try:
            with history_file.open("a") as file_obj:
                json.dump(entry, file_obj)
                file_obj.write("\n")
        except Exception as exc:
            logging.error("Error appending question history: %s", exc)

    def _write_history_entries(self, entries: list[dict]) -> None:
        """Rewrite the current session history file from memory.

        Args:
            entries: Complete ordered history entry list to persist.

        Returns:
            ``None``.
        """
        history_file = self._history_file()
        if history_file is None:
            logging.error("No game state directory available for history rewrite")
            return
        try:
            with history_file.open("w") as file_obj:
                for entry in entries:
                    json.dump(entry, file_obj)
                    file_obj.write("\n")
        except Exception as exc:
            logging.error("Error rewriting question history: %s", exc)

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
        return bool(self.get_recent_score_corrections(limit=1))

    def _history_attempt_order(self, entry: dict, player_results: dict) -> list[int]:
        """Build a stable player order for one clue's answer attempts.

        Args:
            entry: Existing clue history entry.
            player_results: Mapping of player index to corrected result state.

        Returns:
            Ordered player indices that should appear in ``answer_attempts``.
        """
        original_order = [
            attempt.get("player_index")
            for attempt in entry.get("answer_attempts", [])
            if attempt.get("player_index") is not None
        ]
        updated_order = [
            player_index
            for player_index in original_order
            if player_results.get(player_index, "no answer") != "no answer"
        ]
        remaining_players = sorted(
            player_index
            for player_index, result in player_results.items()
            if result != "no answer" and player_index not in updated_order
        )
        return updated_order + remaining_players

    def _history_player_results(self, entry: dict) -> dict[int, str]:
        """Return per-player result labels for a clue history entry.

        Args:
            entry: Persisted clue history entry.

        Returns:
            Mapping of player index to ``correct`` or ``incorrect``.
        """
        player_results = {}
        for attempt in entry.get("answer_attempts", []):
            player_index = attempt.get("player_index")
            if player_index is None:
                continue
            player_results[player_index] = (
                "correct" if attempt.get("answer_correct") else "incorrect"
            )
        return player_results

    def _history_attempts_by_player(self, entry: dict) -> dict[int, dict]:
        """Return a lookup of saved answer attempts keyed by player index.

        Args:
            entry: Persisted clue history entry.

        Returns:
            Mapping of player index to the saved attempt dictionary.
        """
        return {
            attempt.get("player_index"): deepcopy(attempt)
            for attempt in entry.get("answer_attempts", [])
            if attempt.get("player_index") is not None
        }

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

    def _rebuild_history_entries(self, entries: list[dict]) -> tuple[list[dict], dict]:
        """Recompute score-before/after values across all saved history events.

        Args:
            entries: Ordered history records to normalize.

        Returns:
            Tuple of ``(rewritten_entries, final_scores)``.
        """
        rewritten_entries = []
        scores = {}
        for entry in entries:
            updated_entry = deepcopy(entry)
            if is_manual_score_adjustment(updated_entry):
                player_index = updated_entry.get("player_index")
                if player_index is not None:
                    score_before = scores.get(player_index, 0)
                    score_after = updated_entry.get(
                        "new_score",
                        updated_entry.get("score_after", score_before),
                    )
                    updated_entry["score_before"] = score_before
                    updated_entry["score_after"] = score_after
                    updated_entry["new_score"] = score_after
                    scores[player_index] = score_after
                rewritten_entries.append(updated_entry)
                continue

            if not is_question_history_entry(updated_entry):
                rewritten_entries.append(updated_entry)
                continue

            value = int(updated_entry.get("value", 0) or 0)
            attempts_by_player = {
                attempt.get("player_index"): attempt
                for attempt in updated_entry.get("answer_attempts", [])
                if attempt.get("player_index") is not None
            }
            player_results = self._history_player_results(updated_entry)
            rebuilt_attempts = []
            for player_index in self._history_attempt_order(
                updated_entry, player_results
            ):
                original_attempt = attempts_by_player.get(player_index, {})
                score_before = scores.get(player_index, 0)
                score_after = (
                    score_before + value
                    if player_results[player_index] == "correct"
                    else score_before - value
                )
                rebuilt_attempts.append(
                    {
                        **original_attempt,
                        "player_index": player_index,
                        "answer_correct": player_results[player_index] == "correct",
                        "timestamp": original_attempt.get("timestamp", time.time()),
                        "score_before": score_before,
                        "score_after": score_after,
                    }
                )
                scores[player_index] = score_after
            updated_entry["answer_attempts"] = rebuilt_attempts
            rewritten_entries.append(updated_entry)
        return rewritten_entries, scores

    def _sync_scores_from_history_entries(self, entries: list[dict]) -> None:
        """Apply final replayed scores from persisted history to live players.

        Args:
            entries: Ordered history records that should define live totals.

        Returns:
            ``None``.
        """
        _, final_scores = self._rebuild_history_entries(entries)
        for player in self.players:
            self.set_score(player, final_scores.get(player.player_number, 0))
        self._refresh_score_edit_controls()

    def get_recent_score_corrections(self, limit: int = 5) -> list[dict]:
        """Return recent standard-clue history entries for the score editor.

        Args:
            limit: Maximum number of clue entries to return.

        Returns:
            Newest-first list of score-correction view models.
        """
        entries = self._load_question_history()
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
                player.player_number: self._history_player_results(entry).get(
                    player.player_number, "no answer"
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
        """Rewrite saved clue history after host score-correction edits.

        Args:
            corrections: Edited clue payloads keyed by ``question_number``.

        Returns:
            ``True`` when any saved history changed.
        """
        if not corrections:
            return False
        correction_map = {
            correction["question_number"]: correction for correction in corrections
        }
        entries = self._load_question_history()
        changed = False
        updated_entries = []
        for entry in entries:
            if not is_question_history_entry(entry):
                updated_entries.append(deepcopy(entry))
                continue
            question_number = entry.get("question_number")
            correction = correction_map.get(question_number)
            updated_entry = deepcopy(entry)
            if correction is not None:
                original_player_results = self._history_player_results(entry)
                original_entry_states = {
                    player.player_number: original_player_results.get(
                        player.player_number, "no answer"
                    )
                    for player in self.players
                }
                corrected_player_results = {
                    int(player_index): result
                    for player_index, result in correction["player_states"].items()
                }
                if corrected_player_results != original_entry_states:
                    changed = True
                attempts_by_player = self._history_attempts_by_player(entry)
                updated_entry["answer_attempts"] = [
                    {
                        **attempts_by_player.get(player_index, {}),
                        "player_index": player_index,
                        "answer_correct": corrected_player_results[player_index]
                        == "correct",
                        "timestamp": attempts_by_player.get(player_index, {}).get(
                            "timestamp", time.time()
                        ),
                    }
                    for player_index in self._history_attempt_order(
                        entry, corrected_player_results
                    )
                    if corrected_player_results[player_index] != "no answer"
                ]
                if updated_entry.get("is_daily_double"):
                    corrected_value = int(correction["value"])
                    if corrected_value != int(entry.get("value", 0) or 0):
                        changed = True
                    updated_entry["value"] = corrected_value
            updated_entries.append(updated_entry)

        if not changed:
            return False
        rebuilt_entries, _ = self._rebuild_history_entries(updated_entries)
        self._write_history_entries(rebuilt_entries)
        self._sync_scores_from_history_entries(rebuilt_entries)
        return True

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
        """
        self.players.remove(player)
        player.waiter.close()
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

    def _update_player_numbers(self) -> None:
        """Renumber players and remap their keyboard shortcuts by position.

        Returns:
            ``None``.
        """
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
            if getattr(self.dc, "final_window", None) is None:
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
        """
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

        Returns:
            ``None``.
        """
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
        self.final_jeopardy_flow.generate_final_score_graphs()

    def _load_question_history(self) -> object:
        """Load saved per-question history for the current game session.

        Returns:
            A list of persisted question history entries.
        """
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
        original_player_map = {
            p.get("player_number"): p.get("name", f"Player {p.get('player_number')}")
            for p in general_state.get("players", [])
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
        game_id = os.environ.get("JPARTY_GAME_ID", "unknown")
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
        self.buzzer_controller.restart()
        if self.buzzer_controller:
            for player_number in list(
                self.buzzer_controller.lectern_connections.keys()
            ):
                if player_number in self.buzzer_controller.lectern_connections:
                    try:
                        self.buzzer_controller.lectern_connections[player_number].send(
                            "NO_PLAYER", ""
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
        self.timer = None
        self.data = None
        self._judgement_round = 0
        self.early_buzzes = set()
        self.responses_open_time = None
        self.dc.restart()
        self.begin()
        self._refresh_score_edit_controls()

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
        try:
            logging.info(f"Current round is: {self.current_round}")
            logging.info(f"Rounds are {self.data.rounds}")
            round_index = self.data.rounds.index(self.current_round)
        except (AttributeError, ValueError):
            round_index = DEFAULT_RESUME_ROUND_INDEX
        max_wager = max(
            self.answering_player.score,
            DEFAULT_DAILY_DOUBLE_J_ROUND_WAGER
            if round_index == 0
            else DEFAULT_DAILY_DOUBLE_DJ_ROUND_WAGER,
        )
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

        Returns:
            ``None``.
        """
        self.stumped_trigger.emit()

    def __handle_stumped_timeout(self) -> None:
        """Run stumped handling on the game object's Qt thread.

        Returns:
            ``None``.
        """
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
