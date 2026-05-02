"""Unit tests for extracted gameplay collaborators."""

import json

import pytest
from jparty.domain.models import FinalBoard

pytestmark = pytest.mark.unit


def test_clue_flow_correct_answer_updates_score_and_history(
    game: object, players: object
) -> None:
    """Correct answers should score, clear the clue, and persist history."""
    question = game.current_round.questions[0]
    game.load_question(question)
    game.open_responses()

    game.buzz(0)
    game.correct_answer()

    assert players[0].score == question.value
    assert game.active_question is None
    history_lines = (
        (game._game_state_dir / "question_history.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    entry = json.loads(history_lines[0])
    assert entry["answer_attempts"][0]["player_index"] == 0
    assert entry["answer_attempts"][0]["answer_correct"] is True


def test_clue_flow_incorrect_answer_reopens_standard_clue(
    game: object, players: object
) -> None:
    """Incorrect standard-clue rulings should reopen responses."""
    question = game.current_round.questions[0]
    game.load_question(question)
    game.open_responses()

    game.buzz(0)
    timer = game.timer
    game.incorrect_answer()

    assert players[0].score == -question.value
    assert game.active_question is question
    assert timer.resume_calls == 1
    assert game.accepting_responses is True


def test_clue_flow_triple_stumper_reveal_is_optional(game: object) -> None:
    """Triple stumpers should either queue reveal or go straight back."""
    question = game.current_round.questions[0]
    game.load_question(question)
    game.set_reveal_answers_after_triple_stumper(True)

    game.stumped()

    assert game._awaiting_stumped_answer_reveal is True
    game.reveal_stumped_answer()
    assert game.dc.question_widget.reveal_answer_calls == 1


def test_final_jeopardy_flow_orders_players_by_score(
    game: object, players: object
) -> None:
    """Final Jeopardy judging should proceed from lowest to highest score."""
    players[0].score = 600
    players[1].score = 200
    players[2].score = 1000
    for player in players:
        player.wager = 100
        player.finalanswer = player.name
    game.current_round = game.data.rounds[-1]
    assert isinstance(game.current_round, FinalBoard)
    game.active_question = game.current_round.question

    game.final_next_player()

    assert game.answering_player is players[1]
    game.final_correct_answer()
    game.final_next_player()
    assert game.answering_player is players[0]


def test_final_jeopardy_flow_tie_uses_tie_screen(game: object, players: object) -> None:
    """Tied final scores should show the tie display path."""
    game.current_round = game.data.rounds[-1]
    game.active_question = game.current_round.question
    players[0].score = 1000
    players[1].score = 1000
    players[2].score = 200
    game._current_question_history = {"question_number": 61}

    game.end_game()

    assert game.dc.final_window.tie_shown is True


def test_score_recorder_manual_override_appends_history(
    game: object, players: object
) -> None:
    """Manual overrides should append a score-adjustment history entry."""
    changed = game.score_recorder.apply_manual_score_override(players[0], 900)

    assert changed is True
    history_entry = json.loads(
        (game._game_state_dir / "question_history.jsonl").read_text(encoding="utf-8")
    )
    assert history_entry["type"] == "manual_score_adjustment"
    assert history_entry["score_after"] == 900
