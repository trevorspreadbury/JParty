"""Tests for players picking clues and wagering on their phones.

Phones run the board whenever the robot host is on (``robot_game`` in
conftest). ``FakeBuzzerController`` records what each phone is offered.
"""

import json

import pytest

from jparty.domain.models import FinalBoard

pytestmark = pytest.mark.integration


def _offers(game: object) -> list:
    """Return ``(player, board)`` for each board offered to a phone."""
    return game.buzzer_controller.picks_offered


def _start(game: object) -> None:
    """Start a fresh game on the first board."""
    game.start_game()


def _clue(game: object, column: int = 0, row: int = 0) -> object:
    """Return a clue on the current board."""
    return game.current_round.get_question(column, row)


def _win_clue(game: object, i_player: int, column: int, row: int) -> None:
    """Have the player in control pick a clue and ``i_player`` get it right."""
    in_control = game.players.index(game.player_in_control)
    game.phone_pick(in_control, column, row)
    game.clue_reader.speaker.finish()
    game.buzz(i_player)
    game.listener.hear(f"What is {_clue(game, column, row).answer}?")


def test_game_start_offers_the_board_to_seat_one(robot_game: object) -> None:
    """Everyone starts at $0, so the first seat picks first."""
    game = robot_game
    _start(game)
    [(player, board)] = _offers(game)
    assert player is game.players[0]
    assert game.player_in_control is game.players[0]
    assert board["rows"][0] == [200] * 6


def test_phone_pick_loads_the_clue(robot_game: object) -> None:
    """The picked clue is shown and read; the board is withdrawn."""
    game = robot_game
    _start(game)
    ends = game.buzzer_controller.end_pick_calls

    game.phone_pick(0, 2, 3)

    assert game.active_question is _clue(game, 2, 3)
    assert game.clue_reader.speaker.said == [_clue(game, 2, 3).text]
    assert game.buzzer_controller.end_pick_calls > ends


def test_pick_out_of_turn_is_ignored(robot_game: object) -> None:
    """Only the player in control can pick."""
    game = robot_game
    _start(game)
    game.phone_pick(1, 0, 0)
    assert game.active_question is None


def test_pick_of_a_played_clue_offers_the_board_again(robot_game: object) -> None:
    """A stale board on the phone gets a fresh one."""
    game = robot_game
    _start(game)
    _clue(game).complete = True

    game.phone_pick(0, 0, 0)

    assert game.active_question is None
    assert len(_offers(game)) == 2
    assert _offers(game)[-1][1]["rows"][0][0] is None


def test_correct_response_passes_control(robot_game: object) -> None:
    """Whoever gets a clue right picks next."""
    game = robot_game
    _start(game)

    _win_clue(game, 1, 0, 0)

    assert game.player_in_control is game.players[1]
    player, board = _offers(game)[-1]
    assert player is game.players[1]
    assert board["rows"][0][0] is None


def test_clue_nobody_gets_keeps_control(robot_game: object) -> None:
    """Control stays put after a clue nobody gets."""
    game = robot_game
    _start(game)
    game.phone_pick(0, 0, 0)
    game.clue_reader.speaker.finish()
    game.stumped()
    game.delayed[-1][1]()  # The pause before the board returns.

    assert game.active_question is None
    assert _offers(game)[-1][0] is game.players[0]


def test_host_click_still_works_and_withdraws_the_offer(robot_game: object) -> None:
    """The host can pick from the board; the phone stops offering it."""
    game = robot_game
    _start(game)
    ends = game.buzzer_controller.end_pick_calls

    game.load_question(_clue(game, 4, 1))

    assert game.buzzer_controller.end_pick_calls > ends
    assert game.players[0].page != "pick"


def test_next_round_starts_with_the_lowest_score(robot_game: object) -> None:
    """The trailing player picks first in Double Jeopardy."""
    game = robot_game
    _start(game)
    for player, score in zip(game.players, [1200, -400, 600]):
        player.score = score

    game.next_round()

    assert game.current_round is game.data.rounds[1]
    assert _offers(game)[-1][0] is game.players[1]


