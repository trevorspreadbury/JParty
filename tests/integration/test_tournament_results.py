"""A tournament game saves its players and logs its results when it ends."""

import json

import pytest
from PyQt6.QtCore import Qt

from jparty.domain.models import Player, Question
from jparty.domain.tournament.play import (
    SAVED_PLAYER_ID,
    SAVED_PLAYER_NAME,
    GameResult,
    TournamentGameRef,
)
from jparty.domain.tournament.store import load_results, save_results

REF = TournamentGameRef("Fun", "Quarterfinals: QF 1")
SEATS = [("ann-id", "Ann"), ("bob-id", "Bob"), ("cy-id", "Cy")]


class DummyWaiter:
    """A phone connection that ignores messages."""

    def send(self, message: object, text: object = "") -> None:
        """Ignore a message."""

    def close(self) -> None:
        """Ignore closing."""


@pytest.fixture()
def folders(game: object, monkeypatch: object, temp_dir: object) -> object:
    """Send saves and tournaments to the temp folder; return the tournament's."""
    from jparty.domain import game_engine
    from jparty.services import archive_client, game_loader

    data = game.data
    monkeypatch.setattr(archive_client, "save_game_html", lambda game_id: None)
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: data)
    monkeypatch.setattr(game_engine, "GAME_STATES_DIR", temp_dir / "game_states")
    monkeypatch.setattr(game_engine, "TOURNAMENTS_DIR", temp_dir / "tournaments")
    folder = temp_dir / "tournaments" / "Fun"
    folder.mkdir(parents=True)
    return folder


def _seat_phones(game: object, names: list[str]) -> list[Player]:
    """Connect a phone per name, in podium order."""
    players = [Player(name, DummyWaiter(), index) for index, name in enumerate(names)]
    game.buzzer_controller.connected_players = players
    game.players = players
    game.dc.scoreboard.refresh_players()
    return players


def _start_final_only(game: object) -> None:
    """Start the game at its Final, as a tournament game."""
    game.set_session_game_id("4453")
    game.set_selected_round_indices([len(game.data.rounds) - 1])
    game.set_tournament_game(REF, SEATS)
    game.start_game()


def _finish_final(game: object, scores: list[int], rulings: list[bool]) -> None:
    """Give the players ``scores``, then play Final with no wagers."""
    for player, score in zip(game.players, scores, strict=True):
        game.score_recorder.apply_manual_score_override(player, score)
    for index in range(len(game.players)):
        game.wager(index, 0)
    game.open_final()
    game.final_open_responses()
    for player in game.players:
        game.answer(player, "answer")
    game.final_jeopardy_flow.finished_song()
    for is_correct in rulings:
        game.final_next_player()
        game.final_show_answer()
        if is_correct:
            game.final_correct_answer()
        else:
            game.final_incorrect_answer()
    game.final_next_player()


def test_tournament_game_saves_who_plays_and_logs_results(
    game: object, folders: object
) -> None:
    """general.json names the roster players; the end writes results.csv."""
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    _start_final_only(game)
    general = json.loads((game._game_state_dir / "general.json").read_text())
    assert general["tournament"] == {"name": "Fun", "game_key": REF.game_key}
    assert [
        (player[SAVED_PLAYER_ID], player[SAVED_PLAYER_NAME])
        for player in general["players"]
    ] == SEATS
    saved_game = game._game_state_dir.name

    _finish_final(game, [500, 1200, 300], [True, True, True])

    results = load_results(folders)
    assert [(r.player_id, r.player, r.score, r.result) for r in results] == [
        ("ann-id", "Ann", 500, "loss"),
        ("bob-id", "Bob", 1200, "win"),
        ("cy-id", "Cy", 300, "loss"),
    ]
    assert {r.game for r in results} == {"Fun-4453"}
    assert {r.game_key for r in results} == {REF.game_key}
    assert {r.saved_game for r in results} == {saved_game}
    # Manual score changes aren't clues, so they don't count toward Coryat.
    assert {r.coryat for r in results} == {0}


def test_regular_game_logs_nothing(game: object, folders: object) -> None:
    """A game that isn't a tournament game leaves results.csv alone."""
    _seat_phones(game, ["A", "B", "C"])
    game.set_session_game_id("4453")
    game.set_selected_round_indices([len(game.data.rounds) - 1])
    game.start_game()
    assert "tournament" not in json.loads(
        (game._game_state_dir / "general.json").read_text()
    )
    _finish_final(game, [100, 200, 300], [True, True, True])
    assert not (folders / "results.csv").exists()


