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

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox, QWidget

from jparty import __version__
from jparty.app.paths import GAME_STATES_DIR, TOURNAMENTS_DIR
from jparty.domain.gameplay import (
    ClueFlow,
    FinalJeopardyFlow,
    PlayerStateBroadcaster,
    ScoreRecorder,
    TiebreakerFlow,
)
from jparty.domain.input import (
    MAX_PLAYERS,
    KeystrokeManager,
    QuestionTimer,
    index_to_key,
)
from jparty.domain.models import FinalBoard
from jparty.domain.state import (
    HISTORY_FORMAT,
    NO_ANSWER_RESULT,
    PLAYER_RENUMBER_TYPE,
    QUESTION_HISTORY_FILE_NAME,
    HistoryFileError,
    LoadedSave,
    build_end_game_summary,
    build_score_correction_lines,
    classify_buzz_phases,
    clue_player_results,
    corrected_history_entries,
    current_saved_players,
    get_current_game_state,
    history_score_totals,
    is_question_history_entry,
    is_tiebreaker_clue,
    load_question_history,
    load_saved_game_data,
    question_for_history_entry,
    read_history_file,
    save_general_state,
    tiebreaker_winner_number,
)
from jparty.domain.tournament.advancement import TiebreakerSession
from jparty.domain.tournament.dropouts import Dropout, dropped_ids
from jparty.domain.tournament.play import (
    SAVED_PLAYER_ID,
    SAVED_PLAYER_NAME,
    GameResult,
    PlayerOutcome,
    TournamentGameRef,
    already_recorded,
    game_results,
)
from jparty.domain.tournament.saves import saved_game_problem, tournament_save
from jparty.domain.tournament.store import (
    TournamentFileError,
    load_dropouts,
    load_results,
    record_game_results,
    record_tiebreak,
)
from jparty.services.game_loader import (
    build_game_from_board_selection_configs,
    load_tiebreaker_clues,
)
from jparty.ui.widgets.common import CompoundObject, SongPlayer

DEFAULT_DAILY_DOUBLE_WAGER_CAP = 1000
MIN_DAILY_DOUBLE_WAGER = 5


def board_top_clue_value(board: object) -> int:
    """Return the highest clue value on ``board``, for the Daily Double cap.

    Played Daily Doubles are skipped, because their value is replaced by
    the wager. Unplayed ones (including the one being wagered on) still
    hold their row value and count, so a board whose top row is all
    Daily Doubles still caps at that row. The cap comes from the board
    itself, not from the round's position, since a game can start with
    any selected round.

    Args:
        board: Standard board whose clue values set the cap.

    Returns:
        The highest clue value, or the standard first-round cap when the
        board has no usable values.
    """
    values = [
        question.value
        for question in getattr(board, "questions", [])
        if not (question.dd and question.complete)
        and question.value
        and question.value > 0
    ]
    return max(values, default=DEFAULT_DAILY_DOUBLE_WAGER_CAP)


def dd_wager_bounds(score_before: int, board: object) -> tuple[int, int]:
    """Return the allowed Daily Double wager range for one player.

    A player may wager from $5 up to their score or the board's top clue
    value, whichever is larger. The maximum is never below the $5 minimum,
    even on a custom board whose clues are all worth less.

    Args:
        score_before: The player's score just before the Daily Double.
        board: Board the Daily Double is on.

    Returns:
        ``(minimum, maximum)`` wager.
    """
    maximum = max(score_before, board_top_clue_value(board), MIN_DAILY_DOUBLE_WAGER)
    return MIN_DAILY_DOUBLE_WAGER, maximum


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


def _tournament_save_problem(path: Path, general_state: dict) -> str | None:
    """Return why a tournament game's save can't resume as one, or ``None``.

    ``None`` for a regular game's save. This reads the tournament's files,
    so it runs with the rest of :meth:`Game.read_saved_game`.

    Args:
        path: The saved game's folder.
        general_state: Its decoded ``general.json``.

    Returns:
        A message for the host, or ``None``.
    """
    save = tournament_save(path, general_state)
    ref = TournamentGameRef.from_json(general_state.get("tournament"))
    if save is None or ref is None:
        return None
    return saved_game_problem(TOURNAMENTS_DIR / ref.tournament, save)


