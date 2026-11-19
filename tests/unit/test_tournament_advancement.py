"""Tests for working out who advances from each round of a tournament."""

import pytest

from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament import TournamentOptions, plan_tournament
from jparty.domain.tournament_advancement import (
    TIE_BYE,
    TIE_CHASER,
    TIE_WILDCARD,
    Tiebreak,
    advancement_conflicts,
    eligible_players,
    player_statuses,
    round_entrants,
    round_standing,
    seating_problem,
    tie_text,
    tournament_standings,
)
from jparty.domain.tournament_play import GameResult
from jparty.domain.tournament_setup import TournamentBoard

QF = "Quarterfinals"
SF = "Semifinals"


def play(key: str, scores: dict[str, int], winner: str) -> list[GameResult]:
    """Return one game's rows: each player's score, and who won."""
    return [
        GameResult(
            key,
            player_id,
            player_id,
            score,
            None,
            "g",
            "win" if player_id == winner else "loss",
        )
        for player_id, score in scores.items()
    ]


def twelve_player_quarterfinals(**loser_scores: int) -> list[GameResult]:
    """Return results for a 12-player field's four Quarterfinals.

    Winners are ``w1``..``w4``. The eight non-winners ``a``..``h`` score
    800, 700, ..., 100 unless ``loser_scores`` says otherwise.
    """
    losers = dict(zip("abcdefgh", range(800, 0, -100), strict=True))
    losers.update(loser_scores)
    names = list(losers)
    results = []
    for game in range(4):
        pair = names[2 * game : 2 * game + 2]
        results += play(
            f"{QF}: QF {game + 1}",
            {f"w{game + 1}": 5000, **{p: losers[p] for p in pair}},
            f"w{game + 1}",
        )
    return results


def test_winners_only_round_advances_its_winners() -> None:
    """Semifinal winners go to the Final; the round waits for every game."""
    plan = plan_tournament(TournamentOptions(9))
    results = play(f"{SF}: SF 1", {"a": 1, "b": 2, "c": 3}, "c") + play(
        f"{SF}: SF 2", {"d": 1, "e": 2, "f": 3}, "d"
    )
    standing = round_standing(plan, 0, results)
    assert standing.games_left == (f"{SF}: SF 3",)
    assert not standing.decided
    assert standing.winners == ("c", "d")
    entrants = round_entrants(plan, tournament_standings(plan, results), 1)
    assert entrants.players == ()
    assert entrants.waiting == "The Semifinals aren't finished: 1 game left (SF 3)."

    results += play(f"{SF}: SF 3", {"g": 9, "h": 2, "i": 3}, "g")
    standing = round_standing(plan, 0, results)
    assert standing.decided
    assert standing.advancers == ("c", "d", "g")
    assert set(standing.eliminated) == set("abefhi")
    assert round_entrants(plan, tournament_standings(plan, results), 1).players == (
        "c",
        "d",
        "g",
    )


def test_wildcards_are_the_top_scoring_non_winners() -> None:
    """12 players: four winners plus five wildcards fill the Semifinals."""
    plan = plan_tournament(TournamentOptions(12))
    standing = round_standing(plan, 0, twelve_player_quarterfinals())
    assert standing.decided
    assert standing.winners == ("w1", "w2", "w3", "w4")
    assert standing.wildcards == ("a", "b", "c", "d", "e")
    assert standing.advancers == ("w1", "w2", "w3", "w4", "a", "b", "c", "d", "e")
    assert set(standing.eliminated) == {"f", "g", "h"}


def test_first_round_is_open_to_everyone() -> None:
    """Nobody has advanced into the first round; it isn't narrowed."""
    plan = plan_tournament(TournamentOptions(12))
    assert round_entrants(plan, tournament_standings(plan, []), 0).players is None


