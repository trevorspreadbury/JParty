"""Tests that dropouts and fixed results never leave the bracket stuck.

Each test is a case a simulated tournament once got stuck on: a game that
couldn't be seated, with no message, or a conflict reported for a game
that was played correctly.
"""

from dataclasses import replace

import pytest

from jparty.domain.tournament.advancement import (
    TIE_CHASER,
    Eligibility,
    advancement_conflicts,
    eligible_players,
    round_standing,
    seating_gaps,
    seating_problem,
)
from jparty.domain.tournament.drop_choices import (
    DropOption,
    TournamentData,
    apply_drop,
    drop_situation,
)
from jparty.domain.tournament.dropouts import DROP_PLAY_IN, DROP_SLIDE, DROP_VOID
from jparty.domain.tournament.play import RESULT_LOSS, RESULT_WIN, GameResult
from jparty.domain.tournament.roster import PlayerSlot
from jparty.domain.tournament.setup import BracketSettings, plan_games

QF = "Quarterfinals"
SF = "Semifinals"
PRELIMS = "Preliminaries"
R2 = "Second Round"


def rows(key: str, *players: tuple[str, int, bool]) -> list[GameResult]:
    """Return one game's results from ``(player id, score, won)``."""
    return [
        GameResult(
            key,
            player_id,
            player_id.upper(),
            score,
            None,
            "t-1",
            RESULT_WIN if won else RESULT_LOSS,
            key,
        )
        for player_id, score, won in players
    ]


def tournament(
    size: int,
    results: list[GameResult],
    bracket: BracketSettings | None = None,
) -> TournamentData:
    """Return a tournament of players ``p00``, ``p01``, ... with ``results``."""
    slots = tuple(
        PlayerSlot(f"P{index:02d}", player_id=f"p{index:02d}") for index in range(size)
    )
    return TournamentData(bracket or BracketSettings(), slots, tuple(results))


def with_results(data: TournamentData, results: list[GameResult]) -> TournamentData:
    """Return ``data`` with ``results`` added."""
    return replace(data, results=data.results + tuple(results))


def drop(data: TournamentData, player_id: str, choice: str = DROP_SLIDE) -> DropOption:
    """Return the option ``choice`` for ``player_id``."""
    situation = drop_situation(data, player_id)
    assert not situation.problem, situation.problem
    (found,) = [o for o in situation.options if o.dropout.choice == choice]
    return found


def dropped(
    data: TournamentData, player_id: str, choice: str = DROP_SLIDE
) -> TournamentData:
    """Return ``data`` after ``player_id`` drops out with ``choice``."""
    found = drop(data, player_id, choice)
    assert not found.problem, found.problem
    return apply_drop(data, found.dropout)


def eligible(data: TournamentData, key: str) -> Eligibility:
    """Return who may sit in ``key``."""
    return eligible_players(
        data.plan, key, data.slots, data.results, None, data.tiebreaks, data.dropouts
    )


def conflicts(data: TournamentData) -> list[str]:
    """Return the tournament's conflicts."""
    return advancement_conflicts(
        data.plan, data.standings(), data.results, data.names(), data.dropouts
    )


def gaps(data: TournamentData) -> list[str]:
    """Return seats nobody can fill."""
    return seating_gaps(
        data.plan, data.slots, data.results, data.tiebreaks, data.dropouts
    )


def sixteen_quarterfinals(losers: list[int]) -> list[GameResult]:
    """Return QF 1-4 of 16 players: p00, p03, p06, p09 win.

    The second players of each game score ``losers[game]``, the third
    400, 300, 200, 100.
    """
    results = []
    for game in range(4):
        first, second, third = (f"p{3 * game + seat:02d}" for seat in range(3))
        results += rows(
            f"{QF}: QF {game + 1}",
            (first, 9000, True),
            (second, losers[game], False),
            (third, 400 - 100 * game, False),
        )
    return results