def test_resumed_tournament_game_still_logs_results(
    game: object, folders: object
) -> None:
    """Closing mid-game and resuming keeps the tournament players."""
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    _start_final_only(game)
    saved_dir = game._game_state_dir
    game.close_game()
    assert game.tournament_game is None

    game.prepare_resume_from_dir(saved_dir)
    assert game.tournament_game == REF
    # The phones rejoin with other names; the saved roster decides who's who.
    _seat_phones(game, ["X", "Y", "Z"])
    game.start_game()
    # The resumed players get their tournament ids back, for the host page.
    assert [player.tournament_player for player in game.players] == SEATS
    _finish_final(game, [900, 100, 200], [True, True, True])

    results = load_results(folders)
    assert [(r.player_id, r.result) for r in results] == [
        ("ann-id", "win"),
        ("bob-id", "loss"),
        ("cy-id", "loss"),
    ]


def test_resuming_a_finished_game_keeps_fixed_results(
    game: object, folders: object
) -> None:
    """A finished game ends again on resume, without undoing the host's fix."""
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    _start_final_only(game)
    saved_dir = game._game_state_dir
    _finish_final(game, [500, 1200, 300], [True, True, True])
    fixed = [
        GameResult(**{**vars(result), "score": result.score + 1})
        for result in load_results(folders)
    ]
    save_results(folders, fixed)
    game.close_game()

    game.prepare_resume_from_dir(saved_dir)
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    game.start_game()
    assert load_results(folders) == fixed


def test_unwritable_results_warn_the_host(
    game: object, folders: object, monkeypatch: object
) -> None:
    """A results file that can't be saved is reported, not swallowed."""
    from jparty.domain import game_engine
    from jparty.domain.tournament.store import TournamentFileError

    def fail(_folder: object, _results: object) -> None:
        raise TournamentFileError("disk full")

    monkeypatch.setattr(game_engine, "record_game_results", fail)
    warnings = []
    monkeypatch.setattr(
        game, "show_host_warning", lambda title, text: warnings.append(text)
    )
    _seat_phones(game, ["A", "B", "C"])
    _start_final_only(game)
    _finish_final(game, [500, 1200, 300], [True, True, True])
    assert warnings and "disk full" in warnings[0]


def _tie_then_offer_tiebreaker(game: object, monkeypatch: object) -> list[str]:
    """Tie Ann and Bob for first; return the host warnings shown after."""
    warnings = []
    monkeypatch.setattr(
        game, "show_host_warning", lambda title, text: warnings.append(text)
    )
    clues = [
        Question(
            index=(0, 4),
            text="Tiebreaker clue",
            answer="Tiebreaker answer",
            category="Tiebreaker category",
            value=2000,
        )
    ]
    monkeypatch.setattr(
        game, "load_tiebreaker_clues", lambda game_id, is_cancelled: (game_id, clues)
    )
    monkeypatch.setattr(game, "run_in_background", lambda work: work())
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    _start_final_only(game)
    _finish_final(game, [1000, 1000, 200], [False, False, False])
    assert game.keystroke_manager._events["START_TIEBREAKER"].active
    return warnings


def _space(game: object) -> None:
    """Press Space on the host keyboard."""
    game.keystroke_manager.call(Qt.Key.Key_Space)


def test_tiebreaker_win_logs_one_winner(
    game: object, folders: object, monkeypatch: object
) -> None:
    """A tie writes nothing until the tiebreaker is won; then one win."""
    _tie_then_offer_tiebreaker(game, monkeypatch)
    assert not (folders / "results.csv").exists()

    monkeypatch.setattr(game, "prompt_tiebreaker_game_id", lambda: "1234")
    _space(game)  # Pick the game and load its clues.
    _space(game)  # Show the clue after its category.
    _space(game)  # Open buzzing.
    game.buzz(1)
    game.correct_answer()

    results = load_results(folders)
    assert [(r.player_id, r.score, r.result) for r in results] == [
        ("ann-id", 1000, "loss"),
        ("bob-id", 1000, "win"),
        ("cy-id", 200, "loss"),
    ]