def test_tie_for_the_last_wildcard_needs_a_tiebreaker() -> None:
    """Two players level on the cutoff wait for a tiebreaker, then it decides."""
    plan = plan_tournament(TournamentOptions(12))
    results = twelve_player_quarterfinals(f=400)  # e and f both on 400
    standing = round_standing(plan, 0, results)
    assert not standing.decided
    (tie,) = standing.ties
    assert (tie.reason, tie.players, tie.score, tie.spots) == (
        TIE_WILDCARD,
        ("e", "f"),
        400,
        1,
    )
    assert tie_text(tie, {"e": "Eve", "f": "Fay"}) == (
        "Eve, Fay are tied at $400 in the Quarterfinals for the last wildcard "
        "spot. Play a tiebreaker to settle it."
    )
    assert (
        "tiebreaker"
        in round_entrants(plan, tournament_standings(plan, results), 1).waiting
    )

    decided = round_standing(
        plan, 0, results, [Tiebreak(QF, frozenset({"e", "f"}), "f")]
    )
    assert decided.decided
    assert decided.wildcards == ("a", "b", "c", "d", "f")
    assert "e" in decided.eliminated


def test_tiebreaker_for_other_players_or_rounds_doesnt_count() -> None:
    """Only a tiebreaker between exactly the tied players, in this round, counts."""
    plan = plan_tournament(TournamentOptions(12))
    results = twelve_player_quarterfinals(f=400)
    for tiebreak in (
        Tiebreak(QF, frozenset({"e", "f", "g"}), "f"),
        Tiebreak(SF, frozenset({"e", "f"}), "f"),
        Tiebreak(QF, frozenset({"e", "f"}), "z"),
    ):
        assert round_standing(plan, 0, results, [tiebreak]).ties


def test_three_way_tie_for_two_spots_takes_two_tiebreakers() -> None:
    """Each tiebreaker settles one spot; the rest stay tied until the next."""
    plan = plan_tournament(TournamentOptions(12))
    results = twelve_player_quarterfinals(e=500, f=500)  # d, e, f on 500
    (tie,) = round_standing(plan, 0, results).ties
    assert (tie.players, tie.spots) == (("d", "e", "f"), 2)
    assert "the last 2 wildcard spots" in tie_text(tie)

    first = Tiebreak(QF, frozenset("def"), "e")
    (tie,) = round_standing(plan, 0, results, [first]).ties
    assert (tie.players, tie.spots) == (("d", "f"), 1)

    second = Tiebreak(QF, frozenset("df"), "d")
    standing = round_standing(plan, 0, results, [first, second])
    assert standing.wildcards == ("a", "b", "c", "e", "d")
    assert "f" in standing.eliminated


def test_ties_away_from_a_cutoff_need_no_tiebreaker() -> None:
    """Two wildcards on the same score, both safely in, are fine."""
    plan = plan_tournament(TournamentOptions(12))
    standing = round_standing(plan, 0, twelve_player_quarterfinals(b=800))
    assert standing.decided
    assert set(standing.wildcards) == set("abcde")


def eleven_player_regulars() -> list[GameResult]:
    """Return 11 players' three regular Quarterfinals.

    Six non-winners ``a``..``f`` score 600..100, so with five wildcards the
    chaser is ``f``, the first one out.
    """
    losers = dict(zip("abcdef", range(600, 0, -100), strict=True))
    names = list(losers)
    results = []
    for game in range(3):
        pair = names[2 * game : 2 * game + 2]
        results += play(
            f"{QF}: QF {game + 1}",
            {f"w{game + 1}": 5000, **{p: losers[p] for p in pair}},
            f"w{game + 1}",
        )
    return results


def test_chaser_is_the_first_player_out_of_the_wildcards() -> None:
    """The chase game's third seat is decided once the regular games are in."""
    plan = plan_tournament(TournamentOptions(11))
    assert round_standing(plan, 0, eleven_player_regulars()[:-3]).chasers == {}
    standing = round_standing(plan, 0, eleven_player_regulars())
    assert standing.chasers == {f"{QF}: Chase 1": "f"}
    assert standing.games_left == (f"{QF}: Chase 1",)


def test_new_player_winning_the_chase_game_advances() -> None:
    """A new player who wins advances; the chaser stays out."""
    plan = plan_tournament(TournamentOptions(11))
    results = eleven_player_regulars() + play(
        f"{QF}: Chase 1", {"n1": 3000, "n2": 50, "f": 2000}, "n1"
    )
    standing = round_standing(plan, 0, results)
    assert standing.winners == ("w1", "w2", "w3", "n1")
    assert standing.wildcards == ("a", "b", "c", "d", "e")
    assert set(standing.eliminated) == {"f", "n2"}


