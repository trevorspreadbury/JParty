"""Test game resume and logging module."""

import json
from copy import deepcopy

import pytest
from PyQt6.QtCore import Qt

from jparty import __version__
from jparty.domain.models import FinalBoard, Player
from jparty.domain.state import HISTORY_FORMAT

pytestmark = pytest.mark.integration


class DummyWaiter:
    """Test helper for dummywaiter."""

    def send(self, message: object, text: object = "") -> None:
        """Test send."""
        return None

    def close(self) -> None:
        """Test close."""
        return None


def test_question_history_logging_writes_buzz_phases_and_attempts(
    game_with_players: object, time_controller: object
) -> None:
    """Test test question history logging writes buzz phases and attempts."""
    game = game_with_players
    question = game.current_round.get_question(0, 0)
    game.load_question(question)
    time_controller.advance(1.0)
    game.buzz(0)
    game.open_responses()
    time_controller.advance(0.1)
    game.buzz(1)
    time_controller.advance(0.2)
    game.correct_answer()
    history_file = game._game_state_dir / "question_history.jsonl"
    entry = json.loads(history_file.read_text().splitlines()[0])
    assert entry["question_number"] == 1
    assert entry["answer_attempts"][0]["player_index"] == 1
    assert entry["buzz_phases"]
    assert entry["buzz_phases"][0]["buzz_attempts"][0]["player_index"] == 0


def test_final_jeopardy_logging_writes_question_history_entry(
    game_with_players: object,
) -> None:
    """Test Final Jeopardy judgments are written to question history."""
    game = game_with_players
    game.current_round = game.data.rounds[2]
    game.active_question = game.current_round.question
    game.players[0].score = 1000
    game.players[1].score = 800
    game.players[2].score = 600
    game.players[0].wager = 200
    game.players[1].wager = 300
    game.players[2].wager = 100
    game.players[0].finalanswer = "Paris"
    game.players[1].finalanswer = "London"
    game.players[2].finalanswer = "Rome"
    game.final_open_responses()
    for expected_player, is_correct in [
        (game.players[2], False),
        (game.players[1], True),
        (game.players[0], False),
    ]:
        game.final_next_player()
        assert game.answering_player is expected_player
        game.final_show_answer()
        if is_correct:
            game.final_correct_answer()
        else:
            game.final_incorrect_answer()
    game.final_next_player()
    history_file = game._game_state_dir / "question_history.jsonl"
    entry = json.loads(history_file.read_text().splitlines()[-1])
    assert entry["round_index"] == 2
    assert entry["answer_attempts"]
    assert [attempt["player_index"] for attempt in entry["answer_attempts"]] == [
        2,
        1,
        0,
    ]


