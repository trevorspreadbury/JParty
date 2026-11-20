"""Tests for the tiebreaker played when players tie for first (#44)."""

import json

import pytest
from PyQt6.QtCore import Qt

from jparty.domain.models import Question
from jparty.domain.state import (
    build_end_game_summary,
    history_score_totals,
    read_history_file,
)

pytestmark = pytest.mark.integration


def _clue(number: int, value: int = 2000) -> Question:
    """Return one tiebreaker clue."""
    return Question(
        index=(number, 4),
        text=f"Tiebreaker clue {number}",
        answer=f"Tiebreaker answer {number}",
        category=f"Tiebreaker category {number}",
        value=value,
    )


@pytest.fixture()
def tied_game(game_with_players: object, monkeypatch: object) -> object:
    """Return a game that just ended with Alice and Bob tied for first.

    The host prompt answers with game id ``1234``, loading runs on the
    test thread, and host warnings are recorded instead of shown.
    """
    game = game_with_players
    game.players[0].score = 1000
    game.players[1].score = 1000
    game.players[2].score = 200
    game.prompt_requests = 0
    game.loaded_game_ids = []
    game.host_warnings = []
    game.tiebreaker_clue_queue = [_clue(1), _clue(2)]

    def prompt() -> str:
        game.prompt_requests += 1
        return "1234"

    def load(game_id: str, is_cancelled: object) -> tuple[str, list]:
        game.loaded_game_ids.append(game_id)
        game.load_is_cancelled = is_cancelled
        return game_id, list(game.tiebreaker_clue_queue)

    monkeypatch.setattr(game, "prompt_tiebreaker_game_id", prompt)
    monkeypatch.setattr(game, "load_tiebreaker_clues", load)
    monkeypatch.setattr(game, "run_in_background", lambda work: work())
    monkeypatch.setattr(
        game,
        "show_host_warning",
        lambda title, text: game.host_warnings.append(text),
    )
    game.end_game()
    return game


def _space(game: object) -> None:
    """Press Space on the host keyboard."""
    game.keystroke_manager.call(Qt.Key.Key_Space)


def _start_first_clue(game: object) -> None:
    """Load the tiebreaker, show the first clue, and open buzzing."""
    _space(game)  # Prompt for the game and load its clues.
    _space(game)  # Show the first clue after its category.
    _space(game)  # Open buzzing.


def test_tie_offers_tiebreaker_instead_of_summary(tied_game: object) -> None:
    """A tie for first on a positive score waits for the host to start one."""
    game = tied_game
    assert game.dc.final_window.tie_shown is True
    assert game.keystroke_manager._events["START_TIEBREAKER"].active
    assert not game.keystroke_manager._events["GENERATE_GRAPHS"].active
    assert game.tiebreaker_flow.contenders == game.players[:2]


@pytest.mark.parametrize("scores", [(0, 0, -200), (-400, -400, -800)])
def test_tie_at_zero_or_below_still_offers_tiebreaker(
    game_with_players: object, scores: tuple
) -> None:
    """The two leaders can break a tie whatever their score."""
    game = game_with_players
    for player, score in zip(game.players, scores, strict=True):
        player.score = score
    game.end_game()
    assert game.keystroke_manager._events["START_TIEBREAKER"].active
    assert not game.keystroke_manager._events["GENERATE_GRAPHS"].active
    assert game.tiebreaker_flow.contenders == game.players[:2]


def test_no_tiebreaker_for_a_single_leader(game_with_players: object) -> None:
    """A clear winner goes straight to the summary."""
    game = game_with_players
    game.players[0].score = -200
    game.players[1].score = -400
    game.players[2].score = -400
    game.end_game()
    assert game.keystroke_manager._events["GENERATE_GRAPHS"].active
    assert not game.keystroke_manager._events["START_TIEBREAKER"].active


def test_cancelling_the_prompt_ends_in_a_tie(
    tied_game: object, monkeypatch: object
) -> None:
    """Cancel keeps the tie and moves on to the summary."""
    game = tied_game
    monkeypatch.setattr(game, "prompt_tiebreaker_game_id", lambda: None)
    _space(game)
    assert game.loaded_game_ids == []
    assert game.keystroke_manager._events["GENERATE_GRAPHS"].active
    assert game.dc.loaded_tiebreakers == []


