"""Tests for the tiebreaker played when players tie for first (#44)."""

import pytest
from PyQt6.QtCore import Qt

from jparty.domain.models import Question
from jparty.domain.state import build_end_game_summary

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

    def load(game_id: str) -> tuple[str, list]:
        game.loaded_game_ids.append(game_id)
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
def test_tie_at_zero_or_below_has_no_tiebreaker(
    game_with_players: object, scores: tuple
) -> None:
    """Nobody wins when the top score is not positive, so nothing to break."""
    game = game_with_players
    for player, score in zip(game.players, scores, strict=True):
        player.score = score
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