def test_prepare_and_resume_saved_game_restores_round_scores_and_questions(
    game: object, monkeypatch: object, sample_saved_game_dir: object
) -> None:
    """Test test prepare and resume saved game restores round scores and questions."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(sample_saved_game_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()
    assert game.current_round is game.data.rounds[0]
    assert not isinstance(game.current_round, FinalBoard)
    assert game.question_number == 4
    assert game.players[0].score == 0
    assert game.players[1].score == 400
    assert game.current_round.get_question(0, 0).complete is True
    assert game.current_round.get_question(1, 0).complete is True
    assert game.current_round.get_question(2, 0).complete is True
    assert game.current_round.get_question(3, 0).complete is False


def test_resume_with_real_controller_reclaims_signature_player(
    game: object, monkeypatch: object, sample_saved_game_dir: object
) -> None:
    """Test a phone reclaims a drawn-signature player and keeps its score."""
    from jparty.services import game_loader
    from jparty.web.controller import BuzzerController

    signature = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAA+/x=="
    general_file = sample_saved_game_dir / "general.json"
    general = json.loads(general_file.read_text())
    general["players"][1]["name"] = signature
    general_file.write_text(json.dumps(general))
    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    controller = BuzzerController(game)
    game.buzzer_controller = controller

    game.prepare_resume_from_dir(sample_saved_game_dir)
    claimed = {}
    for number in (1, 0):
        socket = DummyWaiter()
        controller.register_socket(socket)
        claimed[number] = controller.claim_saved_player(socket, number)
    assert game.resume_claims_complete()
    # The signature player's phone reconnects with the token it was given.
    assert controller.player_with_token(claimed[1].token.hex()) is claimed[1]
    game.start_game()

    assert [(player.name, player.score) for player in game.players] == [
        ("Alice", 0),
        (signature, 400),
    ]
    assert game.players[1] is claimed[1]
    rewritten = json.loads(general_file.read_text())
    assert [player["name"] for player in rewritten["players"]] == ["Alice", signature]


def _resume_and_read_general_state(game: object, saved_dir: object) -> dict:
    """Resume ``saved_dir`` and return the ``general.json`` it writes back."""
    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()
    return json.loads((saved_dir / "general.json").read_text())


def test_new_game_records_history_format_and_version(
    game: object, players: object, monkeypatch: object
) -> None:
    """Test a new session stamps general.json with the format and app version."""
    from jparty.services import archive_client

    monkeypatch.setattr(archive_client, "save_game_html", lambda game_id: None)
    game.set_session_game_id("4453")
    game.start_game()

    saved = json.loads((game._game_state_dir / "general.json").read_text())
    assert saved["history_format"] == HISTORY_FORMAT
    assert saved["jparty_version"] == __version__


def _freeze_save_folder_clock(monkeypatch: object, stamp: str) -> None:
    """Make every new save folder use the local timestamp ``stamp``."""

    class FrozenNow:
        """A ``datetime.now()`` result that always formats as ``stamp``."""

        def astimezone(self) -> object:
            """Return this frozen time unchanged."""
            return self

        def strftime(self, fmt: object) -> str:
            """Return ``stamp`` for the save-folder format."""
            assert fmt == "%Y%m%dT%H%M"
            return stamp

    class FrozenDatetime:
        """Stand-in for ``datetime`` whose clock never moves."""

        @classmethod
        def now(cls) -> object:
            """Return the frozen time."""
            return FrozenNow()

    monkeypatch.setattr("jparty.domain.game_engine.datetime", FrozenDatetime)


def _start_fresh_game(game: object, players: list, data: object) -> object:
    """Start a fresh session of game 4453 on ``data``; return its save folder."""
    game.data = data
    game.set_session_game_id("4453")
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()
    return game._game_state_dir


def test_fresh_starts_in_the_same_minute_get_separate_save_folders(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """A second Start in the same minute must not write into the first save."""
    from jparty.domain import game_engine
    from jparty.domain.state import read_history_file
    from jparty.services import archive_client

    monkeypatch.setattr(archive_client, "save_game_html", lambda game_id: None)
    monkeypatch.setattr(game_engine, "GAME_STATES_DIR", temp_dir / "game_states")
    _freeze_save_folder_clock(monkeypatch, "20260418T1435")
    data = game.data

    first_players = [
        Player("Alice", DummyWaiter(), 0),
        Player("Bob", DummyWaiter(), 1),
    ]
    first_dir = _start_fresh_game(game, first_players, data)
    _answer_correctly(game, _first_plain_clue(game.current_round), 0)
    first_general = (first_dir / "general.json").read_text()
    first_history = (first_dir / "question_history.jsonl").read_text()
    game.close_game()

    second_players = [
        Player("Carol", DummyWaiter(), 0),
        Player("Dave", DummyWaiter(), 1),
    ]
    second_dir = _start_fresh_game(game, second_players, data)
    _answer_correctly(game, _first_plain_clue(game.current_round), 1)

    assert first_dir.name == "4453-20260418T1435"
    assert second_dir.name == "4453-20260418T1435-2"
    assert (first_dir / "general.json").read_text() == first_general
    assert (first_dir / "question_history.jsonl").read_text() == first_history
    assert len(read_history_file(first_dir / "question_history.jsonl")) == 1
    assert len(read_history_file(second_dir / "question_history.jsonl")) == 1
    second_general = json.loads((second_dir / "general.json").read_text())
    assert [player["name"] for player in second_general["players"]] == [
        "Carol",
        "Dave",
    ]

    game.close_game()
    third_dir = _start_fresh_game(game, second_players, data)
    assert third_dir.name == "4453-20260418T1435-3"


def test_resume_keeps_writing_to_an_old_style_save_folder(
    game: object,
    monkeypatch: object,
    temp_dir: object,
    sample_saved_game_dir: object,
) -> None:
    """An existing ``<id>-<minute>`` save resumes in place, not in a new folder."""
    import shutil

    from jparty.domain import game_engine
    from jparty.services import archive_client, game_loader

    monkeypatch.setattr(archive_client, "save_game_html", lambda game_id: None)
    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    states_dir = temp_dir / "game_states"
    monkeypatch.setattr(game_engine, "GAME_STATES_DIR", states_dir)
    _freeze_save_folder_clock(monkeypatch, "20260422T2130")
    old_dir = states_dir / "4453-20260422T2130"
    states_dir.mkdir()
    shutil.copytree(sample_saved_game_dir, old_dir)

    saved = _resume_and_read_general_state(game, old_dir)

    assert game._game_state_dir == old_dir
    assert saved["game_id"] == "4453"
    assert [path.name for path in states_dir.iterdir()] == ["4453-20260422T2130"]
    game.close_game()
    game.clear_resume_state()

    fresh_dir = _start_fresh_game(
        game,
        [Player("Carol", DummyWaiter(), 0), Player("Dave", DummyWaiter(), 1)],
        restored_data,
    )
    assert fresh_dir.name == "4453-20260422T2130-2"
    assert json.loads((old_dir / "general.json").read_text()) == saved


def test_resume_keeps_the_recorded_format_and_version(
    game: object, monkeypatch: object, sample_saved_game_dir: object
) -> None:
    """Test resume keeps the version that started the save, not the current one."""
    from jparty.services import game_loader

    monkeypatch.setattr(game_loader, "get_game", lambda game_id: game.data)
    general_file = sample_saved_game_dir / "general.json"
    general_state = json.loads(general_file.read_text())
    general_state["history_format"] = 2
    general_state["jparty_version"] = "0.0.1-test"
    general_file.write_text(json.dumps(general_state))

    saved = _resume_and_read_general_state(game, sample_saved_game_dir)

    assert saved["history_format"] == 2
    assert saved["jparty_version"] == "0.0.1-test"


def test_resume_leaves_a_save_without_a_format_unmarked(
    game: object, monkeypatch: object, sample_saved_game_dir: object
) -> None:
    """Test resuming a save from before the fields existed doesn't add them."""
    from jparty.services import game_loader

    monkeypatch.setattr(game_loader, "get_game", lambda game_id: game.data)
    general_state = json.loads((sample_saved_game_dir / "general.json").read_text())
    assert "history_format" not in general_state

    saved = _resume_and_read_general_state(game, sample_saved_game_dir)

    assert "history_format" not in saved
    assert "jparty_version" not in saved