def test_tiebreaker_shows_category_then_clue(tied_game: object) -> None:
    """The category is shown first, then Space reveals the clue."""
    game = tied_game
    _space(game)
    assert game.loaded_game_ids == ["1234"]
    first_clue = game.dc.loaded_tiebreakers[0]
    assert first_clue.text == "Tiebreaker clue 1"
    assert game.active_question is first_clue
    assert game.dc.question_widget.show_question_calls == 0

    _space(game)
    assert game.dc.question_widget.show_question_calls == 1
    assert game.keystroke_manager._events["OPEN_RESPONSES"].active


def test_only_tied_players_can_buzz(tied_game: object) -> None:
    """The player who isn't tied for first cannot buzz in."""
    game = tied_game
    _start_first_clue(game)
    game.buzz(2)
    assert game.answering_player is None
    game.buzz(1)
    assert game.answering_player is game.players[1]


def test_correct_answer_wins_without_changing_scores(tied_game: object) -> None:
    """The first correct response wins, and the scores stay tied."""
    game = tied_game
    _start_first_clue(game)
    game.buzz(1)
    game.correct_answer()

    assert [player.score for player in game.players] == [1000, 1000, 200]
    assert game.tiebreaker_winner is game.players[1]
    assert game.dc.final_window.winner is game.players[1]
    assert game.dc.unloaded_tiebreakers == 1
    assert game.tiebreaker_flow.active is False
    assert game.active_question is None
    assert game.keystroke_manager._events["GENERATE_GRAPHS"].active


def test_incorrect_answer_rebounds_then_moves_to_next_clue(
    tied_game: object,
) -> None:
    """A miss reopens buzzing; once both tied players miss, a new clue comes."""
    game = tied_game
    _start_first_clue(game)
    game.buzz(0)
    game.incorrect_answer()
    assert game.players[0].score == 1000
    assert game.accepting_responses is True

    game.buzz(0)
    assert game.answering_player is None
    game.buzz(1)
    game.incorrect_answer()
    assert game.players[1].score == 1000
    assert game.song_player.stumped_calls == 1
    assert game.keystroke_manager._events["TIEBREAKER_NEXT_CLUE"].active

    _space(game)
    assert game.dc.loaded_tiebreakers[-1].text == "Tiebreaker clue 2"
    # Both tied players can buzz again on the new clue.
    _space(game)
    _space(game)
    game.buzz(0)
    assert game.answering_player is game.players[0]


def test_timeout_reveals_answer_when_option_is_on(tied_game: object) -> None:
    """A clue nobody buzzes on reveals its answer if the host enabled that."""
    game = tied_game
    game.set_reveal_answers_after_triple_stumper(True)
    _start_first_clue(game)
    game.timer.fire()

    assert game.keystroke_manager._events["TIEBREAKER_REVEAL_ANSWER"].active
    clue_widget = game.dc.question_widget
    _space(game)
    assert clue_widget.reveal_answer_calls == 1
    _space(game)
    assert game.dc.loaded_tiebreakers[-1].text == "Tiebreaker clue 2"


def test_running_out_of_clues_returns_to_the_tie(tied_game: object) -> None:
    """When every clue is missed, the host can start over with another game."""
    game = tied_game
    game.tiebreaker_clue_queue = [_clue(1)]
    _start_first_clue(game)
    game.timer.fire()
    _space(game)

    assert game.tiebreaker_flow.active is False
    assert game.active_question is None
    assert game.dc.unloaded_tiebreakers == 1
    assert "no more tiebreaker clues" in game.host_warnings[0]
    assert game.keystroke_manager._events["START_TIEBREAKER"].active
    _space(game)
    assert game.prompt_requests == 2


def test_failed_load_warns_and_offers_again(tied_game: object) -> None:
    """A game that gives no clues warns the host and re-offers the prompt."""
    game = tied_game
    game.tiebreaker_clue_queue = []
    _space(game)
    assert "Couldn't load tiebreaker clues from game 1234" in game.host_warnings[0]
    assert game.dc.loaded_tiebreakers == []
    assert game.keystroke_manager._events["START_TIEBREAKER"].active


def test_clues_for_an_old_request_are_ignored(
    tied_game: object, monkeypatch: object
) -> None:
    """Clues that arrive after the game closed never start a tiebreaker."""
    game = tied_game
    pending = []
    monkeypatch.setattr(game, "run_in_background", pending.append)
    _space(game)
    game.tiebreaker_flow.reset()
    pending[0]()
    assert game.dc.loaded_tiebreakers == []
    assert game.tiebreaker_flow.active is False