def test_slide_after_chase_one_still_seats_chase_two() -> None:
    """A wildcard who leaves after Chase 1 doesn't make Chase 1's chaser chase again."""
    data = tournament(16, sixteen_quarterfinals([8000, 7000, 6000, 5000]))
    assert data.standings()[0].planned_chasers == {
        f"{QF}: Chase 1": "p02",
        f"{QF}: Chase 2": "p10",
    }
    data = with_results(
        data,
        rows(
            f"{QF}: Chase 1",
            ("p12", 3000, True),
            ("p13", 100, False),
            ("p02", 50, False),
        ),
    )
    data = dropped(data, "p01")
    # p10 moves up to a wildcard. p02 has chased, so the next player out
    # chases in Chase 2.
    chase_two = eligible(data, f"{QF}: Chase 2")
    assert chase_two.waiting == ""
    assert chase_two.chasers == ("p05",)
    assert set(chase_two.entrants) == {"p14", "p15"}
    assert conflicts(data) == []


def test_chase_game_played_between_two_dropouts_keeps_its_chaser() -> None:
    """Chase 1 played with the chaser of the moment raises no conflict later."""
    data = tournament(16, sixteen_quarterfinals([8000, 7000, 6000, 5000]))
    data = dropped(data, "p00")
    assert data.standings()[0].planned_chasers[f"{QF}: Chase 1"] == "p05"
    data = with_results(
        data,
        rows(
            f"{QF}: Chase 1",
            ("p12", 3000, True),
            ("p13", 100, False),
            ("p05", 50, False),
        ),
    )
    assert conflicts(data) == []
    data = dropped(data, "p03")
    assert conflicts(data) == []
    chase_two = eligible(data, f"{QF}: Chase 2")
    assert chase_two.waiting == ""
    assert chase_two.chasers == ("p08",)


def eleven_quarterfinals() -> list[GameResult]:
    """Return QF 1-3 of 11 players: p00, p03, p06 win."""
    results = []
    for game in range(3):
        first, second, third = (f"p{3 * game + seat:02d}" for seat in range(3))
        results += rows(
            f"{QF}: QF {game + 1}",
            (first, 9000, True),
            (second, 5000 - 1000 * game, False),
            (third, 400 - 100 * game, False),
        )
    return results


def play_two_player_chase(data: TournamentData, key: str) -> TournamentData:
    """Return ``data`` with chase game ``key`` played by its two new players."""
    eligibility = eligible(data, key)
    assert eligibility.waiting == ""
    assert eligibility.seats == 2
    assert eligibility.chasers == ()
    first, second = eligibility.entrants[:2]
    assert seating_problem(eligibility, [first, second, None]) is None
    return with_results(data, rows(key, (first, 3000, True), (second, 100, False)))


@pytest.mark.parametrize("player_id", ["p01", "p00", "p08"])
def test_slide_that_leaves_no_chaser_makes_the_chase_game_two_players(
    player_id: str,
) -> None:
    """11 players have no spare loser: after a slide, Chase 1 has no chaser.

    That's a wildcard (p01), a winner (p00), or the planned chaser himself
    (p08). The chase game's two new players play it on their own, and its
    winner advances.
    """
    data = tournament(11, eleven_quarterfinals())
    assert data.standings()[0].planned_chasers == {f"{QF}: Chase 1": "p08"}
    option = drop(data, player_id)
    assert option.problem == ""
    data = apply_drop(data, option.dropout)
    chase = eligible(data, f"{QF}: Chase 1")
    assert chase.entrants == ("p09", "p10")
    assert seating_problem(chase, ["p09", None, None]) == (
        "No one is left to chase in this game: choose its 2 new players and "
        "leave one podium empty."
    )
    data = play_two_player_chase(data, f"{QF}: Chase 1")
    standing = data.standings()[0]
    assert standing.decided
    assert len(standing.advancers) == 9
    assert player_id not in standing.advancers
    assert gaps(data) == []
    assert conflicts(data) == []


def test_both_chasers_of_thirteen_players_can_drop_out() -> None:
    """With two chase games, each chaser who leaves takes one chaser seat away."""
    results = []
    for game in range(4):
        first, second, third = (f"p{3 * game + seat:02d}" for seat in range(3))
        results += rows(
            f"{QF}: QF {game + 1}",
            (first, 9000, True),
            (second, 5000 - 1000 * game, False),
            (third, 400 - 100 * game, False),
        )
    data = tournament(13, results)
    planned = data.standings()[0].planned_chasers
    first_out = planned[f"{QF}: Chase 2"]
    data = dropped(data, first_out)
    # The one player left to chase chases in Chase 2; Chase 1 goes without.
    assert eligible(data, f"{QF}: Chase 1").seats == 2
    assert eligible(data, f"{QF}: Chase 2").chasers == (planned[f"{QF}: Chase 1"],)
    data = dropped(data, planned[f"{QF}: Chase 1"])
    for key in (f"{QF}: Chase 1", f"{QF}: Chase 2"):
        data = play_two_player_chase(data, key)
    standing = data.standings()[0]
    assert standing.decided
    assert len(standing.advancers) == 9
    assert gaps(data) == []