def test_chaser_who_wins_opens_a_wildcard_ranked_on_original_scores() -> None:
    """A winning chaser adds a spot, but their chase score doesn't count."""
    plan = plan_tournament(TournamentOptions(11))
    results = eleven_player_regulars() + play(
        # n1 beats f's original 100, so n1 takes the extra spot, not f.
        f"{QF}: Chase 1",
        {"n1": 150, "n2": 50, "f": 9000},
        "f",
    )
    standing = round_standing(plan, 0, results)
    assert standing.winners == ("w1", "w2", "w3")
    assert standing.wildcards == ("a", "b", "c", "d", "e", "n1")
    assert standing.scores["f"] == 100
    assert set(standing.eliminated) == {"f", "n2"}


def test_tie_for_the_chaser_seat_needs_a_tiebreaker() -> None:
    """Two players level on the first spot out can't both chase."""
    plan = plan_tournament(TournamentOptions(11))
    results = [
        row if row.player_id != "f" else GameResult(**{**vars(row), "score": 200})
        for row in eleven_player_regulars()
    ]
    standing = round_standing(plan, 0, results)
    assert standing.chasers == {}
    (tie,) = standing.ties
    assert (tie.reason, set(tie.players)) == (TIE_CHASER, {"e", "f"})

    settled = round_standing(plan, 0, results, [Tiebreak(QF, frozenset("ef"), "f")])
    assert settled.chasers == {f"{QF}: Chase 1": "e"}


def thirteen_player_regulars() -> list[GameResult]:
    """Return 13 players' three regular Quarterfinals.

    Six non-winners ``a``..``f`` score 600..100. With four wildcards, ``e``
    is the first player out and ``f`` the second.
    """
    losers = dict(zip("abcdef", range(600, 0, -100), strict=True))
    results = []
    for game, pair in enumerate(("ab", "cd", "ef")):
        results += play(
            f"{QF}: QF {game + 1}",
            {f"w{game + 1}": 5000, **{p: losers[p] for p in pair}},
            f"w{game + 1}",
        )
    return results


def test_two_chasers_are_set_after_the_regular_games() -> None:
    """13 players: the second player out chases first, the first player out last."""
    plan = plan_tournament(TournamentOptions(13))
    layout = plan.rounds[0].layout
    assert (layout.regular_games, layout.chase_games, layout.wildcards) == (3, 2, 4)
    standing = round_standing(plan, 0, thirteen_player_regulars())
    assert standing.chasers == {f"{QF}: Chase 1": "f", f"{QF}: Chase 2": "e"}

    # Chase 1's results don't move Chase 2's chaser, even when a new player
    # who lost outscores e.
    results = thirteen_player_regulars() + play(
        f"{QF}: Chase 1", {"n1": 3000, "n2": 450, "f": 0}, "n1"
    )
    assert round_standing(plan, 0, results).chasers[f"{QF}: Chase 2"] == "e"


def test_chase_games_can_be_played_in_either_order() -> None:
    """Both chasers are known up front, so Chase 2 doesn't wait for Chase 1."""
    plan = plan_tournament(TournamentOptions(13))
    results = thirteen_player_regulars() + play(
        f"{QF}: Chase 2", {"n3": 10, "n4": 20, "e": 1}, "n3"
    )
    standing = round_standing(plan, 0, results)
    assert standing.games_left == (f"{QF}: Chase 1",)
    assert standing.chasers == {f"{QF}: Chase 1": "f", f"{QF}: Chase 2": "e"}


@pytest.mark.parametrize(
    ("chase_2_winner", "wildcards"),
    [
        # Both chasers win: two more spots, so e and f both get in.
        ("e", ("a", "b", "c", "d", "e", "f")),
        # Only f wins: one more spot, and it goes to e, who ranks above f.
        ("n4", ("a", "b", "c", "d", "e")),
    ],
)
def test_second_player_out_needs_both_chasers_to_win(
    chase_2_winner: str, wildcards: tuple[str, ...]
) -> None:
    """F's win only helps f if e wins too; otherwise it opens a spot for e."""
    plan = plan_tournament(TournamentOptions(13))
    results = (
        thirteen_player_regulars()
        + play(f"{QF}: Chase 1", {"n1": 10, "n2": 20, "f": 9000}, "f")
        + play(f"{QF}: Chase 2", {"n3": 30, "n4": 40, "e": 1}, chase_2_winner)
    )
    standing = round_standing(plan, 0, results)
    assert standing.wildcards == wildcards
    assert standing.scores["f"] == 100