def test_closing_the_game_cancels_a_random_game_search(tied_game: object) -> None:
    """The load's cancel check turns on once the request is no longer needed."""
    game = tied_game
    _space(game)
    assert game.load_is_cancelled() is False
    game.tiebreaker_flow.reset()
    assert game.load_is_cancelled() is True


def _page(player: object) -> str:
    """Return the page a player's phone is showing."""
    return player.page


def test_only_tied_players_phones_show_the_buzzer(tied_game: object) -> None:
    """Tied players get the buzz button; everyone else sees they sit out."""
    game = tied_game
    alice, bob, cara = game.players
    _start_first_clue(game)
    assert [_page(alice), _page(bob), _page(cara)] == ["buzz", "buzz", "sitout"]

    game.buzz(1)
    game.correct_answer()
    assert [_page(alice), _page(bob), _page(cara)] == ["null", "null", "null"]


def test_phones_clear_when_the_tiebreaker_runs_out(tied_game: object) -> None:
    """Running out of clues takes the buzz button away until the next game."""
    game = tied_game
    game.tiebreaker_clue_queue = [_clue(1)]
    _start_first_clue(game)
    game.timer.fire()
    _space(game)
    assert {player.page for player in game.players} == {"null"}


def test_failed_load_leaves_phones_alone(tied_game: object) -> None:
    """A load that gives no clues never hands out the buzz button."""
    game = tied_game
    for player in game.players:
        player.page = "null"
    game.tiebreaker_clue_queue = []
    _space(game)
    assert {player.page for player in game.players} == {"null"}


def _forbid_score_dialog(monkeypatch: object) -> None:
    """Fail the test if the manual score override dialog opens."""

    def get_int(*args: object, **kwargs: object) -> tuple:
        raise AssertionError("the score override dialog should not open")

    monkeypatch.setattr("jparty.domain.game_engine.QInputDialog.getInt", get_int)


def test_scores_are_locked_from_the_tie_offer(
    tied_game: object, monkeypatch: object
) -> None:
    """Edit Score and podium overrides stay off at the tie and after run-out.

    The tied players are fixed when the tie is offered, so a later score
    change could leave players who are no longer tied in the tiebreaker.
    """
    game = tied_game
    game._has_editable_clue = True
    _forbid_score_dialog(monkeypatch)
    assert game.can_open_score_editor() is False
    game.adjust_score(game.players[1])

    game.tiebreaker_clue_queue = [_clue(1)]
    _start_first_clue(game)
    game.timer.fire()
    _space(game)
    assert game.active_question is None
    assert game.can_open_score_editor() is False
    game.adjust_score(game.players[1])
    assert [player.score for player in game.players] == [1000, 1000, 200]


def test_scores_stay_locked_after_a_win(tied_game: object, monkeypatch: object) -> None:
    """A won tiebreaker keeps the scores, so the winner card matches the summary."""
    game = tied_game
    game._has_editable_clue = True
    _forbid_score_dialog(monkeypatch)
    _start_first_clue(game)
    game.buzz(0)
    game.correct_answer()
    assert game.keystroke_manager._events["GENERATE_GRAPHS"].active
    assert game.can_open_score_editor() is False
    game.adjust_score(game.players[1])
    assert [player.score for player in game.players] == [1000, 1000, 200]


def test_scores_stay_locked_after_a_declined_tiebreaker(
    tied_game: object, monkeypatch: object
) -> None:
    """Declining keeps the tie the tie card shows."""
    game = tied_game
    game._has_editable_clue = True
    monkeypatch.setattr(game, "prompt_tiebreaker_game_id", lambda: None)
    _space(game)
    assert game.keystroke_manager._events["GENERATE_GRAPHS"].active
    assert game.can_open_score_editor() is False


def test_single_leader_keeps_scores_editable(game_with_players: object) -> None:
    """With no tie for first, the end of the game leaves Edit Score alone."""
    game = game_with_players
    game.players[0].score = 1000
    game._has_editable_clue = True
    game.end_game()
    assert game.can_open_score_editor() is True


def test_summary_names_the_tiebreaker_winner(tied_game: object) -> None:
    """The end-of-game summary reports one winner after a tiebreaker."""
    game = tied_game
    game._save_general_state()
    summary = build_end_game_summary(game)
    assert summary.is_tie is True

    _start_first_clue(game)
    game.buzz(0)
    game.correct_answer()
    summary = build_end_game_summary(game)
    assert summary.is_tie is False
    assert summary.winner_player_numbers == [game.players[0].player_number]