def test_slide_after_the_chase_game_lets_the_chaser_move_up() -> None:
    """Once Chase 1 is played, the same slide works: the chaser takes the spot."""
    data = tournament(11, eleven_quarterfinals())
    chaser = data.standings()[0].planned_chasers[f"{QF}: Chase 1"]
    data = with_results(
        data,
        rows(
            f"{QF}: Chase 1",
            ("p09", 3000, True),
            ("p10", 100, False),
            (chaser, 50, False),
        ),
    )
    data = dropped(data, "p01")
    standing = data.standings()[0]
    assert standing.decided
    assert chaser in standing.wildcards
    assert gaps(data) == []


def twelve_prelims_and_r2_one() -> TournamentData:
    """Return 12 players, 3 byes, an 8-player Second Round: Prelims and R2 1 played.

    The Prelims eliminate only p11, so a play-in would have one player.
    """
    bracket = BracketSettings(True, 3, 8)
    results = []
    for game in range(4):
        first, second, third = (f"p{3 * game + seat:02d}" for seat in range(3))
        results += rows(
            f"{PRELIMS}: Prelim {game + 1}",
            (first, 9000 + 100 * game, True),
            (second, 5000 - 100 * game, False),
            (third, 400 - 100 * game, False),
        )
    data = tournament(12, results, bracket)
    standing = data.standings()[0]
    assert standing.eliminated == ("p11",)
    r2_one = f"{R2}: R2 1"
    assert r2_one in [key for key, _round, _game in plan_games(data.plan)]
    seated = eligible(data, r2_one).entrants[:3]
    return with_results(
        data,
        rows(
            r2_one,
            (seated[0], 9000, True),
            (seated[1], 100, False),
            (seated[2], 50, False),
        ),
    )


def test_play_in_with_too_few_players_is_refused() -> None:
    """A play-in needs three players; with one left, it's refused."""
    data = twelve_prelims_and_r2_one()
    bye = data.standings()[0].byes[0]
    option = drop(data, bye, DROP_PLAY_IN)
    assert "would have only 1 of its 3 players" in option.problem


def fourteen_through_chase_one() -> list[GameResult]:
    """Return QF 1-4 and Chase 1 of 14 players; p02 (from QF 1) chased."""
    results = sixteen_quarterfinals([8000, 7000, 6000, 5000])
    results += rows(
        f"{QF}: Chase 1",
        ("p12", 3000, True),
        ("p13", 100, False),
        ("p02", 50, False),
    )
    return results


def test_deleting_a_game_played_before_the_chase_game_is_a_conflict() -> None:
    """Chase 1 can't stand once a regular game it came after is deleted."""
    data = tournament(14, fourteen_through_chase_one())
    assert data.standings()[0].chasers[f"{QF}: Chase 1"] == "p02"
    data = TournamentData(
        data.bracket,
        data.slots,
        tuple(row for row in data.results if row.game_key != f"{QF}: QF 1"),
    )
    assert conflicts(data) == [
        "Chase 1: P12, P13, P02 played it before QF 1 was played. Delete its "
        "results too, and replay it once QF 1 is played."
    ]


def fifteen_prelims() -> TournamentData:
    """Return 15 players, 1 bye, a 9-player Second Round: Prelims played.

    p12 wins with the top score and gets the bye. p13 is the last wildcard.
    """
    bracket = BracketSettings(True, 1, 9)
    results = []
    for game in range(5):
        first, second, third = (f"p{3 * game + seat:02d}" for seat in range(3))
        results += rows(
            f"{PRELIMS}: Prelim {game + 1}",
            (first, 9000 + 100 * game, True),
            (second, 9000 - 100 * game, False),
            (third, 1000 - 10 * game, False),
        )
    return tournament(15, results, bracket)