def test_tie_between_the_two_chasers_needs_a_tiebreaker() -> None:
    """Who is first out and who is second decides who chases when."""
    plan = plan_tournament(TournamentOptions(13))
    results = [
        GameResult(**{**vars(row), "score": 200}) if row.player_id == "f" else row
        for row in thirteen_player_regulars()
    ]
    standing = round_standing(plan, 0, results)
    assert standing.chasers == {}
    (tie,) = standing.ties
    assert (tie.reason, set(tie.players)) == (TIE_CHASER, {"e", "f"})
    settled = round_standing(plan, 0, results, [Tiebreak(QF, frozenset("ef"), "f")])
    assert settled.chasers == {f"{QF}: Chase 1": "e", f"{QF}: Chase 2": "f"}


def second_round_prelims(winner_scores: list[int]) -> list[GameResult]:
    """Return 18 players' six preliminary games.

    Winners ``w1``..``w6`` score ``winner_scores``. Non-winner ``l<n>-<k>``
    scores ``100 * n + k``, so wildcards are spread across games.
    """
    results = []
    for game, score in enumerate(winner_scores, start=1):
        results += play(
            f"Preliminaries: Prelim {game}",
            {
                f"w{game}": score,
                f"l{game}-1": 100 * game + 1,
                f"l{game}-2": 100 * game + 2,
            },
            f"w{game}",
        )
    return results


def test_top_winners_get_byes_and_the_rest_play_the_second_round() -> None:
    """18 players, 5 byes: the top five winners skip to the Semifinals."""
    plan = plan_tournament(TournamentOptions(18, True, 5))
    results = second_round_prelims([6000, 1000, 5000, 4000, 3000, 2000])
    standings = tournament_standings(plan, results)
    prelims = standings[0]
    assert prelims.byes == ("w1", "w3", "w4", "w5", "w6")
    second_round = round_entrants(plan, standings, 1)
    assert "w2" in second_round.players
    assert not set(prelims.byes) & set(second_round.players)
    assert len(second_round.players) == len(prelims.advancers) - 5
    # The Semifinals wait for the second round, then take the byes too.
    assert "Second Round" in round_entrants(plan, standings, 2).waiting


def test_tie_for_the_last_bye_needs_a_tiebreaker() -> None:
    """Two winners level on the bye cutoff wait for a tiebreaker."""
    plan = plan_tournament(TournamentOptions(18, True, 5))
    results = second_round_prelims([6000, 2000, 5000, 4000, 3000, 2000])
    (tie,) = round_standing(plan, 0, results).ties
    assert (tie.reason, set(tie.players)) == (TIE_BYE, {"w2", "w6"})
    assert "the last Semifinal bye" in tie_text(tie)
    settled = round_standing(
        plan, 0, results, [Tiebreak("Preliminaries", frozenset({"w2", "w6"}), "w6")]
    )
    assert "w6" in settled.byes and "w2" not in settled.byes


def test_more_byes_than_winners_go_to_the_top_wildcards() -> None:
    """12 players, 8 byes: all four winners and the top four wildcards."""
    plan = plan_tournament(TournamentOptions(12, True, 8))
    results = []
    for game in range(1, 5):
        results += play(
            f"Preliminaries: Prelim {game}",
            {f"w{game}": 5000, f"a{game}": 100 * game, f"b{game}": 10 * game},
            f"w{game}",
        )
    standings = tournament_standings(plan, results)
    prelims = standings[0]
    assert prelims.byes == ("w1", "w2", "w3", "w4", "a4", "a3", "a2", "a1")
    assert round_entrants(plan, standings, 1).players == tuple(
        p for p in prelims.advancers if p not in prelims.byes
    )


@pytest.mark.parametrize("fixed_winner", ["a", "w1"])
def test_fixing_a_result_changes_who_advances(fixed_winner: str) -> None:
    """Standings come from the saved results, so a fix changes them."""
    plan = plan_tournament(TournamentOptions(12))
    results = [
        GameResult(
            **{
                **vars(row),
                "result": "win" if row.player_id == fixed_winner else "loss",
            }
        )
        if row.game_key == f"{QF}: QF 1"
        else row
        for row in twelve_player_quarterfinals()
    ]
    standing = round_standing(plan, 0, results)
    assert fixed_winner in standing.winners


# Eligibility