def _results_problem(
    ref: TournamentGameRef,
    saved: list[GameResult],
    dropouts: list[Dropout],
    results: list[GameResult],
    saved_game: str,
) -> str | None:
    """Return why a finished game's results mustn't be logged, or ``None``.

    Args:
        ref: The tournament game.
        saved: Every result already in results.csv.
        dropouts: Every dropout.
        results: The game's new rows.
        saved_game: The game's save folder name.

    Returns:
        A message for the host, or ``None``.
    """
    others = sorted(
        {r.saved_game for r in saved if r.game_key == ref.game_key} - {saved_game}
    )
    if others:
        return (
            f"{ref.game_key} already has results from another saved game "
            f"({', '.join(others)}), so this game's results weren't saved over "
            "them. Use Fix Results in the tournament if this game should count."
        )
    dropped = dropped_ids(dropouts)
    gone = [r.player for r in results if r.player_id in dropped]
    if gone:
        return (
            f"{', '.join(gone)} dropped out of the {ref.tournament} tournament, "
            f"so the results of {ref.game_key} weren't saved."
        )
    return None


class Game(QObject):
    """Manage one active JParty game, including state, players, and flow."""

    buzz_trigger = pyqtSignal(int)
    new_player_trigger = pyqtSignal()
    stumped_trigger = pyqtSignal()
    final_finished_trigger = pyqtSignal()
    wager_trigger = pyqtSignal(int, int)
    answer_trigger = pyqtSignal(object, str)
    toolate_trigger = pyqtSignal()
    lectern_update_trigger = pyqtSignal(int, dict)
    tiebreaker_loaded_trigger = pyqtSignal(int, str, object)

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
        # True only between start_final and the Final clue being shown.
        self.final_wagers_open = False
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
            "FORCE_OPEN_FINAL", Qt.Key.Key_Return, self.force_open_final
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
        self.keystroke_manager.addEvent(
            "START_TIEBREAKER",
            Qt.Key.Key_Space,
            self.start_tiebreaker,
            self.spacehints,
        )
        self.keystroke_manager.addEvent(
            "TIEBREAKER_SHOW_CLUE",
            Qt.Key.Key_Space,
            self.tiebreaker_show_clue,
            self.spacehints,
        )
        self.keystroke_manager.addEvent(
            "TIEBREAKER_REVEAL_ANSWER",
            Qt.Key.Key_Space,
            self.tiebreaker_reveal_answer,
            self.spacehints,
        )
        self.keystroke_manager.addEvent(
            "TIEBREAKER_NEXT_CLUE",
            Qt.Key.Key_Space,
            self.tiebreaker_next_clue,
            self.spacehints,
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
        self.answer_trigger.connect(self.answer)
        self.buzz_trigger.connect(self.buzz)
        self.new_player_trigger.connect(self.new_player)
        self.stumped_trigger.connect(self.__handle_stumped_timeout)
        self.final_finished_trigger.connect(self.__handle_final_finished_song)
        self.toolate_trigger.connect(self.__toolate)
        self.lectern_update_trigger.connect(self.__broadcast_lectern_update)
        self.tiebreaker_loaded_trigger.connect(self.__handle_tiebreaker_loaded)
        self._game_state_dir = None
        # Whether this session's history has a non-Final clue the score
        # editor can change. Kept in memory so refreshing the Edit Score
        # button never re-reads the history file.
        self._has_editable_clue = False
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
        self.tiebreaker_flow = TiebreakerFlow(self)
        # Player who won a tiebreaker, or None. The scores stay tied; the
        # saved tiebreaker_clue line is what records the win.
        self.tiebreaker_winner = None
        self._reset_tournament_state()
        # Replaced in tests so loading runs without a thread or network.
        self.load_tiebreaker_clues = load_tiebreaker_clues

    def _reset_tournament_state(self) -> None:
        """Forget the tournament game, tiebreaker session, and /host code.

        Returns:
            ``None``.
        """
        # The tournament game being played, or None for a regular game. Its
        # results go to the tournament's results.csv when the game ends.
        self.tournament_game = None
        # A tournament tiebreaker played outside any game, or None; see
        # start_tiebreaker_session. Its tied player id by phone.
        self.tiebreaker_session = None
        # Whether the /host QR code was shown this game, and whether it's
        # on the host's screen now; see _show_host_code.
        self.host_code_done = False
        self.host_code_shown = False
        self._session_player_ids = {}

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
        self._reset_tournament_state()
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
        """Store the round indices selected for play.

        The indices point into ``data.rounds``. Before Start in regular mode
        that is the loaded source game, so they are its round numbers; see
        :meth:`selected_round_indices` for what Start changes.

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

    def set_tournament_game(
        self,
        ref: TournamentGameRef | None,
        players: list[tuple[str, str]] | None = None,
    ) -> None:
        """Make the next fresh game a tournament game, or a regular one.

        Args:
            ref: The tournament game, or ``None`` for a regular game.
            players: ``(player_id, actual_name)`` for each podium, in seat
                order. Seat ``i`` is the ``i``-th connected player. Ignored
                when ``ref`` is ``None``.

        Returns:
            ``None``.

        Raises:
            ValueError: If ``ref`` is set and the number of ``players``
                doesn't match the connected players. Pairing them anyway
                would log one player's results under another's name.
        """
        choices = list(players or []) if ref is not None else []
        if ref is not None and len(choices) != len(self.players):
            raise ValueError(
                f"{ref.game_key} needs one player per phone: "
                f"{len(choices)} players for {len(self.players)} phones"
            )
        self.tournament_game = ref
        seated = sorted(self.players, key=lambda player: player.player_number)
        for index, player in enumerate(seated):
            player.tournament_player = (
                tuple(choices[index]) if index < len(choices) else None
            )

    def _restore_tournament_players(self, raw_history: list[dict]) -> None:
        """Give resumed players back their tournament player ids.

        A resumed game's players are new objects from the phones, so they
        don't carry the ids :meth:`set_tournament_game` gave them. The saved
        roster has them, under the seat each player had when the game
        started; seat changes in the history move them to the current seat.

        Args:
            raw_history: The saved game's history, in file order.

        Returns:
            ``None``.
        """
        if self.tournament_game is None:
            return
        by_seat = {}
        for saved in current_saved_players(self._starting_roster or [], raw_history):
            player_id = saved.get(SAVED_PLAYER_ID)
            if player_id:
                by_seat[saved.get("player_number")] = (
                    str(player_id),
                    str(saved.get(SAVED_PLAYER_NAME) or ""),
                )
        for player in self.players:
            player.tournament_player = by_seat.get(player.player_number)

    def record_tournament_results(self) -> None:
        """Log a finished tournament game's results to its results.csv.

        Called once the winner is known: after Final Jeopardy, or after a
        tiebreaker. Does nothing for a regular game. A resumed game that
        already logged its results leaves them alone, since the host may
        have fixed them. Results that would replace another save's rows for
        the game, or that name a player who dropped out, aren't saved; the
        host is warned instead.

        Returns:
            ``None``.
        """
        ref = self.tournament_game
        if ref is None or not self._game_state_dir:
            return
        try:
            summary = build_end_game_summary(self)
            history = self._load_question_history()
        except HistoryFileError as error:
            self.show_history_error(error)
            return
        saved_game = Path(self._game_state_dir).name
        folder = TOURNAMENTS_DIR / ref.tournament
        saved_players = current_saved_players(
            get_current_game_state(self)["players"], history
        )
        results = game_results(
            ref,
            saved_players,
            [
                PlayerOutcome(stats.player_number, stats.final_score, stats.coryat)
                for stats in summary.current_players
            ],
            summary.winner_player_numbers,
            str(self.current_game_id() or ""),
            saved_game,
        )
        try:
            saved = load_results(folder)
            if already_recorded(saved, ref.game_key, saved_game):
                logging.info("Results for %s are already saved", ref.game_key)
                return
            problem = _results_problem(
                ref, saved, load_dropouts(folder), results, saved_game
            )
            if problem:
                logging.error("Not saving results for %s: %s", ref.game_key, problem)
                self.show_host_warning("Results Not Saved", problem)
                return
            record_game_results(folder, results)
        except TournamentFileError as error:
            logging.error("Couldn't save tournament results: %s", error)
            self.show_host_warning(
                "Results Not Saved",
                f"Couldn't save the results of {ref.game_key} to the "
                f"{ref.tournament} tournament: {error}",
            )
            return
        logging.info("Saved results for %s", ref.game_key)

    def start_tiebreaker_session(self, session: TiebreakerSession) -> None:
        """Play a tournament tiebreaker between the connected phones.

        There's no board: the tie card shows, and Space asks for a game to
        take tiebreaker clues from, as after a tied Final (see
        :class:`jparty.domain.gameplay.TiebreakerFlow`). The win is saved to
        the tournament's ``tiebreaks.csv``. Nothing is written to the saved
        games, so the session can't be resumed; Cancel returns to the lobby.

        Args:
            session: The tie. Phone ``i`` plays as ``session.players[i]``.

        Raises:
            ValueError: If the number of phones doesn't match the tied
                players.
        """
        seated = sorted(self.players, key=lambda player: player.player_number)
        if len(seated) != len(session.players):
            raise ValueError(
                f"The tiebreaker needs one phone per tied player: "
                f"{len(session.players)} players for {len(seated)} phones"
            )
        logging.info("Starting a tiebreaker for %s", session.description)
        self.tournament_game = None
        # Nothing about the session is saved as a game, so make sure no
        # earlier save folder is written into.
        self._game_state_dir = None
        self.tiebreaker_session = session
        self._session_player_ids = {
            player: player_id
            for player, (player_id, _name) in zip(seated, session.players, strict=True)
        }
        self.dc.hide_welcome_widgets()
        self.buzzer_controller.accepting_players = False
        self.song_player.stop()
        self.song_player.keep_output_awake()
        self.dc.load_final_judgement()
        self.dc.final_window.show_tie()
        self.tiebreaker_flow.contenders = seated
        self.keystroke_manager.activate("START_TIEBREAKER")
        self._refresh_score_edit_controls()

    def record_tiebreaker_session(self, winner: object) -> None:
        """Save the winner of a tiebreaker session to ``tiebreaks.csv``.

        Args:
            winner: The phone that won.

        Returns:
            ``None``.
        """
        session = self.tiebreaker_session
        if session is None or winner not in self._session_player_ids:
            return
        tiebreak = session.tiebreak(self._session_player_ids[winner])
        try:
            record_tiebreak(TOURNAMENTS_DIR / session.tournament, tiebreak)
        except TournamentFileError as error:
            logging.error("Couldn't save the tiebreaker: %s", error)
            self.show_host_warning(
                "Tiebreaker Not Saved",
                f"Couldn't save the tiebreaker for {session.description}: {error}",
            )
            return
        logging.info("Saved the tiebreaker for %s", session.description)

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
        """Return the selected round indices for this session.

        These always point into ``data.rounds``, the same numbering that
        history ``round_index`` values use. When a game starts from board
        selections, ``data`` becomes the built game holding only the chosen
        boards and every one of its rounds is selected (``0..n-1``), in
        regular and advanced mode alike.

        Returns:
            Selected zero-based round indices, or all currently loaded rounds
            when no explicit selection has been stored.
        """
        if self._selected_round_indices is not None:
            return list(self._selected_round_indices)
        if self.data is None:
            return []
        return list(range(len(self.data.rounds)))

    def prepare_resume_from_dir(self, saved_game_dir: object) -> object:
        """Load enough metadata to resume a previously saved game session.

        This is :meth:`read_saved_game` followed by
        :meth:`apply_saved_game`. The welcome screen calls the two halves
        separately so the slow read can run on a worker thread.

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
            HistoryFileError: If the saved clue history cannot be read.
        """
        return self.apply_saved_game(self.read_saved_game(saved_game_dir))

    def read_saved_game(self, saved_game_dir: object) -> LoadedSave:
        """Read and validate a saved game without changing this game.

        This can fetch the game from J-Archive or Google Sheets, so it may be
        slow. It never touches ``self``, so it is safe to run on a worker
        thread. A save that fails any check raises here, before anything is
        applied, so a failed Load Saved leaves the current game as it was.

        Args:
            saved_game_dir: Filesystem path to a saved game directory containing
                at least ``general.json`` and related session files.

        Returns:
            The validated save, ready for :meth:`apply_saved_game`.

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
        # so a damaged save fails right away.
        history_entries = read_history_file(
            saved_game_path / QUESTION_HISTORY_FILE_NAME
        )
        current_players = current_saved_players(saved_players, history_entries)
        saved_game = load_saved_game_data(general_state)
        if saved_game.data is None or not saved_game.data.rounds:
            raise ValueError("Saved game points to an invalid or incomplete game")
        return LoadedSave(
            path=saved_game_path,
            game_id=game_id,
            general_state=general_state,
            saved_game=saved_game,
            current_players=current_players,
            tournament_problem=_tournament_save_problem(saved_game_path, general_state),
        )

    def apply_saved_game(self, loaded: LoadedSave) -> object:
        """Make a save read by :meth:`read_saved_game` the game to resume.

        Call this on the UI thread. It does no I/O and cannot fail on a
        validated save.

        Args:
            loaded: Save returned by :meth:`read_saved_game`.

        Returns:
            A dictionary describing the loaded resume state.
        """
        general_state = loaded.general_state
        self.data = loaded.saved_game.data
        self.set_board_selection_configs(loaded.saved_game.board_selection_configs)
        self.set_selected_round_indices(loaded.saved_game.selected_round_indices)
        self.set_reveal_answers_after_triple_stumper(
            general_state.get("reveal_answers_after_triple_stumper", False)
        )
        self.set_session_game_id(general_state.get("game_id", loaded.game_id))
        # A tournament game keeps logging its results when resumed; the
        # player ids are on the saved players list. A save that can no
        # longer be resumed as one resumes as a regular game instead.
        self.tournament_game = (
            None
            if loaded.tournament_problem
            else TournamentGameRef.from_json(general_state.get("tournament"))
        )
        self._resume_state = {
            "path": loaded.path,
            "game_id": loaded.game_id,
            "general_state": general_state,
            "player_count": len(general_state.get("players", [])),
        }
        if self.buzzer_controller:
            self.buzzer_controller.begin_saved_player_reclaim(loaded.current_players)
        return self._resume_state

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
            # The built game holds only the chosen boards. Number its rounds
            # by position, as history round_index values do, so every round
            # is played (Final included) and resume rebuilds the same game.
            if self.data:
                self._selected_round_indices = list(range(len(self.data.rounds)))
        # Without board selections the whole game stays loaded and the
        # selected indices already point into it.
        playable_round_indices = self._playable_round_indices()
        if not playable_round_indices:
            logging.warning("No rounds selected for play")
            return
        self.current_round = self.data.rounds[playable_round_indices[0]]
        self.dc.hide_welcome_widgets()
        self.buzzer_controller.accepting_players = False
        self.song_player.stop()
        self.song_player.keep_output_awake()
        self._game_started_at = time.time()
        self._history_format = HISTORY_FORMAT
        self._started_by_version = __version__
        self._starting_roster = None
        self._has_editable_clue = False
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
            question = question_for_history_entry(self.data, entry)
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
        # Standard boards come first, then Finals in order, so a save with
        # several Finals resumes at the first one not yet judged.
        for want_final in (False, True):
            for round_index in playable_round_indices:
                round_data = self.data.rounds[round_index]
                if isinstance(round_data, FinalBoard) != want_final:
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
        self._has_editable_clue = False
        self._clear_pending_history()
        self._game_started_at = (
            resume_state["general_state"].get("started_at") or time.time()
        )
        # Keep the format and version the save was started with.
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
        self._has_editable_clue = any(
            self._is_editable_clue_entry(entry) for entry in question_history
        )
        self._mark_completed_questions(question_history)
        self._restore_player_scores(raw_history)
        self._restore_tournament_players(raw_history)
        # Tiebreaker clues use question numbers too, so continue after them.
        numbered_entries = question_history + [
            entry for entry in raw_history if is_tiebreaker_clue(entry)
        ]
        if numbered_entries:
            self.question_number = (
                max(entry.get("question_number", 0) for entry in numbered_entries) + 1
            )
        else:
            self.question_number = 1
        # A tiebreaker won before the app closed still decides the game.
        saved_winner_number = tiebreaker_winner_number(raw_history)
        self.tiebreaker_winner = next(
            (
                player
                for player in self.players
                if player.player_number == saved_winner_number
            ),
            None,
        )
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
        self.song_player.keep_output_awake()
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
            ``None`` when no active clue is available or a tiebreaker clue
            is being played.
        """
        if not self.active_question or not self.data:
            return None
        # A tiebreaker clue comes from another game, so it has no place in
        # this game's rounds.
        if self.tiebreaker_flow.active:
            return None
        try:
            round_index = self.data.rounds.index(self.current_round)
            return (round_index, self.active_question.index)
        except (ValueError, AttributeError):
            return None

    def _initialize_game_state_dir(self) -> None:
        """Create a new, empty save directory for the current game session.

        Every fresh session gets its own folder. When a folder for the same
        game id and minute already exists (for example a second Start within
        the same minute), a ``-2``, ``-3``, ... suffix is added instead of
        reusing it, so one session never writes into another's save.

        Returns:
            ``None``.
        """
        game_id = self.current_game_id()
        if not game_id:
            return
        base_name = self._game_state_dir_name(game_id)
        GAME_STATES_DIR.mkdir(parents=True, exist_ok=True)
        suffix = 1
        while True:
            name = base_name if suffix == 1 else f"{base_name}-{suffix}"
            candidate = GAME_STATES_DIR / name
            try:
                candidate.mkdir(exist_ok=False)
            except FileExistsError:
                suffix += 1
                continue
            break
        self._game_state_dir = candidate
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
        # Queued lines count too: the score editor already shows them.
        if self._is_editable_clue_entry(entry):
            self._has_editable_clue = True
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

        This runs on every Edit Score button refresh, so it uses an in-memory
        flag instead of reading the history file. The file is read only when
        the dialog opens, which is also where a damaged file is reported.

        Returns:
            ``True`` when there is saved non-final clue history and no active
            clue interaction is in progress.
        """
        if self.active_question is not None or self.soliciting_player:
            return False
        # A tie for first fixes who plays the tiebreaker, so a later edit
        # could leave the wrong players in it or a winner the summary
        # disagrees with.
        if self.tiebreaker_flow.locks_scores():
            return False
        return self._has_editable_clue

    def _is_editable_clue_entry(self, entry: dict) -> bool:
        """Return whether the score editor can change this history entry.

        Args:
            entry: History line.

        Returns:
            ``True`` for a played clue on a standard (non-Final) board.
        """
        if not is_question_history_entry(entry):
            return False
        if self._question_from_history_entry(entry) is None:
            return False
        return not isinstance(self.data.rounds[entry["round_index"]], FinalBoard)

    def _question_from_history_entry(self, entry: dict) -> object:
        """Resolve the question object referenced by a saved clue history entry.

        Args:
            entry: Persisted clue history entry.

        Returns:
            Matching question object, or ``None`` when unavailable.
        """
        return question_for_history_entry(self.data, entry)

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
            if not self._is_editable_clue_entry(entry):
                continue
            question = self._question_from_history_entry(entry)
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
                    "wager_bounds": self._history_dd_wager_bounds(entry),
                    "player_states": player_states,
                }
            )
        recent_entries.sort(
            key=lambda entry: entry.get("question_number", 0), reverse=True
        )
        return recent_entries[:limit]

    def _history_dd_wager_bounds(self, entry: dict) -> tuple[int, int] | None:
        """Return the wager range a saved Daily Double was played under.

        Args:
            entry: Corrected clue history entry.

        Returns:
            ``(minimum, maximum)`` from :func:`dd_wager_bounds`, using the
            player's score just before the clue, or ``None`` for a regular
            clue. If no one is ruled on the clue any more, the score is taken
            as 0, so the cap is the board's top value.
        """
        if not entry.get("is_daily_double"):
            return None
        attempts = entry.get("answer_attempts") or [{}]
        score_before = int(attempts[0].get("score_before") or 0)
        return dd_wager_bounds(score_before, self.data.rounds[entry["round_index"]])

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
        correction_lines = build_score_correction_lines(
            self._load_question_history(),
            corrections,
            [player.player_number for player in self.players],
            time.time(),
        )
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
        self._update_all_lecterns()

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
        # The removed player's seat, or the last seat after renumbering, is
        # now empty, so its lectern goes back to the logo.
        self._update_all_lecterns()

    def move_player_up(self, player: object) -> None:
        """Move a player one slot earlier in the roster order.

        Args:
            player: Connected player object to reorder.

        Returns:
            ``None``.
        """
        self._move_player(player, -1)

    def move_player_down(self, player: object) -> None:
        """Move a player one slot later in the roster order.

        Args:
            player: Connected player object to reorder.

        Returns:
            ``None``.
        """
        self._move_player(player, 1)

    def _move_player(self, player: object, offset: int) -> None:
        """Swap a player with the neighbour ``offset`` seats away.

        Args:
            player: Connected player object to reorder.
            offset: ``-1`` for one seat earlier, ``1`` for one seat later.

        Returns:
            ``None``.
        """
        if player not in self.players:
            return
        if self._in_saved_player_reclaim_mode():
            self._move_saved_player(player, offset)
            return
        index = self.players.index(player)
        other = index + offset
        if not 0 <= other < len(self.players):
            return
        (self.players[index], self.players[other]) = (
            self.players[other],
            self.players[index],
        )
        self._update_player_numbers()
        self.dc.scoreboard.refresh_players()
        self._refresh_score_edit_controls()
        self._update_all_lecterns()
        # A tournament game seats podium i as the i-th phone, so the welcome
        # screen shows the new order.
        welcome = getattr(self.host_display, "welcome_widget", None)
        if welcome is not None:
            welcome.check_start()

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

    def has_later_round(self) -> bool:
        """Return whether a selected round comes after the current one.

        Returns:
            ``True`` when another playable round follows ``current_round``.
        """
        if not self.data or self.current_round not in self.data.rounds:
            return False
        i = self.data.rounds.index(self.current_round)
        return any(index > i for index in self._playable_round_indices())

    def next_round(self) -> None:
        """Advance from the current round to the next round in the game.

        In a tournament game, the first Space after the first board shows the
        host the ``/host`` page's QR code instead; the next Space moves on.

        Returns:
            ``None``.
        """
        logging.info("next round")
        if self.host_code_shown:
            self.host_code_shown = False
            self.host_display.hide_host_code()
        elif self._show_host_code():
            self.keystroke_manager.activate("NEXT_ROUND")
            return
        playable_round_indices = self._playable_round_indices()
        i = self.data.rounds.index(self.current_round)
        logging.info(f"ROUND {i}")
        future_round_indices = [
            round_index for round_index in playable_round_indices if round_index > i
        ]
        if not future_round_indices:
            # Only reached from a regular board: a Final round with no later
            # round ends through FinalJeopardyFlow, so no final window exists
            # yet.
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

    def _show_host_code(self) -> bool:
        """Show the ``/host`` QR code after a tournament game's first board.

        It's shown once per game, only when another round follows.

        Returns:
            Whether the code is now showing.
        """
        if (
            self.tournament_game is None
            or self.host_code_done
            or self.buzzer_controller is None
            or not hasattr(self.host_display, "load_host_code")
        ):
            return False
        playable = self._playable_round_indices()
        index = self.data.rounds.index(self.current_round)
        if not playable or index != playable[0] or not self.has_later_round():
            return False
        try:
            host = self.buzzer_controller.host()
        except OSError:
            logging.warning("No network address for the host page", exc_info=True)
            return False
        self.host_code_done = True
        self.host_code_shown = True
        self.host_display.load_host_code(host)
        return True

    def start_final(self) -> None:
        """Begin the Final Jeopardy wagering phase.

        Returns:
            ``None``.
        """
        logging.info("start final")
        for player in self.players:
            self.dc.player_widget(player).set_lights(True)
        self.final_wagers_open = True
        self.buzzer_controller.open_wagers()
        # Lets the host open Final without waiting on a missing wager.
        self.keystroke_manager.activate("FORCE_OPEN_FINAL")
        self._refresh_score_edit_controls()

    def wager(self, i_player: object, amount: object) -> None:
        """Record a Final Jeopardy wager from a player.

        Args:
            i_player: Zero-based player index submitting the wager.
            amount: Wager amount chosen by the player. It is clamped to
                ``0..max(score, 0)``.

        Returns:
            ``None``.

        A wager that arrives after the clue is shown is ignored. The server
        can accept a wager just before the host presses Enter, and its signal
        reaches this thread just after, when the forced 0 must stand.
        """
        player = self.players[i_player]
        if not self.final_wagers_open:
            logging.info(f"Ignoring {player}'s wager; the Final clue is open")
            return
        amount = player.clamp_final_wager(amount)
        player.wager = amount
        self.dc.player_widget(player).set_lights(False)
        logging.info(f"{player} wagered {amount}")
        if all(p.wager is not None for p in self.players):
            self.host_display.question_widget.hint_label.setText(
                "Press space to show clue!"
            )
            self.keystroke_manager.deactivate("FORCE_OPEN_FINAL")
            self.keystroke_manager.activate("OPEN_FINAL")

    def force_open_final(self) -> None:
        """Open the Final clue now, counting any missing wager as 0.

        Bound to the host's Enter key while Final wagers are open. It covers
        players who cannot wager (a dead phone, someone who left), so the game
        is never stuck waiting. Their wager prompts are closed so a late wager
        from their phone is ignored.

        Returns:
            ``None``.
        """
        for player in self.players:
            if player.wager is None:
                player.wager = 0
                self.dc.player_widget(player).set_lights(False)
                logging.info(f"{player} did not wager; host counted it as 0")
        self.buzzer_controller.close_wagers()
        self.keystroke_manager.deactivate("OPEN_FINAL")
        self.open_final()

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

    def prompt_tiebreaker_game_id(self) -> str | None:
        """Ask the host which game to take tiebreaker clues from.

        Returns:
            The game id the host typed, ``""`` for a random game, or ``None``
            when the host cancelled and the game should end in a tie.
        """
        # Signed names are image data, so show seats for them instead.
        names = " and ".join(
            player.text_name() for player in self.tiebreaker_flow.contenders
        )
        if self.tiebreaker_session is not None:
            tied_for = self.tiebreaker_session.description
            cancel_text = "Cancel goes back to the tournament without settling it."
        elif self.tournament_game is not None:
            tied_for = "first"
            cancel_text = "A tournament game needs a winner, so Cancel comes back here."
        else:
            tied_for = "first"
            cancel_text = "Cancel ends the game in a tie."
        game_id, accepted = QInputDialog.getText(
            self.host_display,
            "Tiebreaker",
            f"{names} are tied for {tied_for}.\n\n"
            "Enter a J-Archive game ID for the tiebreaker clues,\n"
            "or leave it blank for a random game.\n\n"
            f"{cancel_text}",
        )
        if not accepted:
            return None
        return game_id

    def run_in_background(self, work: object) -> None:
        """Run ``work`` on a daemon thread so the host UI stays responsive.

        Args:
            work: Callable with no arguments.

        Returns:
            ``None``.
        """
        Thread(target=work, daemon=True).start()

    def start_tiebreaker(self) -> None:
        """Prompt for a tiebreaker game and load its clues.

        Returns:
            ``None``.
        """
        self.tiebreaker_flow.offer()

    def __handle_tiebreaker_loaded(
        self, token: int, game_id: str, clues: object
    ) -> None:
        """Receive tiebreaker clues on the game object's Qt thread.

        Args:
            token: Load request the clues belong to.
            game_id: Game the clues came from.
            clues: Loaded clues, highest value first.

        Returns:
            ``None``.
        """
        self.tiebreaker_flow.clues_loaded(token, game_id, clues)

    def tiebreaker_show_clue(self) -> None:
        """Reveal the current tiebreaker clue after its category.

        Returns:
            ``None``.
        """
        self.tiebreaker_flow.show_clue()

    def tiebreaker_reveal_answer(self) -> None:
        """Reveal the answer to a tiebreaker clue nobody got.

        Returns:
            ``None``.
        """
        self.tiebreaker_flow.reveal_answer()

    def tiebreaker_next_clue(self) -> None:
        """Move on to the next tiebreaker clue.

        Returns:
            ``None``.
        """
        self.tiebreaker_flow.next_clue()

    def _load_question_history(self) -> object:
        """Load per-question history for the current game session.

        Queued lines are retried first. Any that still could not be written
        are included after the saved lines.

        Returns:
            A list of question history entries.
        """
        self._flush_pending_history()
        return load_question_history(self)

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
        self.song_player.let_output_sleep()
        self.accepting_responses = False
        self.data = None
        self._judgement_round = 0
        self.early_buzzes = set()
        self.responses_open_time = None
        # Forget the closed session's save folder, so nothing done in the
        # lobby (or a later game) is written into that save.
        self._game_state_dir = None
        self._has_editable_clue = False
        self._game_started_at = None
        self._starting_roster = None
        self.tiebreaker_flow.reset()
        self.tiebreaker_winner = None
        self._reset_tournament_state()
        self.previous_answerers = set()
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
        min_wager, max_wager = dd_wager_bounds(
            self.answering_player.score, self.current_round
        )
        wager_res = QInputDialog.getInt(
            self.host_display,
            "Wager",
            f"How much do they wager? (min: ${min_wager}, max: ${max_wager})",
            min=min_wager,
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
        self.final_wagers_open = False
        self.dc.question_widget.show_question()
        self.keystroke_manager.activate("FINAL_OPEN_RESPONSES")

    def correct_answer(self) -> None:
        """Apply a correct ruling to the active player's clue response.

        Returns:
            ``None``.
        """
        if self.tiebreaker_flow.active:
            self.tiebreaker_flow.correct_answer()
            return
        self.clue_flow.correct_answer()

    def incorrect_answer(self) -> None:
        """Apply an incorrect ruling to the active player's clue response.

        Returns:
            ``None``.
        """
        if self.tiebreaker_flow.active:
            self.tiebreaker_flow.incorrect_answer()
            return
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
        if self.tiebreaker_flow.active:
            self.tiebreaker_flow.stumped()
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

        Edits are ignored until a game has started (in the lobby before Start
        and after Close Game). There is no save to record them in yet, and an
        edited score would break the new save's score chain. They are also
        ignored once a tie for first has been offered a tiebreaker, for the
        same reason as :meth:`can_open_score_editor`.

        Args:
            player: Player whose score should be edited.

        Returns:
            ``None``.
        """
        if self.current_round is None:
            return
        if self.active_question is not None or self.soliciting_player:
            return
        if self.tiebreaker_flow.locks_scores():
            return
        (new_score, answered) = QInputDialog.getInt(
            self.host_display, "Adjust Score", "Enter a new score:", value=player.score
        )
        if answered:
            self.apply_manual_score_override(player, new_score)

    def close(self) -> None:
        """Save queued history, stop timers and audio, and quit the app.

        Like ``close_game``, this makes a last attempt to write any clue
        history lines that earlier failed to save, and warns the host if they
        are still unsaved. A running clue or Final Jeopardy timer is
        cancelled so its thread does not keep the process alive.

        Returns:
            ``None``.
        """
        self._finish_pending_history()
        if self.timer:
            self.timer.cancel()
        self.timer = None
        self.song_player.stop()
        self.song_player.let_output_sleep()
        QApplication.quit()