def test_play_in_allowance_only_covers_play_in_games() -> None:
    """A play-in player who sat in a regular Second Round game is a conflict."""
    data = fifteen_prelims()
    assert data.standings()[0].byes == ("p12",)
    data = with_results(
        data,
        rows(
            f"{R2}: R2 1", ("p13", 5000, True), ("p00", 100, False), ("p01", 50, False)
        ),
    )
    data = dropped(data, "p12", DROP_PLAY_IN)
    # p13's Prelim score was really 995: they're now a play-in player, not a
    # wildcard, so their R2 1 seat no longer stands.
    fixed = tuple(
        GameResult(**{**vars(row), "score": 995})
        if row.player_id == "p13" and row.game_key.startswith(PRELIMS)
        else row
        for row in data.results
    )
    data = TournamentData(data.bracket, data.slots, fixed, dropouts=data.dropouts)
    assert "p13" in data.standings()[0].play_in_players
    assert conflicts(data) == [
        "R2 1: P13 played, but they didn't advance into the Second Round."
    ]


def test_slide_that_would_leave_a_seat_empty_is_refused() -> None:
    """With nobody left beneath, a second wildcard leaving the Second Round is refused."""
    data = fifteen_prelims()
    entrants = list(eligible(data, f"{R2}: R2 1").entrants)
    results = []
    for game in range(3):
        seated = entrants[3 * game : 3 * game + 3]
        results += rows(
            f"{R2}: R2 {game + 1}",
            (seated[0], 9000, True),
            (seated[1], 5000 - 100 * game, False),
            (seated[2], 1000 - 100 * game, False),
        )
    data = with_results(data, results)
    standing = data.standings()[1]
    assert len(standing.eliminated) == 1
    first, second = standing.wildcards[:2]
    data = dropped(data, first)
    assert "The Semifinals would have 8 players for 9 open seats." in (
        drop(data, second).problem
    )


def nine_player_semifinal_one() -> TournamentData:
    """Return 9 players with SF 1 played: p00 wins."""
    return tournament(
        9,
        rows(
            f"{SF}: SF 1", ("p00", 9000, True), ("p01", 400, False), ("p02", 100, False)
        ),
    )


def test_voided_first_round_game_waits_for_the_rest_of_the_round() -> None:
    """The replay's third seat is known only once SF 2 and SF 3 are played."""
    data = dropped(nine_player_semifinal_one(), "p00", DROP_VOID)
    replay = eligible(data, f"{SF}: SF 1")
    assert replay.waiting == (
        "The player taking the dropped seat is known once the rest of the "
        "Semifinals are played."
    )
    assert seating_problem(replay, ["p01", "p02", "p03"]) == replay.waiting
    data = with_results(
        data,
        rows(
            f"{SF}: SF 2", ("p03", 9000, True), ("p04", 500, False), ("p05", 100, False)
        )
        + rows(
            f"{SF}: SF 3", ("p06", 9000, True), ("p07", 300, False), ("p08", 100, False)
        ),
    )
    replay = eligible(data, f"{SF}: SF 1")
    assert replay.waiting == ""
    assert set(replay.entrants) == {"p01", "p02"}
    assert replay.chasers == ("p04",)
    assert gaps(data) == []


def test_three_way_tie_across_the_last_wildcard_and_a_chaser_seat_needs_a_tiebreaker() -> (
    None
):
    """Coryat only settles seeding between chasers, never a wildcard spot.

    In 16 players there are three wildcards and two chasers. Three losers
    tied for the last wildcard and both chaser seats can't be split on
    Coryat, since the cut between the wildcards and the chasers decides
    who gets in.
    """
    data = tournament(16, sixteen_quarterfinals([8000, 7000, 5000, 5000]))
    results = [
        GameResult(**{**vars(row), "score": 5000, "coryat": 6000})
        if row.player_id == "p02"
        else GameResult(**{**vars(row), "coryat": 4000})
        if row.player_id in {"p07", "p10"}
        else row
        for row in data.results
    ]
    standing = round_standing(data.plan, 0, results)
    assert standing.planned_chasers == {}
    (tie,) = standing.ties
    assert tie.reason == TIE_CHASER
    assert set(tie.players) == {"p02", "p07", "p10"}
    assert "p02" not in standing.wildcards