def roster(*player_ids: str) -> list[PlayerSlot]:
    """Return a named slot for each id, named after it in capitals."""
    return [
        PlayerSlot(player_id.upper(), player_id=player_id) for player_id in player_ids
    ]


TWELVE = ("w1", "w2", "w3", "w4", *"abcdefgh")


def test_first_round_is_open_to_players_who_have_not_played_it() -> None:
    """Players who played a Quarterfinal can't play another one."""
    plan = plan_tournament(TournamentOptions(12))
    results = twelve_player_quarterfinals()[:3]
    eligibility = eligible_players(plan, f"{QF}: QF 2", roster(*TWELVE), results)
    assert eligibility.entrants == ("w2", "w3", "w4", *"cdefgh")
    assert eligibility.chasers == ()
    assert eligibility.waiting == ""


def test_cant_play_and_blank_names_are_never_eligible() -> None:
    """A board's Can't Play list and unnamed slots are left out."""
    plan = plan_tournament(TournamentOptions(9))
    slots = [*roster(*"abcdefgh"), PlayerSlot("  ", player_id="blank")]
    board = TournamentBoard("b", ({"game_id": "1"},), cant_play=("b",))
    eligibility = eligible_players(plan, f"{SF}: SF 1", slots, [], board)
    assert eligibility.entrants == tuple("acdefgh")


def test_later_round_offers_only_the_players_who_advanced() -> None:
    """The Semifinals take the four winners and five wildcards, once each."""
    plan = plan_tournament(TournamentOptions(12))
    results = twelve_player_quarterfinals() + play(
        f"{SF}: SF 1", {"w1": 1, "a": 2, "e": 3}, "e"
    )
    eligibility = eligible_players(plan, f"{SF}: SF 2", roster(*TWELVE), results)
    assert eligibility.entrants == ("w2", "w3", "w4", "b", "c", "d")
    assert eligibility.waiting == ""


def test_later_round_waits_for_the_round_before() -> None:
    """Until the Quarterfinals are decided, no one can sit a Semifinal."""
    plan = plan_tournament(TournamentOptions(12))
    results = twelve_player_quarterfinals()[:-3]
    eligibility = eligible_players(plan, f"{SF}: SF 1", roster(*TWELVE), results)
    assert eligibility.entrants == ()
    assert eligibility.waiting == (
        "The Quarterfinals aren't finished: 1 game left (QF 4)."
    )
    assert seating_problem(eligibility, ["w1", "w2", "w3"]) == eligibility.waiting


def test_tie_message_names_the_players() -> None:
    """A tie that blocks the next round says who is tied, by name."""
    plan = plan_tournament(TournamentOptions(12))
    results = twelve_player_quarterfinals(f=400)
    eligibility = eligible_players(plan, f"{SF}: SF 1", roster(*TWELVE), results)
    assert eligibility.waiting.startswith("E, F are tied at $400")


def test_chase_game_offers_new_players_and_the_chaser() -> None:
    """The chaser seat is for the first player out of the wildcards."""
    plan = plan_tournament(TournamentOptions(11))
    slots = roster("w1", "w2", "w3", *"abcdef", "n1", "n2", "n3")
    eligibility = eligible_players(
        plan, f"{QF}: Chase 1", slots, eleven_player_regulars()
    )
    assert eligibility.chase
    assert eligibility.entrants == ("n1", "n2", "n3")
    assert eligibility.chasers == ("f",)
    assert seating_problem(eligibility, ["n1", "n2", "f"]) is None
    assert "can't play" in seating_problem(eligibility, ["n1", "n2", "e"])
    assert "the chaser" in seating_problem(eligibility, ["n1", "n2", "n3"])


def test_chase_game_waits_for_the_regular_games() -> None:
    """Before the regular games are in, the chaser isn't known."""
    plan = plan_tournament(TournamentOptions(11))
    slots = roster("w1", "w2", "w3", *"abcdef", "n1", "n2")
    eligibility = eligible_players(
        plan, f"{QF}: Chase 1", slots, eleven_player_regulars()[:-3]
    )
    assert eligibility.chasers == ()
    assert "chaser is known once this round's regular games" in eligibility.waiting