def test_tournament_tie_cant_be_declined(
    game: object, folders: object, monkeypatch: object
) -> None:
    """Cancelling the tiebreaker warns the host and keeps the tie open."""
    warnings = _tie_then_offer_tiebreaker(game, monkeypatch)
    monkeypatch.setattr(game, "prompt_tiebreaker_game_id", lambda: None)
    _space(game)

    assert len(warnings) == 1 and "needs a winner" in warnings[0]
    assert game.keystroke_manager._events["START_TIEBREAKER"].active
    assert not game.keystroke_manager._events["GENERATE_GRAPHS"].active
    assert not (folders / "results.csv").exists()

    # The host can still settle it.
    monkeypatch.setattr(game, "prompt_tiebreaker_game_id", lambda: "")
    _space(game)
    _space(game)
    _space(game)
    game.buzz(0)
    game.correct_answer()
    assert [r.result for r in load_results(folders)] == ["win", "loss", "loss"]


def test_seating_needs_one_player_per_phone(game: object, folders: object) -> None:
    """Seating three players on two phones is refused, not paired by position."""
    _seat_phones(game, ["Phone A", "Phone C"])
    with pytest.raises(ValueError, match="one player per phone"):
        game.set_tournament_game(REF, SEATS)
    assert game.tournament_game is None


def test_results_follow_players_who_change_seats_on_resume(
    game: object, folders: object, monkeypatch: object
) -> None:
    """Players reordered in the resume lobby keep their own results."""
    from jparty.web.controller import BuzzerController
    from tests.integration.test_resume_lobby_seats import FakeSocket

    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    _start_final_only(game)
    saved_dir = game._game_state_dir
    game.close_game()

    monkeypatch.setattr(game, "_update_all_lecterns", lambda: None)
    monkeypatch.setattr(game, "_update_lectern_for_player", lambda *a, **k: None)
    controller = BuzzerController(game)
    monkeypatch.setattr(game, "buzzer_controller", controller)
    game.prepare_resume_from_dir(saved_dir)
    claimed = []
    for number in range(3):
        socket = FakeSocket()
        controller.register_socket(socket)
        claimed.append(controller.claim_saved_player(socket, number))
    # Cy's phone moves to the first podium: Cy, Ann, Bob.
    game.move_player_up(claimed[2])
    game.move_player_up(claimed[2])
    assert [player.player_number for player in claimed] == [1, 2, 0]
    game.start_game()
    # Each resumed player keeps their own id at their new seat, so the host
    # page steps through them last podium first: Bob, Ann, Cy.
    assert [player.tournament_player for player in claimed] == SEATS
    from jparty.domain.tournament.roster import PlayerSlot
    from jparty.domain.tournament.store import TournamentSettings, save_tournament

    save_tournament(
        folders.parent,
        TournamentSettings("Fun"),
        [PlayerSlot(name, player_id=player_id) for player_id, name in SEATS],
    )
    controller.tournaments_dir = folders.parent
    page = controller.host_page()
    assert page.in_game
    assert [(p.player_id, p.seat) for p in page.players] == [
        ("bob-id", 3),
        ("ann-id", 2),
        ("cy-id", 1),
    ]

    # Seats in order: Cy 900, Ann 100, Bob 200.
    _finish_final(game, [900, 100, 200], [True, True, True])
    results = {r.player_id: (r.score, r.result) for r in load_results(folders)}
    assert results == {
        "cy-id": (900, "win"),
        "ann-id": (100, "loss"),
        "bob-id": (200, "loss"),
    }


SF_REF = TournamentGameRef("Fun", "Semifinals: SF 1")


def _write_tournament(folder: object, dropouts: tuple = ()) -> None:
    """Save a nine-player "Fun" tournament whose roster includes SEATS."""
    from jparty.domain.tournament.roster import PlayerSlot
    from jparty.domain.tournament.store import (
        DROPOUTS_FILE,
        TournamentSettings,
        dropouts_csv_text,
        save_tournament,
    )

    slots = [PlayerSlot(name, player_id=player_id) for player_id, name in SEATS]
    slots += [PlayerSlot(f"P{index}", player_id=f"p{index}") for index in range(6)]
    save_tournament(folder.parent, TournamentSettings("Fun"), slots)
    if dropouts:
        (folder / DROPOUTS_FILE).write_text(
            dropouts_csv_text(list(dropouts)), encoding="utf-8"
        )