def test_eight_player_void_replays_before_the_chase_game() -> None:
    """Voiding SF 1 of 8 players doesn't leave the replay and Chase 1 waiting on each other."""
    data = tournament(
        8,
        rows(
            f"{SF}: SF 1", ("p00", 9000, True), ("p01", 400, False), ("p02", 100, False)
        )
        + rows(
            f"{SF}: SF 2", ("p03", 9000, True), ("p04", 500, False), ("p05", 300, False)
        ),
    )
    assert [game.name for game in data.plan.rounds[0].games] == [
        "SF 1",
        "SF 2",
        "Chase 1",
    ]
    data = dropped(data, "p00", DROP_VOID)
    replay = eligible(data, f"{SF}: SF 1")
    assert replay.waiting == ""
    assert set(replay.entrants) >= {"p01", "p02"}
    assert replay.chasers == ("p04",)
    data = with_results(
        data,
        rows(
            f"{SF}: SF 1", ("p01", 9000, True), ("p02", 100, False), ("p04", 50, False)
        ),
    )
    # The chase game can be seated now.
    chase = eligible(data, f"{SF}: Chase 1")
    assert chase.waiting == ""
    assert len(chase.entrants) == 2


def twenty_four_with_two_byes() -> TournamentData:
    """Return 24 players, second round, 2 byes, with Prelims 1 and 2 played."""
    bracket = BracketSettings(True, 2)
    data = tournament(24, [], bracket)
    results = []
    for game in range(2):
        first, second, third = (f"p{3 * game + seat:02d}" for seat in range(3))
        results += rows(
            f"{PRELIMS}: Prelim {game + 1}",
            (first, 9000, True),
            (second, 5000, False),
            (third, 400, False),
        )
    return with_results(data, results)


def test_slides_beyond_what_a_round_knocks_out_are_refused_early() -> None:
    """24 players knock out one in the Prelims, so only one Prelims player may slide.

    The second slide is refused while the Prelims are still being played,
    instead of leaving the Second Round a player short later.
    """
    data = twenty_four_with_two_byes()
    layout = data.plan.rounds[0].layout
    assert layout.players - layout.spots == 1
    data = dropped(data, "p00")
    option = drop(data, "p03")
    assert option.problem == (
        "Nobody would be left to take their seat: The Preliminaries would have 1 "
        "too few players left to move up into dropped players' spots."
    )


def test_undo_that_would_leave_a_gap_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Undo Drop checks for seats nobody can fill, like the drop options do."""
    from jparty.domain.tournament import drop_choices

    data = dropped(
        tournament(16, sixteen_quarterfinals([8000, 7000, 6000, 5000])), "p01"
    )
    (dropout,) = data.dropouts
    assert drop_choices.undo_problem(data, dropout) == ""
    monkeypatch.setattr(drop_choices, "gaps_added", lambda before, after: ["A gap."])
    assert drop_choices.undo_problem(data, dropout) == (
        "Nobody would be left for every seat: A gap."
    )


def test_chase_games_played_before_a_void_keep_their_chasers() -> None:
    """A voided Semifinal adds a Quarterfinals wildcard after the chase games.

    The chasers who played then were right, so no conflict is raised.
    """
    data = tournament(16, sixteen_quarterfinals([8000, 7000, 6000, 5000]))
    data = with_results(
        data,
        rows(
            f"{QF}: Chase 1",
            ("p12", 3000, True),
            ("p13", 100, False),
            ("p02", 50, False),
        )
        + rows(
            f"{QF}: Chase 2",
            ("p14", 3000, True),
            ("p15", 100, False),
            ("p10", 50, False),
        ),
    )
    standing = data.standings()[0]
    assert standing.decided
    sf_one = eligible(data, f"{SF}: SF 1").entrants[:3]
    data = with_results(
        data,
        rows(
            f"{SF}: SF 1",
            (sf_one[0], 9000, True),
            (sf_one[1], 100, False),
            (sf_one[2], 50, False),
        ),
    )
    data = dropped(data, sf_one[0], DROP_VOID)
    assert data.standings()[0].wildcards[-1] == "p10"
    assert conflicts(data) == []


def test_undoing_the_dropout_after_a_two_player_chase_game_flags_it() -> None:
    """Once the dropout is taken back there's a chaser again, so the game is listed."""
    from jparty.domain.tournament.drop_choices import undo_drop

    data = dropped(tournament(11, eleven_quarterfinals()), "p01")
    data = play_two_player_chase(data, f"{QF}: Chase 1")
    (dropout,) = data.dropouts
    data = undo_drop(data, dropout)
    assert conflicts(data) == [
        "Chase 1: P09, P10 played it with no chaser, but the chaser should be P08."
    ]