def _tiebreaker_lines(game: object) -> list[dict]:
    """Return the saved ``tiebreaker_clue`` lines."""
    path = game._game_state_dir / "question_history.jsonl"
    lines = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    return [line for line in lines if line.get("type") == "tiebreaker_clue"]


def test_each_tiebreaker_clue_is_saved_to_history(
    tied_game: object, time_controller: object
) -> None:
    """A missed clue and the winning clue each get a tiebreaker_clue line."""
    game = tied_game
    game.question_number = 62
    _start_first_clue(game)
    time_controller.advance(2)
    game.buzz(0)
    time_controller.advance(2)
    game.incorrect_answer()
    time_controller.advance(2)
    game.buzz(1)
    time_controller.advance(2)
    game.incorrect_answer()
    _space(game)  # Next clue.
    _space(game)
    _space(game)
    game.buzz(1)
    game.correct_answer()

    missed, won = _tiebreaker_lines(game)
    assert missed["question_number"] == 62
    assert missed["source_game_id"] == "1234"
    assert missed["source_question_index"] == [1, 4]
    assert missed["category"] == "Tiebreaker category 1"
    assert missed["text"] == "Tiebreaker clue 1"
    assert missed["answer"] == "Tiebreaker answer 1"
    assert missed["value"] == 2000
    assert missed["contenders"] == [0, 1]
    assert missed["winner"] is None
    assert [
        (attempt["player_index"], attempt["answer_correct"])
        for attempt in missed["answer_attempts"]
    ] == [(0, False), (1, False)]
    assert [phase["phase_type"] for phase in missed["buzz_phases"]] == [
        "main",
        "rebound",
    ]
    assert missed["buzz_phases"][0]["buzz_attempts"][0]["question_index"] is None
    assert len(missed["responses_open_times"]) == len(missed["buzz_phases"])

    assert won["question_number"] == 63
    assert won["winner"] == 1
    assert won["answer_attempts"][0]["answer_correct"] is True


def test_unanswered_tiebreaker_clue_is_saved(tied_game: object) -> None:
    """A clue that times out with no buzz is saved with no winner."""
    game = tied_game
    _start_first_clue(game)
    game.timer.fire()
    (line,) = _tiebreaker_lines(game)
    assert line["winner"] is None
    assert line["answer_attempts"] == []
    assert line["buzz_phases"] == []


def test_tiebreaker_lines_leave_scores_and_stats_alone(tied_game: object) -> None:
    """Tiebreaker rulings stay out of the score chain and per-clue stats."""
    game = tied_game
    game._save_general_state()
    _start_first_clue(game)
    game.buzz(0)
    game.correct_answer()

    entries = read_history_file(game._game_state_dir / "question_history.jsonl")
    assert history_score_totals(entries) == {}
    summary = build_end_game_summary(game)
    alice = summary.current_players[0]
    assert (alice.right_count, alice.questions_buzzed_on) == (0, 0)
    assert summary.question_count == 0


def test_summary_winner_is_read_from_history(tied_game: object) -> None:
    """The saved winner decides the summary, even without the live game."""
    game = tied_game
    game._save_general_state()
    _start_first_clue(game)
    game.buzz(1)
    game.correct_answer()
    game.tiebreaker_winner = None
    summary = build_end_game_summary(game)
    assert summary.winner_player_numbers == [1]


def test_seat_change_renumbers_tiebreaker_players(tied_game: object) -> None:
    """A later player_renumber line remaps contenders and the winner."""
    game = tied_game
    _start_first_clue(game)
    game.buzz(1)
    game.correct_answer()
    path = game._game_state_dir / "question_history.jsonl"
    with path.open("a", encoding="utf-8") as history:
        renumber = {"type": "player_renumber", "mapping": {"0": 2, "1": 0, "2": 1}}
        history.write(json.dumps(renumber) + "\n")

    (line,) = [
        entry
        for entry in read_history_file(path)
        if entry.get("type") == "tiebreaker_clue"
    ]
    assert line["contenders"] == [2, 0]
    assert line["winner"] == 0
    assert line["answer_attempts"][0]["player_index"] == 0


