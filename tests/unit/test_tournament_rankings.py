"""Tests for ranking a tournament's players."""

from dataclasses import replace

from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament import TournamentOptions, plan_tournament
from jparty.domain.tournament_dropouts import DROP_REDUCE, Dropout
from jparty.domain.tournament_rankings import NOT_PLAYED_TEXT, tournament_rankings
from tests.unit.test_tournament_advancement import SF, play

FINAL = "Final: Final"


def nine_players() -> list[PlayerSlot]:
    """Return a roster whose ids and names are ``a``..``i``."""
    return [PlayerSlot(player_id, player_id=player_id) for player_id in "abcdefghi"]


def semifinals() -> list:
    """Return results for all three Semifinals, won by c, d, and g."""
    return (
        play(f"{SF}: SF 1", {"a": 100, "b": 200, "c": 3000}, "c")
        + play(f"{SF}: SF 2", {"d": 4000, "e": 500, "f": 600}, "d")
        + play(f"{SF}: SF 3", {"g": 2000, "h": 200, "i": 900}, "g")
    )


def test_nobody_is_ranked_before_any_game() -> None:
    """With no results, every player is listed without a rank, in order."""
    plan = plan_tournament(TournamentOptions(9))
    rankings = tournament_rankings(plan, nine_players(), [])
    assert [row.name for row in rankings] == list("abcdefghi")
    assert {row.rank for row in rankings} == {None}
    assert {row.status for row in rankings} == {NOT_PLAYED_TEXT}


def test_players_in_an_undecided_round_rank_by_score() -> None:
    """Players who've played rank above those who haven't, by score."""
    plan = plan_tournament(TournamentOptions(9))
    results = play(f"{SF}: SF 1", {"a": 100, "b": 200, "c": 3000}, "c")
    rankings = tournament_rankings(plan, nine_players(), results)
    assert [(row.rank, row.name) for row in rankings[:3]] == [
        (1, "c"),
        (2, "b"),
        (3, "a"),
    ]
    assert rankings[0].games == 1
    assert rankings[0].best_score == 3000
    assert rankings[0].reached == SF
    assert rankings[3].rank is None


def test_finalists_rank_above_players_knocked_out() -> None:
    """Winners heading to the Final come first; the eliminated are out."""
    plan = plan_tournament(TournamentOptions(9))
    rankings = tournament_rankings(plan, nine_players(), semifinals())
    top = [(row.rank, row.name, row.reached) for row in rankings[:3]]
    assert top == [(1, "d", "Final"), (2, "c", "Final"), (3, "g", "Final")]
    assert [row.name for row in rankings[3:]] == ["i", "f", "e", "b", "h", "a"]
    assert all(row.out for row in rankings[3:])
    # b and h both scored 200 in the Semifinals, so they share a place.
    assert [row.rank for row in rankings[3:]] == [4, 5, 6, 7, 7, 9]


def test_the_champion_comes_first() -> None:
    """The Final's winner is the champion, whatever they scored."""
    plan = plan_tournament(TournamentOptions(9))
    results = semifinals() + play(FINAL, {"c": 100, "d": 50, "g": 9000}, "c")
    rankings = tournament_rankings(plan, nine_players(), results)
    assert rankings[0].name == "c"
    assert rankings[0].reached == "Champion"
    assert rankings[0].status == "champion"
    assert rankings[0].games == 2
    assert rankings[0].total_score == 3100
    assert [row.name for row in rankings[1:3]] == ["g", "d"]


def test_coryat_adds_up_recorded_scores() -> None:
    """Coryat totals skip games that didn't record one."""
    plan = plan_tournament(TournamentOptions(9))
    results = play(f"{SF}: SF 1", {"a": 100, "b": 200, "c": 3000}, "c")
    results[2] = replace(results[2], coryat=2400)
    rankings = {
        row.name: row for row in tournament_rankings(plan, nine_players(), results)
    }
    assert rankings["c"].coryat == 2400
    assert rankings["a"].coryat is None


def test_dropped_out_players_are_out() -> None:
    """A player who dropped out before playing has no rank."""
    slots = nine_players()
    dropouts = [Dropout("i", SF, DROP_REDUCE)]
    plan = plan_tournament(TournamentOptions(9))
    rankings = {
        row.name: row for row in tournament_rankings(plan, slots, [], (), dropouts)
    }
    assert rankings["i"].rank is None
    assert rankings["i"].status == "dropped out"
    assert rankings["i"].out


def test_an_invalid_plan_ranks_nobody() -> None:
    """A bracket that doesn't work still lists the roster."""
    rankings = tournament_rankings(None, nine_players(), semifinals())
    assert {row.rank for row in rankings} == {None}
    assert rankings[0].games == 1
