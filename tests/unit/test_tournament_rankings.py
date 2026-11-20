"""Tests for ranking a tournament's players."""

from dataclasses import replace

from jparty.domain.tournament.advancement import Tiebreak
from jparty.domain.tournament.bracket import TournamentOptions, plan_tournament
from jparty.domain.tournament.dropouts import (
    DROP_PLAY_IN,
    DROP_REDUCE,
    DROP_SLIDE,
    Dropout,
)
from jparty.domain.tournament.rankings import NOT_PLAYED_TEXT, tournament_rankings
from jparty.domain.tournament.roster import PlayerSlot
from tests.unit.test_tournament_advancement import (
    QF,
    SF,
    play,
    twelve_player_quarterfinals,
)
from tests.unit.test_tournament_dropouts import (
    BYES,
    FIRST_R2,
    R2,
    TWELVE,
    TWENTY_SEVEN,
    apply_drop,
    data_for,
    option,
    round_entrants,
    twenty_seven_prelims,
)

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


def rank_data(data: object) -> list:
    """Return the rankings of a dropout test's ``TournamentData``."""
    return tournament_rankings(
        data.plan, data.slots, data.results, data.tiebreaks, data.dropouts
    )


def test_byes_rank_above_second_round_players() -> None:
    """A bye reaches the Semifinals, above everyone still in the Second Round."""
    data = data_for(TWENTY_SEVEN, twenty_seven_prelims(), BYES)
    rankings = rank_data(data)
    assert [row.name for row in rankings[:5]] == ["W1", "W2", "W3", "W4", "W5"]
    assert {row.reached for row in rankings[:5]} == {"Semifinals"}
    assert rankings[5].reached == R2
    assert rankings[5].status == f"won, in the {R2}"


def test_a_play_in_winner_ranks_with_the_semifinalists() -> None:
    """Play-in players aren't out, and the play-in winner reaches the Semifinals."""
    data = data_for(TWENTY_SEVEN, twenty_seven_prelims() + FIRST_R2, BYES)
    after = apply_drop(data, option(data, "w1", DROP_PLAY_IN))
    seated = {row.player_id: row for row in rank_data(after)}
    assert not seated["l5-2"].out
    assert seated["l5-2"].status == f"play-in, in the {R2}"
    # A play-in seat reaches the Second Round before the play-in is played,
    # so its players rank above everyone who only reached the Preliminaries.
    play_in = rank_data(after)
    position = {row.player_id: index for index, row in enumerate(play_in)}
    assert seated["l5-2"].reached == R2
    prelims_only = [
        row for row in play_in if row.rank and row.reached == "Preliminaries"
    ]
    assert prelims_only
    assert all(position["l5-2"] < position[row.player_id] for row in prelims_only)

    entrants = round_entrants(after.plan, after.standings(), 1).players
    rest = [p for p in entrants if p not in {"w6", "l9-2", "l9-1"}]
    results = list(after.results)
    for number in range(2, 5):
        trio = rest[3 * (number - 2) : 3 * (number - 1)]
        results += play(f"{R2}: R2 {number}", dict.fromkeys(trio, 1), trio[0])
    results += play(f"{R2}: Play-in 1", {"l5-2": 1, "l5-1": 2, "l4-2": 3}, "l4-2")
    rankings = rank_data(replace(after, results=tuple(results)))
    semifinalists = [row for row in rankings if row.reached == "Semifinals"]
    assert len(semifinalists) == 9
    winner = next(row for row in rankings if row.player_id == "l4-2")
    assert winner in semifinalists
    assert not winner.out
    assert all(row.out for row in rankings[len(semifinalists) :] if row.rank)


def test_a_winner_who_drops_out_ranks_below_the_next_round() -> None:
    """A dropped-out winner is out, below every player still in."""
    data = data_for(TWELVE, twelve_player_quarterfinals())
    after = apply_drop(data, option(data, "w1", DROP_SLIDE))
    rankings = rank_data(after)
    names = [row.player_id for row in rankings]
    assert names[:9] == ["w2", "w3", "w4", *"abcdef"]
    dropped = rankings[9]
    assert (dropped.player_id, dropped.status, dropped.out) == (
        "w1",
        "dropped out",
        True,
    )
    assert dropped.reached == QF


def test_a_tiebreak_for_the_last_wildcard_separates_the_tied_players() -> None:
    """Level on score, the tiebreak's winner goes through and ranks higher."""
    plan = plan_tournament(TournamentOptions(12))
    results = twelve_player_quarterfinals(f=400)
    slots = [PlayerSlot(p, player_id=p) for p in TWELVE]
    tied = {row.player_id: row for row in tournament_rankings(plan, slots, results)}
    # Undecided: both wait on the tiebreaker, level.
    assert tied["e"].rank == tied["f"].rank
    assert not tied["e"].out

    tiebreaks = [Tiebreak(QF, frozenset({"e", "f"}), "f")]
    rankings = {
        row.player_id: row
        for row in tournament_rankings(plan, slots, results, tiebreaks)
    }
    assert rankings["f"].reached == SF
    assert rankings["e"].out
    assert rankings["f"].rank < rankings["e"].rank