def _write_tied_save(
    saved_dir: object, game_data: object, tiebreaker_lines: list
) -> None:
    """Write a save whose first board is played out to a 3000-3000 tie."""
    saved_dir.mkdir()
    general = {
        "game_id": "4453",
        "players": [
            {"name": "Alice", "player_number": 0},
            {"name": "Bob", "player_number": 1},
        ],
        "selected_round_indices": [0],
    }
    (saved_dir / "general.json").write_text(json.dumps(general), encoding="utf-8")
    scores = {0: 0, 1: 0}
    lines = []
    for number, question in enumerate(game_data.rounds[0].questions, start=1):
        player = question.index[0] % 2
        before = scores[player]
        scores[player] += question.value
        lines.append(
            {
                "question_index": [0, list(question.index)],
                "question_number": number,
                "round_index": 0,
                "category": question.category,
                "value": question.value,
                "is_daily_double": False,
                "buzz_phases": [],
                "answer_attempts": [
                    {
                        "player_index": player,
                        "answer_correct": True,
                        "timestamp": 1700000000.0 + number,
                        "score_before": before,
                        "score_after": scores[player],
                    }
                ],
                "completed_at": 1700000000.0 + number,
            }
        )
    lines.extend(tiebreaker_lines)
    (saved_dir / "question_history.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )


def _tiebreaker_line(question_number: int, winner: int | None) -> dict:
    """Return one saved tiebreaker_clue line between players 0 and 1."""
    return {
        "type": "tiebreaker_clue",
        "question_number": question_number,
        "source_game_id": "1234",
        "source_question_index": [0, 4],
        "category": "RIVERS",
        "value": 2000,
        "text": "Clue",
        "answer": "Answer",
        "contenders": [0, 1],
        "buzz_phases": [],
        "answer_attempts": [],
        "winner": winner,
        "completed_at": 1700001000.0 + question_number,
    }


def _resume(game: object, saved_dir: object, monkeypatch: object) -> None:
    """Resume ``saved_dir`` with Alice and Bob back in their seats."""
    from jparty.domain.models import Player
    from jparty.services import game_loader
    from tests.conftest import FakeWaiter

    game_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: game_data)
    players = [Player("Alice", FakeWaiter(), 0), Player("Bob", FakeWaiter(), 1)]
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    game.start_game()


def test_resume_after_won_tiebreaker_ends_with_that_winner(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """A tiebreaker won before the app closed is not offered again."""
    saved_dir = temp_dir / "saved-won-tiebreaker"
    _write_tied_save(
        saved_dir, game.data, [_tiebreaker_line(31, None), _tiebreaker_line(32, 1)]
    )
    _resume(game, saved_dir, monkeypatch)
    assert [player.score for player in game.players] == [9000, 9000]
    assert game.tiebreaker_winner is game.players[1]

    game.keystroke_manager.call(Qt.Key.Key_Space)  # Finished board -> end.
    events = game.keystroke_manager._events
    assert game.dc.final_window.winner is game.players[1]
    assert events["GENERATE_GRAPHS"].active
    assert not events["START_TIEBREAKER"].active


def test_resume_mid_tiebreaker_offers_it_and_continues_numbering(
    game: object, monkeypatch: object, temp_dir: object
) -> None:
    """With no winner saved, resume offers a tiebreaker numbered after the last."""
    saved_dir = temp_dir / "saved-mid-tiebreaker"
    _write_tied_save(saved_dir, game.data, [_tiebreaker_line(31, None)])
    _resume(game, saved_dir, monkeypatch)
    assert game.tiebreaker_winner is None
    assert game.question_number == 32

    game.keystroke_manager.call(Qt.Key.Key_Space)
    assert game.keystroke_manager._events["START_TIEBREAKER"].active


def test_prompt_shows_seats_for_signed_names(
    tied_game: object, monkeypatch: object
) -> None:
    """A signature's image data never reaches the prompt text.

    Pasting it in made the dialog so wide that its buttons were off screen.
    """
    game = tied_game
    game.players[1].name = "data:image/png;base64," + "A" * 20000
    prompts = []

    def get_text(parent: object, title: str, label: str) -> tuple:
        prompts.append(label)
        return "1234", True

    monkeypatch.setattr("jparty.domain.game_engine.QInputDialog.getText", get_text)
    # The fixture replaces the prompt on the instance; call the real one.
    assert type(game).prompt_tiebreaker_game_id(game) == "1234"
    assert prompts[0].startswith("Alice and Player 2 are tied for first.")
    assert "base64" not in prompts[0]
    assert len(prompts[0]) < 300