def test_final_and_finished_boards_are_never_offered(robot_game: object) -> None:
    """There is nothing to pick once the board is cleared or in Final."""
    game = robot_game
    _start(game)
    for question in game.current_round.questions:
        question.complete = True
    offered = len(_offers(game))
    game.offer_pick()
    game.current_round = next(r for r in game.data.rounds if isinstance(r, FinalBoard))
    game.offer_pick()
    assert len(_offers(game)) == offered


def test_without_the_robot_host_phones_never_pick(game_with_players: object) -> None:
    """With a host at the board, phones only buzz."""
    game = game_with_players
    game.start_game()
    assert _offers(game) == []
    question = _clue(game)
    question.dd = True
    game.load_question(question)
    assert game.soliciting_player is True
    assert game.buzzer_controller.dd_wagers_requested == []


@pytest.fixture()
def daily_double(robot_game: object) -> object:
    """Start a game whose player in control has $1000 and finds a DD."""
    game = robot_game
    _start(game)
    game.players[0].score = 1000
    question = _clue(game, 3, 2)
    question.dd = True
    game.phone_pick(0, 3, 2)
    return game


def test_daily_double_asks_the_finder_for_a_wager(daily_double: object) -> None:
    """The player in control wagers on their phone within the limits."""
    game = daily_double
    [(player, minimum, maximum)] = game.buzzer_controller.dd_wagers_requested
    assert player is game.players[0]
    assert (minimum, maximum) == (5, 1000)
    assert game.answering_player is game.players[0]
    assert game.clue_reader.speaker.said == []


def test_phone_daily_double_wager_is_clamped_and_read(daily_double: object) -> None:
    """A wager over the limit is cut to it; then the clue is read."""
    game = daily_double
    question = game.active_question

    game.phone_dd_wager(0, 99999)

    assert question.value == 1000
    assert game.soliciting_player is False
    assert game.clue_reader.speaker.said == [question.text]
    game.clue_reader.speaker.finish()
    assert game.listener.listening
    game.listener.hear(f"What is {question.answer}?")
    assert game.players[0].score == 2000
    assert _offers(game)[-1][0] is game.players[0]


def test_wager_from_another_phone_is_ignored(daily_double: object) -> None:
    """Only the player who found the Daily Double can wager on it."""
    game = daily_double
    value = game.active_question.value
    game.phone_dd_wager(1, 500)
    assert game.active_question.value == value
    assert game.soliciting_player is True


def test_host_can_still_enter_the_wager(
    daily_double: object, monkeypatch: object
) -> None:
    """If the phone is dark, the host clicks the podium as before."""
    game = daily_double
    monkeypatch.setattr(
        "jparty.domain.game_engine.QInputDialog.getInt",
        lambda *args, **kwargs: (300, True),
    )

    game.get_dd_wager(game.players[0])
    game.phone_dd_wager(0, 900)  # Arrives late; ignored.

    assert game.active_question.value == 300
    assert game.buzzer_controller.end_dd_wager_calls >= 1


def test_resume_gives_control_to_the_last_correct_player(
    robot_game: object, sample_saved_game_dir: object, monkeypatch: object
) -> None:
    """A resumed game offers the board to whoever last got a clue right."""
    from jparty.services import game_loader

    game = robot_game
    restored_data = game.data
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: restored_data)
    history_file = sample_saved_game_dir / "question_history.jsonl"
    lines = [json.loads(line) for line in history_file.read_text().splitlines()]
    correct = [
        attempt["player_index"]
        for line in lines
        if line.get("round_index") == 0
        for attempt in line.get("answer_attempts", [])
        if attempt.get("answer_correct")
    ]
    game.prepare_resume_from_dir(sample_saved_game_dir)
    game.buzzer_controller.claimed_saved_players = lambda: list(game.players)
    game.set_robot_host(True)

    game.start_game()

    assert correct, "fixture needs a correct response in round 0"
    assert game.player_in_control.player_number == correct[-1]
    assert _offers(game)[-1][0] is game.player_in_control