def test_resume_into_final_starts_final_flow(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Test test resume into final starts final flow."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as f:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "started_at": 1700000000.0,
                "last_updated": 1700000300.0,
            },
            f,
        )
    history_entries = []
    question_number = 1
    for round_index, round_data in enumerate(restored_data.rounds[:2]):
        for question in round_data.questions:
            history_entries.append(
                {
                    "question_index": [round_index, list(question.index)],
                    "question_number": question_number,
                    "round_index": round_index,
                    "category": question.category,
                    "value": question.value,
                    "is_daily_double": question.dd,
                    "buzz_phases": [],
                    "answer_attempts": [],
                    "completed_at": 1700000000.0 + question_number,
                }
            )
            question_number += 1
    with (saved_dir / "question_history.jsonl").open("w") as f:
        for entry in history_entries:
            json.dump(entry, f)
            f.write("\n")
    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()
    assert isinstance(game.current_round, FinalBoard)
    assert game.active_question is game.current_round.question
    assert game.buzzer_controller.open_wagers_calls


def test_resume_finished_board_without_final_can_end_game(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Resuming a fully played board with no Final should let Space end the game."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved-finished-no-final"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as f:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "selected_round_indices": [0],
            },
            f,
        )
    with (saved_dir / "question_history.jsonl").open("w") as f:
        for question_number, question in enumerate(
            restored_data.rounds[0].questions, start=1
        ):
            json.dump(
                {
                    "question_index": [0, list(question.index)],
                    "question_number": question_number,
                    "round_index": 0,
                    "category": question.category,
                    "value": question.value,
                    "is_daily_double": question.dd,
                    "buzz_phases": [],
                    "answer_attempts": [],
                    "completed_at": 1700000000.0 + question_number,
                },
                f,
            )
            f.write("\n")

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    assert game.current_round is game.data.rounds[0]
    events = game.keystroke_manager._KeystrokeManager__events
    assert events["NEXT_ROUND"].active is True
    game.keystroke_manager.call(Qt.Key.Key_Space)
    assert events["GENERATE_GRAPHS"].active is True


def test_resume_after_final_goes_to_end_of_game(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Resuming a save whose Final was judged must not reopen wagering."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved-after-final"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as f:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
            },
            f,
        )
    history_entries = []
    for round_index, round_data in enumerate(restored_data.rounds):
        for question in round_data.questions:
            history_entries.append(
                {
                    "question_index": [round_index, list(question.index)],
                    "question_number": len(history_entries) + 1,
                    "round_index": round_index,
                    "category": question.category,
                    "value": question.value,
                    "is_daily_double": question.dd,
                    "buzz_phases": [],
                    "answer_attempts": [],
                    "completed_at": 1700000000.0 + len(history_entries),
                }
            )
    # Bob wagered 300 on Final and got it right.
    history_entries[-1]["answer_attempts"] = [
        {
            "player_index": 1,
            "answer_correct": True,
            "score_before": 0,
            "score_after": 300,
        }
    ]
    with (saved_dir / "question_history.jsonl").open("w") as f:
        for entry in history_entries:
            json.dump(entry, f)
            f.write("\n")

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    assert isinstance(game.current_round, FinalBoard)
    assert not game.buzzer_controller.open_wagers_calls
    assert game.dc.loaded_final_judgement == 1
    assert game.dc.final_window.winner is players[1]
    events = game.keystroke_manager._KeystrokeManager__events
    assert events["GENERATE_GRAPHS"].active is True
    history_lines = (saved_dir / "question_history.jsonl").read_text().splitlines()
    assert len(history_lines) == len(history_entries)


def test_resume_skips_deselected_rounds_when_advancing(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Resumed standard games should honor saved round selections."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved-selected-rounds"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as f:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "selected_round_indices": [0, 2],
            },
            f,
        )
    with (saved_dir / "question_history.jsonl").open("w") as f:
        f.write("")

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    assert game.current_round is game.data.rounds[0]
    game.next_round()
    assert isinstance(game.current_round, FinalBoard)