def test_chaser_on_the_cant_play_list_is_reported() -> None:
    """A chaser who can't play the board blocks the game with a reason."""
    plan = plan_tournament(TournamentOptions(11))
    slots = roster("w1", "w2", "w3", *"abcdef", "n1", "n2")
    board = TournamentBoard("b", ({"game_id": "1"},), cant_play=("f",))
    eligibility = eligible_players(
        plan, f"{QF}: Chase 1", slots, eleven_player_regulars(), board
    )
    assert eligibility.waiting.startswith("F is the chaser, but can't play")


def test_byes_go_straight_to_the_semifinals() -> None:
    """With byes, the Semifinals take the byes and the second round's winners."""
    plan = plan_tournament(TournamentOptions(12, True, 8))
    results = []
    for game in range(1, 5):
        results += play(
            f"Preliminaries: Prelim {game}",
            {f"w{game}": 5000, f"a{game}": 100 * game, f"b{game}": 10 * game},
            f"w{game}",
        )
    second_round = round_entrants(plan, tournament_standings(plan, results), 1)
    (r2_a, r2_b, r2_c) = second_round.players
    results += play("Second Round: R2 1", {r2_a: 1, r2_b: 2, r2_c: 3}, r2_c)
    slots = roster(*(f"{p}{g}" for g in range(1, 5) for p in "wab"))
    eligibility = eligible_players(plan, f"{SF}: SF 1", slots, results)
    assert set(eligibility.entrants) == {
        "w1",
        "w2",
        "w3",
        "w4",
        "a1",
        "a2",
        "a3",
        "a4",
        r2_c,
    }


def test_unknown_game_has_no_one_eligible() -> None:
    """A key that isn't in the bracket offers nobody."""
    plan = plan_tournament(TournamentOptions(9))
    assert eligible_players(plan, "Nope", roster(*"abc"), []).player_ids == ()


def test_seating_problems() -> None:
    """Every podium needs a different, eligible player."""
    plan = plan_tournament(TournamentOptions(12))
    eligibility = eligible_players(plan, f"{QF}: QF 1", roster(*TWELVE), [])
    assert "each of the 3 podiums" in seating_problem(eligibility, ["a", None, "b"])
    assert "different player" in seating_problem(eligibility, ["a", "a", "b"])
    assert "can't play" in seating_problem(eligibility, ["a", "b", "ghost"])
    assert seating_problem(eligibility, ["a", "b", "c"]) is None


# Statuses and conflicts


def test_player_statuses_show_where_each_player_is() -> None:
    """Winners, wildcards, the knocked out, and the next chaser."""
    plan = plan_tournament(TournamentOptions(12))
    statuses = player_statuses(
        plan, tournament_standings(plan, twelve_player_quarterfinals())
    )
    assert statuses["w1"] == ("won, in the Semifinals", False)
    assert statuses["a"] == ("wildcard, in the Semifinals", False)
    assert statuses["h"] == ("out", True)

    plan = plan_tournament(TournamentOptions(11))
    statuses = player_statuses(
        plan, tournament_standings(plan, eleven_player_regulars())
    )
    assert statuses["f"] == ("chaser in Chase 1", False)
    assert statuses["a"] == ("played the Quarterfinals", True)


def test_champion_status() -> None:
    """The Final's winner is the champion."""
    plan = plan_tournament(TournamentOptions(3))
    results = play("Final: Final", {"a": 1, "b": 2, "c": 3}, "c")
    statuses = player_statuses(plan, tournament_standings(plan, results))
    assert statuses["c"] == ("champion", False)
    assert statuses["a"] == ("out", True)


def test_fixed_result_that_changes_a_played_game_is_reported() -> None:
    """A Semifinal played by someone who no longer advanced is flagged."""
    plan = plan_tournament(TournamentOptions(12))
    results = twelve_player_quarterfinals() + play(
        f"{SF}: SF 1", {"w1": 1, "a": 2, "e": 3}, "e"
    )
    standings = tournament_standings(plan, results)
    assert advancement_conflicts(plan, standings, results) == []

    # Fix e's Quarterfinal score from 400 to 50, so f takes the last wildcard.
    fixed = [
        GameResult(**{**vars(row), "score": 50})
        if row.player_id == "e" and row.game_key.startswith(QF)
        else row
        for row in results
    ]
    standings = tournament_standings(plan, fixed)
    assert advancement_conflicts(plan, standings, fixed, {"e": "Eve"}) == [
        "SF 1: Eve played, but they didn't advance into the Semifinals."
    ]