def _start_semifinal(game: object) -> None:
    """Start SF 1 at its Final, as a tournament game."""
    game.set_session_game_id("4453")
    game.set_selected_round_indices([len(game.data.rounds) - 1])
    game.set_tournament_game(SF_REF, SEATS)
    game.start_game()


def _warnings(game: object, monkeypatch: object) -> list[str]:
    """Collect the host warnings ``game`` shows."""
    shown = []
    monkeypatch.setattr(
        game, "show_host_warning", lambda title, text: shown.append(text)
    )
    return shown


def test_a_stale_save_doesnt_replace_another_saves_results(
    game: object, folders: object, monkeypatch: object
) -> None:
    """Finishing an abandoned save of a played game keeps the played rows."""
    warnings = _warnings(game, monkeypatch)
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    data = game.data
    _start_final_only(game)
    abandoned = game._game_state_dir
    game.close_game()
    # The game is started again from the beginning and finished.
    game.data = data
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    _start_final_only(game)
    assert game._game_state_dir != abandoned
    _finish_final(game, [500, 1200, 300], [True, True, True])
    played = load_results(folders)
    game.close_game()

    # The tournament's files can't be read here, so only the end checks.
    game.prepare_resume_from_dir(abandoned)
    assert game.tournament_game == REF
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    game.start_game()
    _finish_final(game, [900, 100, 200], [True, True, True])

    assert load_results(folders) == played
    assert warnings and "already has results from another saved game" in warnings[0]


def test_load_saved_of_a_played_game_resumes_as_a_regular_game(
    game: object, folders: object
) -> None:
    """Load Saved checks the tournament, so the stale save logs nothing."""
    _write_tournament(folders)
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    data = game.data
    _start_semifinal(game)
    abandoned = game._game_state_dir
    game.close_game()
    game.data = data
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    _start_semifinal(game)
    _finish_final(game, [500, 1200, 300], [True, True, True])
    played = load_results(folders)
    game.close_game()

    loaded = game.read_saved_game(abandoned)
    assert "already has results from another saved game" in loaded.tournament_problem
    game.apply_saved_game(loaded)
    assert game.tournament_game is None
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    game.start_game()
    _finish_final(game, [900, 100, 200], [True, True, True])
    assert load_results(folders) == played


def test_load_saved_with_a_dropped_player_logs_no_results(
    game: object, folders: object
) -> None:
    """A save whose player dropped out resumes untracked, so no rows for them."""
    from jparty.domain.tournament.dropouts import DROP_REPLACE, Dropout

    _write_tournament(folders)
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    _start_semifinal(game)
    saved_dir = game._game_state_dir
    game.close_game()
    _write_tournament(
        folders, (Dropout("bob-id", "Semifinals", DROP_REPLACE, other_id="p0"),)
    )

    loaded = game.read_saved_game(saved_dir)
    assert loaded.tournament_problem.startswith("Bob dropped out")
    game.apply_saved_game(loaded)
    assert game.tournament_game is None
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    game.start_game()
    _finish_final(game, [900, 100, 200], [True, True, True])
    assert load_results(folders) == []


def test_load_saved_of_a_good_save_still_logs_results(
    game: object, folders: object
) -> None:
    """A save that passes the checks resumes as a tournament game."""
    _write_tournament(folders)
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    _start_semifinal(game)
    saved_dir = game._game_state_dir
    game.close_game()

    loaded = game.read_saved_game(saved_dir)
    assert loaded.tournament_problem is None
    game.apply_saved_game(loaded)
    assert game.tournament_game == SF_REF
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    game.start_game()
    _finish_final(game, [900, 100, 200], [True, True, True])
    assert [r.player_id for r in load_results(folders)] == [p for p, _ in SEATS]


def test_results_naming_a_dropped_player_arent_saved(
    game: object, folders: object, monkeypatch: object
) -> None:
    """The end of the game checks dropouts too, and warns instead."""
    from jparty.domain.tournament.dropouts import DROP_SLIDE, Dropout

    warnings = _warnings(game, monkeypatch)
    _seat_phones(game, ["Phone A", "Phone B", "Phone C"])
    _start_final_only(game)
    _write_tournament(folders, (Dropout("cy-id", "Quarterfinals", DROP_SLIDE),))
    _finish_final(game, [500, 1200, 300], [True, True, True])
    assert load_results(folders) == []
    assert warnings and warnings[0].startswith("Cy dropped out")