def test_resume_subset_save_uses_original_round_indices(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Subset saves should resume against original round indices, read-only."""
    from jparty.services import game_loader

    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved-double-and-final"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as f:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "selected_round_indices": [1, 2],
            },
            f,
        )
    with (saved_dir / "question_history.jsonl").open("w") as f:
        json.dump(
            {
                "question_index": [1, [0, 0]],
                "question_number": 1,
                "round_index": 1,
                "category": "Cat 0",
                "value": 400,
                "is_daily_double": False,
                "buzz_phases": [
                    {
                        "phase_type": "main",
                        "buzz_attempts": [
                            {
                                "player_index": 0,
                                "question_index": [1, [0, 0]],
                                "timestamp": 1.0,
                                "is_early": False,
                                "is_success": True,
                                "is_rebound": False,
                                "in_timeout": False,
                            }
                        ],
                    }
                ],
                "answer_attempts": [],
                "completed_at": 2.0,
            },
            f,
        )
        f.write("\n")

    history_file = saved_dir / "question_history.jsonl"
    history_before = history_file.read_bytes()
    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    assert len(game.data.rounds) == 3
    assert game.selected_round_indices() == [1, 2]
    assert game.current_round is game.data.rounds[1]
    assert game.data.rounds[1].get_question(0, 0).complete is True
    assert game.data.rounds[0].get_question(0, 0).complete is False
    assert history_file.read_bytes() == history_before


class _ImmediateLoader:
    """Welcome-screen loader that runs each load inline."""

    def run_async(self, target: object) -> None:
        """Run the load right away."""
        target()


def _fixture_game(fixture_dir: object) -> object:
    """Return game 4453 parsed from the saved J-Archive page.

    Its Jeopardy, Double Jeopardy and Final boards all have different
    categories, unlike ``build_game_data``.
    """
    from jparty.services.game_parser import GameParser

    html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    source = GameParser().process_game_board_from_html(html, "4453")
    assert source is not None
    return source


def _start_regular_game(
    qtbot: object,
    game: object,
    monkeypatch: object,
    temp_dir: object,
    source: object,
    ticked: list[int],
) -> object:
    """Start ``source`` in regular mode with only the ``ticked`` rounds.

    Goes through the real welcome screen: type the game id, tick rounds,
    press Start. Saves go to ``temp_dir``; nothing is fetched.

    Returns:
        The save folder the game writes to.
    """
    from jparty.domain import game_engine
    from jparty.services.question_media import QuestionMediaStatus
    from jparty.ui.widgets.welcome import Welcome

    for target in (
        "jparty.services.game_loader.get_game",
        "jparty.ui.widgets.welcome.get_game",
    ):
        monkeypatch.setattr(target, lambda game_id: deepcopy(source))
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )
    monkeypatch.setattr("jparty.services.question_media.QUESTION_MEDIA", temp_dir)
    monkeypatch.setattr(game_engine, "GAME_STATES_DIR", temp_dir / "game_states")
    monkeypatch.setattr(game, "_save_played_game_html", lambda: None)
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.loader = _ImmediateLoader()
    widget.textbox.setText("4453")
    widget.show_summary()
    for index, checkbox in enumerate(widget.round_checkboxes):
        checkbox.setChecked(index in ticked)
    assert game.selected_round_indices() == ticked
    widget.on_start_clicked()
    return game._game_state_dir


def _answer_correctly(game: object, question: object, player_index: int) -> None:
    """Play ``question`` on the current board; ``player_index`` gets it right."""
    assert not question.dd
    game.load_question(question)
    game.open_responses()
    game.buzz(player_index)
    game.correct_answer()


def _resume(game: object, saved_dir: object) -> None:
    """Close the running game and resume ``saved_dir`` with the same players."""
    players = list(game.players)
    game.close_game()
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    for player in players:
        player.score = 0
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()


def _played_clues(game: object) -> list[tuple[str, tuple]]:
    """Return ``(category, index)`` for every clue marked played."""
    return [
        (question.category, question.index)
        for round_data in game.data.rounds
        for question in round_data.questions
        if question.complete
    ]


def _first_plain_clue(round_data: object) -> object:
    """Return the first clue on ``round_data`` that is not a Daily Double."""
    return next(question for question in round_data.questions if not question.dd)


def test_regular_jeopardy_and_final_plays_final_after_jeopardy(
    qtbot: object,
    game_with_players: object,
    monkeypatch: object,
    temp_dir: object,
    fixture_dir: object,
) -> None:
    """Skipping Double Jeopardy in regular mode still reaches Final (#93)."""
    game = game_with_players
    source = _fixture_game(fixture_dir)
    saved_dir = _start_regular_game(qtbot, game, monkeypatch, temp_dir, source, [0, 2])

    assert len(game.data.rounds) == 2
    assert game.selected_round_indices() == [0, 1]
    general_state = json.loads((saved_dir / "general.json").read_text())
    assert general_state["selected_round_indices"] == [0, 1]
    assert [
        selection["source_round_index"]
        for selection in general_state["board_selections"]
    ] == [0, 2]

    game.next_round()

    assert isinstance(game.current_round, FinalBoard)
    assert game.current_round.category == source.rounds[2].category
    assert game.buzzer_controller.open_wagers_calls
    assert game.dc.loaded_final_judgement == 0


@pytest.mark.parametrize(
    ("ticked", "played_round"),
    [([1, 2], 1), ([0, 1, 2], 1), ([0, 1, 2], 0)],
    ids=["double-and-final", "all-rounds-double", "all-rounds-jeopardy"],
)
def test_regular_round_subset_resume_marks_the_played_clue(
    qtbot: object,
    game_with_players: object,
    monkeypatch: object,
    temp_dir: object,
    fixture_dir: object,
    ticked: list[int],
    played_round: int,
) -> None:
    """Resume and ``jparty summary`` read history against the played boards (#93)."""
    from jparty.app import bootstrap
    from jparty.domain.state import build_end_game_summary

    game = game_with_players
    source = _fixture_game(fixture_dir)
    saved_dir = _start_regular_game(qtbot, game, monkeypatch, temp_dir, source, ticked)
    board = game.data.rounds[ticked.index(played_round)]
    if board is not game.current_round:
        game.current_round = board
        game.dc.board_widget.load_round(board)
    clue = _first_plain_clue(board)
    _answer_correctly(game, clue, 1)
    played = [(clue.category, clue.index)]
    assert clue.category in source.rounds[played_round].categories
    in_app_summary = build_end_game_summary(game)

    assert bootstrap.load_summary_from_game_state_directory(saved_dir) == (
        in_app_summary
    )

    _resume(game, saved_dir)

    assert _played_clues(game) == played
    assert [player.score for player in game.players] == [0, clue.value, 0]
    # The first ticked round still has unplayed clues, so play resumes there.
    assert game.current_round.categories == source.rounds[ticked[0]].categories
    assert build_end_game_summary(game) == in_app_summary
    assert bootstrap.load_summary_from_game_state_directory(saved_dir) == (
        in_app_summary
    )


def test_resume_preserves_frankenstein_board_selections_and_round_sources(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Resuming a mixed-source game should not collapse it to one source board."""
    from jparty.services import game_loader

    source_a = deepcopy(game.data)
    source_b = deepcopy(game.data)
    source_a.date = "January 1, 2026"
    source_b.date = "January 2, 2026"
    source_a.comments = "Source A"
    source_b.comments = "Source B"
    source_a.rounds[0].categories[0] = "A Category"
    source_a.rounds[0].questions[0].text = "A Jeopardy clue"
    source_a.rounds[2].category = "A Final Category"
    source_b.rounds[1].categories[0] = "B Category"
    source_b.rounds[1].questions[0].text = "B Double Jeopardy clue"
    monkeypatch.setattr(
        game_loader,
        "get_game",
        lambda game_id: {"111": source_a, "222": source_b}[game_id],
    )

    board_selections = [
        {
            "game_id": "111",
            "source_round_index": 0,
            "source_round_label": "Jeopardy!",
            "board_type": "standard",
            "row_values": [200, 400, 600, 800, 1000],
        },
        {
            "game_id": "222",
            "source_round_index": 1,
            "source_round_label": "Double Jeopardy!",
            "board_type": "standard",
            "row_values": [400, 800, 1200, 1600, 2000],
        },
        {
            "game_id": "111",
            "source_round_index": 2,
            "source_round_label": "Final Jeopardy!",
            "board_type": "final",
            "row_values": [],
        },
    ]
    saved_dir = temp_dir / "mixed_saved"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as file_obj:
        json.dump(
            {
                "game_id": "frankenstein-111-222-111",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "selected_round_indices": [0, 1, 2],
                "board_selections": board_selections,
                "started_at": 1700000000.0,
                "last_updated": 1700000300.0,
            },
            file_obj,
        )
    with (saved_dir / "question_history.jsonl").open("w") as file_obj:
        json.dump(
            {
                "question_index": [0, [0, 0]],
                "question_number": 1,
                "round_index": 0,
                "category": "A Category",
                "value": 200,
                "is_daily_double": False,
                "buzz_phases": [],
                "answer_attempts": [],
                "completed_at": 1700000001.0,
            },
            file_obj,
        )
        file_obj.write("\n")

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    rewritten_general = json.loads((saved_dir / "general.json").read_text())
    assert [
        selection["game_id"] for selection in rewritten_general["board_selections"]
    ] == [
        "111",
        "222",
        "111",
    ]
    assert game.data.rounds[0].questions[0].text == "A Jeopardy clue"
    assert game.data.rounds[1].questions[0].text == "B Double Jeopardy clue"
    assert game.data.rounds[2].category == "A Final Category"
    assert game.current_round is game.data.rounds[0]


def test_resume_rebuilds_saved_daily_double_locations(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """Saved advanced boards should restore their exact Daily Double coords."""
    from jparty.services import game_loader

    restored_data = deepcopy(game.data)
    for question in restored_data.rounds[0].questions:
        question.dd = False
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)

    saved_dir = temp_dir / "saved-daily-doubles"
    saved_dir.mkdir()
    with (saved_dir / "general.json").open("w") as file_obj:
        json.dump(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
                "selected_round_indices": [0],
                "board_selections": [
                    {
                        "game_id": "4453",
                        "source_round_index": 0,
                        "source_round_label": "Jeopardy!",
                        "board_type": "standard",
                        "row_values": [200, 400, 600, 800, 1000],
                        "daily_double_count": 2,
                        "daily_double_indices": [[0, 1], [4, 3]],
                    }
                ],
            },
            file_obj,
        )
    with (saved_dir / "question_history.jsonl").open("w") as file_obj:
        file_obj.write("")

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    restored_indices = sorted(
        [
            list(question.index)
            for question in game.data.rounds[0].questions
            if question.dd
        ]
    )
    assert restored_indices == [[0, 1], [4, 3]]


def test_start_game_ignores_a_resume_prepared_for_another_game(
    game: object, monkeypatch: object, sample_saved_game_dir: object
) -> None:
    """A resume for game 4453 must not run, or write, when another game starts."""
    from jparty.services import game_loader

    source = deepcopy(game.data)
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: deepcopy(source))
    monkeypatch.setattr(game, "_save_played_game_html", lambda: None)
    general_before = (sample_saved_game_dir / "general.json").read_bytes()
    history_before = (sample_saved_game_dir / "question_history.jsonl").read_bytes()
    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(sample_saved_game_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    # What advanced mode does after Load Saved: swap in a different board.
    game.set_board_selection_configs(
        [
            {
                "game_id": "9999",
                "source_round_index": 0,
                "source_round_label": "Jeopardy!",
                "board_type": "standard",
                "row_values": [200, 400, 600, 800, 1000],
            }
        ]
    )
    game.set_session_game_id("frankenstein-9999")

    game.start_game()

    assert game._resume_state is None
    assert game._game_state_dir != sample_saved_game_dir
    saved = json.loads((game._game_state_dir / "general.json").read_text())
    assert saved["game_id"] == "frankenstein-9999"
    assert (sample_saved_game_dir / "general.json").read_bytes() == general_before
    assert (
        sample_saved_game_dir / "question_history.jsonl"
    ).read_bytes() == history_before
    assert game.question_number == 1
    assert [player.score for player in game.players] == [0, 0]
    assert not any(question.complete for question in game.data.rounds[0].questions)


def test_close_game_resets_state(game_with_players: object) -> None:
    """Test test close game resets state."""
    game = game_with_players
    game.active_question = game.current_round.get_question(0, 0)
    game.answering_player = game.players[0]
    game.early_buzzes.add(0)
    game.close_game()
    assert game.players == []
    assert game.active_question is None
    assert game.current_round is None
    assert game.question_number == 1
    assert game.buzzer_controller.restart_calls == 1
    assert game.dc.restart_calls == 1


class _RecordingTimer:
    """Stand-in clue timer that records cancels."""

    def __init__(self) -> None:
        """Start with no cancels."""
        self.cancel_calls = 0

    def cancel(self) -> None:
        """Record a cancel."""
        self.cancel_calls += 1


def test_close_game_cancels_timer_and_closes_responses(
    game_with_players: object,
) -> None:
    """Closing mid-clue stops the clue timer instead of leaving it running."""
    game = game_with_players
    timer = _RecordingTimer()
    game.timer = timer
    game.accepting_responses = True

    game.close_game()

    assert timer.cancel_calls == 1
    assert game.timer is None
    assert not game.accepting_responses


def test_stumped_timeout_after_close_game_is_ignored(
    game_with_players: object, monkeypatch: object
) -> None:
    """A clue timeout already on its way when the game closes does nothing."""
    game = game_with_players
    stumped_calls = []
    monkeypatch.setattr(game.clue_flow, "stumped", lambda: stumped_calls.append(1))
    game.accepting_responses = True

    game.close_game()
    game.stumped()

    assert stumped_calls == []


def test_final_timeout_after_close_game_is_ignored(
    game_with_players: object, monkeypatch: object
) -> None:
    """A Final Jeopardy timeout arriving after the game closes does nothing."""
    game = game_with_players
    finished_calls = []
    monkeypatch.setattr(
        game.final_jeopardy_flow, "finished_song", lambda: finished_calls.append(1)
    )
    game.current_round = game.data.rounds[-1]

    game.close_game()
    game.final_finished_song()

    assert finished_calls == []


def test_final_timeout_during_final_jeopardy_still_runs(
    game_with_players: object, monkeypatch: object
) -> None:
    """The Final Jeopardy timeout guard lets the real timeout through."""
    game = game_with_players
    finished_calls = []
    monkeypatch.setattr(
        game.final_jeopardy_flow, "finished_song", lambda: finished_calls.append(1)
    )
    game.current_round = game.data.rounds[-1]

    game.final_finished_song()

    assert finished_calls == [1]


def test_start_game_saves_html_when_play_begins(
    game: object, monkeypatch: object
) -> None:
    """Test test start game saves html when play begins."""
    from jparty.domain import game_engine
    from jparty.services import archive_client

    # Run the save inline so it finishes before the asserts, and never runs
    # after the patched save_game_html has been restored.
    monkeypatch.setattr(game_engine, "Thread", _InlineThread)
    saved_game_ids = []
    monkeypatch.setattr(
        archive_client, "save_game_html", lambda game_id: saved_game_ids.append(game_id)
    )
    game.set_session_game_id("4453")
    game.start_game()
    assert saved_game_ids == ["4453"]
    assert game.current_round is game.data.rounds[0]
    assert game.dc.hidden_welcome == 1


def test_start_game_without_board_selections_plays_only_selected_rounds(
    game: object, monkeypatch: object
) -> None:
    """Without board selections the whole game stays loaded and is resumable.

    Selected indices and history both keep pointing into the full game, which
    is what resume loads for a save without ``board_selections``.
    """
    from jparty.services import archive_client

    monkeypatch.setattr(archive_client, "save_game_html", lambda game_id: None)
    game.set_session_game_id("4453")
    game.set_selected_round_indices([1, 2])
    double_jeopardy, final = game.data.rounds[1], game.data.rounds[2]
    game.start_game()

    assert len(game.data.rounds) == 3
    assert game.current_round is double_jeopardy
    saved = json.loads((game._game_state_dir / "general.json").read_text())
    assert saved["selected_round_indices"] == [1, 2]
    game.next_round()
    assert game.current_round is final


def test_next_round_ends_game_when_no_later_round_is_selected(
    game_with_players: object, monkeypatch: object
) -> None:
    """Test test next round ends game when no later round is selected."""
    from jparty.services import archive_client

    game = game_with_players
    monkeypatch.setattr(archive_client, "save_game_html", lambda game_id: None)
    game.set_session_game_id("4453")
    game.set_selected_round_indices([0])
    game.dc.final_window = None
    game.start_game()
    game.next_round()
    assert game.dc.loaded_final_judgement == 1
    assert game.dc.final_window.winner is not None or game.dc.final_window.tie_shown


SUBSET_BOARD_SELECTIONS = [
    {
        "game_id": "4453",
        "source_round_index": 1,
        "source_round_label": "Double Jeopardy!",
        "board_type": "standard",
        "row_values": [400, 800, 1200, 1600, 2000],
    },
    {
        "game_id": "4453",
        "source_round_index": 2,
        "source_round_label": "Final Jeopardy!",
        "board_type": "final",
        "row_values": [],
    },
]


@pytest.mark.parametrize(
    ("board_selections", "selected_round_indices", "round_index"),
    [(None, [1, 2], 1), (SUBSET_BOARD_SELECTIONS, [0, 1], 0)],
    ids=["no-board-selections", "regular-subset"],
)
def test_cli_summary_matches_in_app_summary_for_round_subset(
    game: object,
    monkeypatch: object,
    temp_dir: object,
    board_selections: object,
    selected_round_indices: list[int],
    round_index: int,
) -> None:
    """``jparty summary`` and the app agree on stats for a round-subset save.

    Without board selections the full game is loaded, so Double Jeopardy is
    round 1. With them the game is built from the played boards, so Double
    Jeopardy is round 0.
    """
    from jparty.app import bootstrap
    from jparty.domain.state import build_end_game_summary
    from jparty.services import game_loader

    restored_data = deepcopy(game.data)
    monkeypatch.setattr(
        game_loader, "get_game", lambda game_id: deepcopy(restored_data)
    )
    saved_dir = temp_dir / "saved-summary-subset"
    saved_dir.mkdir()
    general_state = {
        "game_id": "4453",
        "players": [
            {"name": "Alice", "player_number": 0},
            {"name": "Bob", "player_number": 1},
        ],
        "selected_round_indices": selected_round_indices,
    }
    if board_selections is not None:
        general_state["board_selections"] = board_selections
    (saved_dir / "general.json").write_text(json.dumps(general_state))
    (saved_dir / "question_history.jsonl").write_text(
        json.dumps(
            {
                "question_index": [round_index, [0, 0]],
                "question_number": 1,
                "round_index": round_index,
                "category": restored_data.rounds[1].questions[0].category,
                "value": 400,
                "is_daily_double": False,
                "buzz_phases": [],
                "answer_attempts": [
                    {
                        "player_index": 0,
                        "answer_correct": True,
                        "score_before": 0,
                        "score_after": 400,
                    }
                ],
                "completed_at": 2.0,
            }
        )
        + "\n"
    )

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()
    app_summary = build_end_game_summary(game)
    cli_summary = bootstrap.load_summary_from_game_state_directory(saved_dir)

    def player_stats(summary: object) -> dict:
        return {
            player.name: (player.final_score, player.coryat, player.right_count)
            for player in summary.current_players
        }

    assert player_stats(app_summary) == {"Alice": (400, 400, 1), "Bob": (0, 0, 0)}
    assert player_stats(cli_summary) == player_stats(app_summary)
    assert cli_summary.game_stats == app_summary.game_stats
    assert cli_summary.question_count == app_summary.question_count


class _InlineThread:
    """Stand-in for ``threading.Thread`` that runs its target on ``start``."""

    def __init__(self, target: object, daemon: bool = False) -> None:
        """Store the target to run."""
        self._target = target

    def start(self) -> None:
        """Run the target immediately on the calling thread."""
        self._target()


def _source_selection(game_id: str, round_index: int = 0) -> dict:
    """Return one advanced-mode board selection drawing from ``game_id``."""
    return {
        "game_id": game_id,
        "source_round_index": round_index,
        "source_round_label": "Jeopardy!",
        "board_type": "standard",
        "row_values": [200, 400, 600, 800, 1000],
    }


def _start_composed_game(
    game: object, monkeypatch: object, game_ids: list, save_game_html: object
) -> None:
    """Start an advanced-mode game built from ``game_ids`` with saving inlined.

    The composed board is cached up front, so nothing is fetched to build it,
    and ``Thread`` runs inline, so the save step finishes before this returns.
    """
    from jparty.domain import game_engine
    from jparty.services import archive_client

    monkeypatch.setattr(game_engine, "Thread", _InlineThread)
    monkeypatch.setattr(archive_client, "save_game_html", save_game_html)
    configs = [
        _source_selection(game_id, index) for index, game_id in enumerate(game_ids)
    ]
    game.set_board_selection_configs(configs)
    game.set_composed_game_data(configs, deepcopy(game.data))
    game.set_session_game_id("frankenstein-test")
    game.start_game()


def test_start_game_saves_each_selected_source_game(
    game: object, monkeypatch: object
) -> None:
    """Every J-Archive game used by a composed board should be cached."""
    saved = []
    _start_composed_game(game, monkeypatch, ["4453", "5000", "6001"], saved.append)
    assert sorted(saved) == ["4453", "5000", "6001"]


def test_start_game_saves_a_repeated_source_game_once(
    game: object, monkeypatch: object
) -> None:
    """Two boards from the same source game should cache it only once."""
    saved = []
    _start_composed_game(game, monkeypatch, ["4453", "4453", "5000"], saved.append)
    assert sorted(saved) == ["4453", "5000"]


def test_start_game_skips_google_sheet_source_games(
    game: object, monkeypatch: object
) -> None:
    """Google Sheets sources have no J-Archive HTML and are not cached."""
    saved = []
    _start_composed_game(
        game, monkeypatch, ["4453", "1AbCdEfGhIjK", "5000"], saved.append
    )
    assert sorted(saved) == ["4453", "5000"]


def test_start_game_keeps_saving_after_one_source_fails(
    game: object, monkeypatch: object
) -> None:
    """One failed save should not stop the remaining games from being cached."""
    attempted = []
    saved = []

    def flaky_save(game_id: str) -> None:
        """Fail for one game and record the rest."""
        attempted.append(game_id)
        if game_id == "5000":
            raise ConnectionError("offline")
        saved.append(game_id)

    _start_composed_game(game, monkeypatch, ["4453", "5000", "6001"], flaky_save)
    assert sorted(attempted) == ["4453", "5000", "6001"]
    assert sorted(saved) == ["4453", "6001"]
    assert game.current_round is game.data.rounds[0]


def _two_final_game_data(game: object) -> object:
    """Return game data with one board followed by two Final boards."""
    from jparty.domain import GameData, Question

    return GameData(
        rounds=[
            game.data.rounds[0],
            FinalBoard(
                "First Final",
                Question((0, 0), "First clue", "First response", "First Final"),
            ),
            FinalBoard(
                "Second Final",
                Question((0, 0), "Second clue", "Second response", "Second Final"),
            ),
        ],
        date="January 1, 2026",
        comments="Two Finals",
    )


def _play_final(game: object, wagers: list[int], rulings: list[bool]) -> None:
    """Play the current Final: wagers, answers, then judge lowest score first."""
    for index, amount in enumerate(wagers):
        game.wager(index, amount)
    game.open_final()
    game.final_open_responses()
    for player in game.players:
        game.answer(player, f"{player.name} answer")
    game.final_jeopardy_flow.finished_song()
    for is_correct in rulings:
        game.final_next_player()
        game.final_show_answer()
        if is_correct:
            game.final_correct_answer()
        else:
            game.final_incorrect_answer()
    game.final_next_player()


def test_two_final_boards_are_both_played_in_order(
    game_with_players: object,
) -> None:
    """With two Final boards, judging the first Final opens the second."""
    from jparty.domain.state import build_end_game_summary

    game = game_with_players
    game.data = _two_final_game_data(game)
    game.set_selected_round_indices([0, 1, 2])
    first_final, second_final = game.data.rounds[1], game.data.rounds[2]
    for player, score in zip(game.players, [1000, 800, 600], strict=True):
        game.score_recorder.apply_manual_score_override(player, score)
    game.current_round = game.data.rounds[0]
    for question in game.current_round.questions:
        question.complete = True
    game.question_number = 31

    game.next_round()
    assert game.current_round is first_final
    _play_final(game, [200, 300, 100], [False, True, False])

    # The first Final's history is saved and the second Final begins with
    # fresh wagers and answers instead of the game ending.
    assert game.current_round is second_final
    assert game.dc.unloaded_finals == 1
    assert game.dc.loaded_finals == [first_final.question, second_final.question]
    assert len(game.buzzer_controller.open_wagers_calls) == 2
    assert all(player.wager is None for player in game.players)
    assert all(player.finalanswer == "" for player in game.players)
    assert first_final.question.complete is True
    assert [player.score for player in game.players] == [800, 1100, 500]
    events = game.keystroke_manager._KeystrokeManager__events
    assert events["GENERATE_GRAPHS"].active is False

    # Judged lowest score first: Cara right, Alice right, Bob wrong.
    _play_final(game, [0, 1100, 500], [True, True, False])
    assert events["GENERATE_GRAPHS"].active is True
    assert [player.score for player in game.players] == [800, 0, 1000]
    assert game.dc.final_window.winner is game.players[2]

    history_file = game._game_state_dir / "question_history.jsonl"
    entries = [
        entry
        for entry in map(json.loads, history_file.read_text().splitlines())
        if "round_index" in entry
    ]
    assert [(entry["round_index"], entry["question_number"]) for entry in entries] == [
        (1, 31),
        (2, 32),
    ]
    summary = build_end_game_summary(game)
    assert [player.final_score for player in summary.current_players] == [
        800,
        0,
        1000,
    ]
    # Coryat leaves out both Finals.
    assert [player.coryat for player in summary.current_players] == [0, 0, 0]


def _write_two_final_save(
    saved_dir: object, game_data: object, judged_finals: int
) -> None:
    """Write a save for a one-board, two-Final game with some Finals judged."""
    saved_dir.mkdir()
    (saved_dir / "general.json").write_text(
        json.dumps(
            {
                "game_id": "4453",
                "players": [
                    {"name": "Alice", "player_number": 0},
                    {"name": "Bob", "player_number": 1},
                ],
            }
        )
    )
    lines = []
    for round_index in range(1 + judged_finals):
        for question in game_data.rounds[round_index].questions:
            lines.append(
                json.dumps(
                    {
                        "question_index": [round_index, list(question.index)],
                        "question_number": len(lines) + 1,
                        "round_index": round_index,
                        "category": question.category,
                        "value": question.value,
                        "is_daily_double": question.dd,
                        "buzz_phases": [],
                        "answer_attempts": [],
                        "completed_at": 1700000000.0 + len(lines),
                    }
                )
            )
    (saved_dir / "question_history.jsonl").write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize(
    ("judged_finals", "expect_wagers"),
    [(1, True), (2, False)],
    ids=["first-final-judged", "both-finals-judged"],
)
def test_resume_with_two_finals_picks_first_unjudged_final(
    game: object,
    monkeypatch: object,
    temp_dir: object,
    judged_finals: int,
    expect_wagers: bool,
) -> None:
    """Resume opens the next unjudged Final, or the end of game when none."""
    from jparty.services import game_loader

    restored_data = _two_final_game_data(game)
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / f"saved-two-finals-{judged_finals}"
    _write_two_final_save(saved_dir, restored_data, judged_finals)

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    assert game.current_round is restored_data.rounds[2]
    assert bool(game.buzzer_controller.open_wagers_calls) is expect_wagers
    assert game.dc.loaded_final_judgement == (0 if expect_wagers else 1)
    events = game.keystroke_manager._KeystrokeManager__events
    assert events["GENERATE_GRAPHS"].active is not expect_wagers


def test_resume_with_two_finals_before_any_final_opens_the_first(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """With the board done and no Final judged, resume opens the first Final."""
    from jparty.services import game_loader

    restored_data = _two_final_game_data(game)
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    saved_dir = temp_dir / "saved-two-finals-0"
    _write_two_final_save(saved_dir, restored_data, 0)

    players = [Player("Alice", DummyWaiter(), 0), Player("Bob", DummyWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()

    assert game.current_round is restored_data.rounds[1]
    assert game.buzzer_controller.open_wagers_calls
