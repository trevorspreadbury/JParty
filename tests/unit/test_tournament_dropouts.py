"""Tests for players who drop out of a tournament, and who takes their spot."""

from dataclasses import replace

import pytest

from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament_advancement import (
    advancement_conflicts,
    eligible_players,
    player_statuses,
    round_entrants,
)
from jparty.domain.tournament_drop_choices import (
    TournamentData,
    apply_drop,
    drop_situation,
    undo_drop,
    undo_problem,
)
from jparty.domain.tournament_dropouts import (
    DROP_PLAY_IN,
    DROP_PROMOTE,
    DROP_REDUCE,
    DROP_REPLACE,
    DROP_SLIDE,
    DROP_VOID,
    Dropout,
    field_size,
)
from jparty.domain.tournament_play import GameResult
from jparty.domain.tournament_setup import BracketSettings, TournamentBoard
from jparty.domain.tournament_store import (
    TournamentSettings,
    dropouts_csv_text,
    load_tournament_data,
    parse_dropouts_csv,
    save_tournament,
    save_tournament_data,
)
from tests.unit.test_tournament_advancement import (
    QF,
    SF,
    play,
    quarterfinals,
    roster,
    twelve_player_quarterfinals,
)

PRELIMS = "Preliminaries"
R2 = "Second Round"


def board(label: str) -> TournamentBoard:
    """Return a board with ``label``, playing one round of game ``label``."""
    return TournamentBoard(label, ({"game_id": label, "source_round_index": 0},))


def data_for(
    player_ids: list[str],
    results: list[GameResult],
    bracket: BracketSettings | None = None,
    **changes: object,
) -> TournamentData:
    """Return a tournament of ``player_ids`` with ``results`` saved."""
    return TournamentData(
        bracket=bracket or BracketSettings(),
        slots=tuple(roster(*player_ids)),
        results=tuple(results),
        **changes,
    )


def option(data: TournamentData, player_id: str, choice: str) -> Dropout:
    """Return the dropout for ``player_id``'s option ``choice``, checking it's open."""
    situation = drop_situation(data, player_id)
    assert not situation.problem, situation.problem
    (found,) = [o for o in situation.options if o.dropout.choice == choice]
    assert not found.problem, found.problem
    return found.dropout


TWELVE = ["w1", "w2", "w3", "w4", *"abcdefgh"]
FOURTEEN = [*TWELVE, "n1", "n2"]
FOURTEEN_LOSERS = dict(zip("abcdefgh", range(800, 0, -100), strict=True))


# Before a player's first game


def test_reduce_replans_the_games_not_yet_played() -> None:
    """12 players, QF 4 unplayed: reducing to 11 turns QF 4 into Chase 1."""
    played = twelve_player_quarterfinals()[:9]  # QF 1-3
    data = data_for(TWELVE, played, boards={f"{QF}: QF 4": board("B4")})
    dropout = option(data, "h", DROP_REDUCE)
    assert dropout == Dropout("h", QF, DROP_REDUCE)
    after = apply_drop(data, dropout)
    assert field_size(after.slots, after.dropouts) == 11
    keys = [game.name for game in after.plan.rounds[0].games]
    assert keys == ["QF 1", "QF 2", "QF 3", "Chase 1"]
    # QF 4's board goes back to unassigned, remembering its game.
    assert f"{QF}: QF 4" not in after.boards
    assert [b.label for b in after.unassigned] == ["B4"]
    eligibility = eligible_players(
        after.plan,
        f"{QF}: Chase 1",
        after.slots,
        after.results,
        dropouts=after.dropouts,
    )
    assert "h" not in eligibility.entrants
    assert set(eligibility.entrants) == {"w4", "g"}


def test_reduce_is_refused_when_the_smaller_bracket_doesnt_work() -> None:
    """11 players can't become 10, so only a replacement is offered."""
    eleven = ["w1", "w2", "w3", *"abcdef", "n1", "n2"]
    situation = drop_situation(data_for(eleven, []), "n1")
    reduce, replace_option = situation.options
    assert reduce.problem.startswith("The bracket doesn't work with one fewer player")
    assert not replace_option.problem


def test_reduce_is_refused_when_a_played_game_would_go_away() -> None:
    """QF 4 already played: 11 players have no QF 4, so it can't shrink."""
    results = twelve_player_quarterfinals()
    played = results[:6] + results[9:]  # QF 1, 2, and 4
    situation = drop_situation(data_for(TWELVE, played), "e")
    assert "QF 4" in situation.options[0].problem


def test_replace_adds_a_new_player_in_their_place() -> None:
    """The field keeps its size, and the new player can sit the first round."""
    data = data_for(TWELVE, [])
    dropout = option(data, "h", DROP_REPLACE)
    new = PlayerSlot("Zed", player_id="z")
    after = apply_drop(data, dropout, new)
    assert after.dropouts == (replace(dropout, other_id="z"),)
    assert field_size(after.slots, after.dropouts) == 12
    eligibility = eligible_players(
        after.plan, f"{QF}: QF 1", after.slots, (), dropouts=after.dropouts
    )
    assert "z" in eligibility.entrants
    assert "h" not in eligibility.entrants


# After their first game


def test_winner_who_drops_out_opens_one_more_wildcard() -> None:
    """w1 won QF 1: everyone slides up, so f gets the sixth wildcard."""
    data = data_for(TWELVE, twelve_player_quarterfinals())
    situation = drop_situation(data, "w1")
    assert situation.summary == "W1 won QF 1 in the Quarterfinals."
    (only,) = situation.options
    assert only.dropout == Dropout("w1", QF, DROP_SLIDE)
    assert "one more wildcard" in only.detail
    after = apply_drop(data, only.dropout)
    standings = after.standings()
    assert standings[0].wildcards == ("a", "b", "c", "d", "e", "f")
    entrants = round_entrants(after.plan, standings, 1, dropped={"w1"})
    assert set(entrants.players) == {"w2", "w3", "w4", *"abcdef"}


def test_wildcard_who_drops_out_lets_the_next_player_in() -> None:
    """Player c had a wildcard: d, e, and f each move up."""
    data = data_for(TWELVE, twelve_player_quarterfinals())
    after = apply_drop(data, option(data, "c", DROP_SLIDE))
    assert after.standings()[0].wildcards == ("a", "b", "d", "e", "f")
    statuses = player_statuses(after.plan, after.standings(), after.dropouts)
    assert statuses["c"] == ("dropped out", True)


def test_dropout_before_the_chase_game_moves_the_chaser_up() -> None:
    """14 players: b drops out, so e takes a wildcard and f chases."""
    plan_players = FOURTEEN
    losers = FOURTEEN_LOSERS
    data = data_for(plan_players, quarterfinals(losers))
    assert data.standings()[0].chasers == {f"{QF}: Chase 1": "e"}
    after = apply_drop(data, option(data, "b", DROP_SLIDE))
    assert after.standings()[0].chasers == {f"{QF}: Chase 1": "f"}


def test_dropout_after_the_chase_game_keeps_the_chaser_who_played() -> None:
    """The chase game was played with e; b dropping out doesn't flag it."""
    plan_players = FOURTEEN
    losers = FOURTEEN_LOSERS
    results = quarterfinals(losers) + play(
        f"{QF}: Chase 1", {"n1": 10, "n2": 20, "e": 9000}, "n2"
    )
    data = data_for(plan_players, results)
    after = apply_drop(data, option(data, "b", DROP_SLIDE))
    standing = after.standings()[0]
    assert standing.wildcards == ("a", "c", "d", "e")
    assert (
        advancement_conflicts(
            after.plan, after.standings(), after.results, {}, after.dropouts
        )
        == []
    )


def test_eliminated_players_cant_drop_out() -> None:
    """Player h is already out of the Quarterfinals."""
    data = data_for(TWELVE, twelve_player_quarterfinals())
    assert drop_situation(data, "h").problem == "H is already out."


def test_dropped_player_cant_drop_out_again() -> None:
    """A second drop for the same player is refused."""
    data = data_for(TWELVE, twelve_player_quarterfinals())
    after = apply_drop(data, option(data, "c", DROP_SLIDE))
    assert drop_situation(after, "c").problem == "C already dropped out."


# Semifinal winners


def twelve_through_semifinal_one() -> list[GameResult]:
    """Return 12 players' Quarterfinals, then SF 1 won by w1."""
    return twelve_player_quarterfinals() + play(
        f"{SF}: SF 1", {"w1": 9000, "a": 100, "b": 200}, "w1"
    )


def test_semifinal_winner_voids_their_game_and_the_next_wildcard_sits() -> None:
    """w1 won SF 1: it's voided, f joins a and b, and the board is retired."""
    data = data_for(
        TWELVE, twelve_through_semifinal_one(), boards={f"{SF}: SF 1": board("S1")}
    )
    situation = drop_situation(data, "w1")
    assert situation.summary == "W1 won SF 1."
    (only,) = situation.options
    assert only.dropout == Dropout("w1", SF, DROP_VOID, game_key=f"{SF}: SF 1")
    after = apply_drop(data, only.dropout)
    assert all(row.game_key != f"{SF}: SF 1" for row in after.results)
    assert {row.player_id for row in after.voided} == {"w1", "a", "b"}
    assert f"{SF}: SF 1" not in after.boards
    assert [(b.label, b.left_game_key) for b in after.retired] == [
        ("S1", f"{SF}: SF 1")
    ]
    assert after.standings()[0].wildcards == ("a", "b", "c", "d", "e", "f")
    eligibility = eligible_players(
        after.plan,
        f"{SF}: SF 1",
        after.slots,
        after.results,
        dropouts=after.dropouts,
    )
    assert "w1" not in eligibility.entrants
    assert {"a", "b", "f"} <= set(eligibility.entrants)


def test_undo_restores_a_voided_game_until_it_is_replayed() -> None:
    """Taking the dropout back brings back SF 1's results and board."""
    data = data_for(
        TWELVE, twelve_through_semifinal_one(), boards={f"{SF}: SF 1": board("S1")}
    )
    dropout = option(data, "w1", DROP_VOID)
    after = apply_drop(data, dropout)
    assert undo_problem(after, dropout) == ""
    undone = undo_drop(after, dropout)
    assert sorted(undone.results, key=repr) == sorted(data.results, key=repr)
    assert undone.boards == {f"{SF}: SF 1": board("S1")}
    assert undone.retired == ()

    replayed = replace(
        after,
        results=after.results
        + tuple(play(f"{SF}: SF 1", {"a": 1, "b": 2, "f": 3}, "f")),
    )
    assert undo_problem(replayed, dropout) == (
        "SF 1 has been played again, so it can't be restored."
    )


def test_semifinal_winner_cant_drop_after_the_final() -> None:
    """Once the Final is played, a Semifinal winner's dropout is refused."""
    results = twelve_through_semifinal_one() + play(
        "Final: Final", {"w1": 1, "x": 2, "y": 3}, "y"
    )
    problem = drop_situation(data_for(TWELVE, results), "w1").problem
    assert "Final" in problem


def test_first_round_semifinal_is_refilled_from_the_other_semifinals() -> None:
    """9 players: SF 1's winner drops; the best other non-winner sits instead."""
    nine = list("abcdefghi")
    results = (
        play(f"{SF}: SF 1", {"a": 9000, "b": 1, "c": 2}, "a")
        + play(f"{SF}: SF 2", {"d": 9000, "e": 700, "f": 3}, "d")
        + play(f"{SF}: SF 3", {"g": 9000, "h": 800, "i": 4}, "g")
    )
    data = data_for(nine, results)
    after = apply_drop(data, option(data, "a", DROP_VOID))
    standing = after.standings()[0]
    assert standing.replacements == {f"{SF}: SF 1": "h"}
    eligibility = eligible_players(
        after.plan,
        f"{SF}: SF 1",
        after.slots,
        after.results,
        dropouts=after.dropouts,
    )
    assert set(eligibility.player_ids) == {"b", "c", "h"}


# Byes


def twenty_seven_prelims() -> list[GameResult]:
    """Return 27 players' nine Preliminaries; w1..w5 get the five byes.

    Non-winner ``l<n>-<k>`` scores ``100 * n + k``, so after the eight
    wildcards the next players are l5-2, l5-1, and l4-2.
    """
    winner_scores = [9000, 8000, 7000, 6000, 5000, 1000, 1100, 1200, 1300]
    results = []
    for game, score in enumerate(winner_scores, start=1):
        results += play(
            f"{PRELIMS}: Prelim {game}",
            {
                f"w{game}": score,
                f"l{game}-1": 100 * game + 1,
                f"l{game}-2": 100 * game + 2,
            },
            f"w{game}",
        )
    return results


BYES = BracketSettings(True, 5)
TWENTY_SEVEN = [
    *(f"w{g}" for g in range(1, 10)),
    *(f"l{g}-{k}" for g in range(1, 10) for k in (1, 2)),
]
FIRST_R2 = play(f"{R2}: R2 1", {"w6": 3000, "l9-2": 1, "l9-1": 2}, "w6")


def test_bye_who_drops_before_the_second_round_slides_the_prelims() -> None:
    """No Second Round game yet: w6 moves up to the bye, and l5-2 gets in."""
    data = data_for(TWENTY_SEVEN, twenty_seven_prelims(), BYES)
    after = apply_drop(data, option(data, "w1", DROP_SLIDE))
    prelims = after.standings()[0]
    assert prelims.byes == ("w2", "w3", "w4", "w5", "w9")
    assert "l5-2" in prelims.advancers


def test_bye_who_drops_after_the_second_round_started_offers_two_choices() -> None:
    """Once R2 1 is played, the host picks a play-in game or a promotion."""
    data = data_for(TWENTY_SEVEN, twenty_seven_prelims() + FIRST_R2, BYES)
    situation = drop_situation(data, "w1")
    assert [o.dropout.choice for o in situation.options] == [
        DROP_PLAY_IN,
        DROP_PROMOTE,
    ]
    assert situation.options[1].dropout.other_id == "w9"


def test_play_in_game_seats_the_next_three_and_its_winner_takes_the_bye() -> None:
    """A play-in for l5-2, l5-1, and l4-2; its winner joins the Semifinals."""
    data = data_for(TWENTY_SEVEN, twenty_seven_prelims() + FIRST_R2, BYES)
    dropout = option(data, "w1", DROP_PLAY_IN)
    assert dropout.game_key == f"{R2}: Play-in 1"
    after = apply_drop(data, dropout)
    assert [g.name for g in after.plan.rounds[1].games][-1] == "Play-in 1"
    prelims = after.standings()[0]
    assert prelims.byes == ("w2", "w3", "w4", "w5")
    assert prelims.play_in_players == ("l5-2", "l5-1", "l4-2")
    eligibility = eligible_players(
        after.plan,
        f"{R2}: Play-in 1",
        after.slots,
        after.results,
        dropouts=after.dropouts,
    )
    assert eligibility.entrants == ("l4-2", "l5-1", "l5-2")  # roster order

    # Play out the Second Round and the play-in.
    entrants = round_entrants(after.plan, after.standings(), 1).players
    rest = [p for p in entrants if p not in {"w6", "l9-2", "l9-1"}]
    results = list(after.results)
    for number in range(2, 5):
        trio = rest[3 * (number - 2) : 3 * (number - 1)]
        results += play(f"{R2}: R2 {number}", dict.fromkeys(trio, 1), trio[0])
    results += play(f"{R2}: Play-in 1", {"l5-2": 1, "l5-1": 2, "l4-2": 3}, "l4-2")
    finished = replace(after, results=tuple(results))
    semifinal = round_entrants(finished.plan, finished.standings(), 2).players
    assert len(semifinal) == 9
    assert "l4-2" in semifinal
    assert "w1" not in semifinal


def test_promoted_player_takes_the_bye_and_the_next_prelim_player_sits() -> None:
    """w9 hasn't played R2: they get the bye, and l5-2 takes their seat."""
    data = data_for(TWENTY_SEVEN, twenty_seven_prelims() + FIRST_R2, BYES)
    after = apply_drop(data, option(data, "w1", DROP_PROMOTE))
    standings = after.standings()
    assert standings[0].byes == ("w9", "w2", "w3", "w4", "w5")
    second_round = round_entrants(after.plan, standings, 1, dropped={"w1"}).players
    assert "w9" not in second_round
    assert "l5-2" in second_round
    assert len(second_round) == 12
    assert (
        advancement_conflicts(after.plan, standings, after.results, {}, after.dropouts)
        == []
    )


# Saving


def test_dropouts_csv_round_trips() -> None:
    """Every field is written and read back."""
    dropouts = [
        Dropout("w1", SF, DROP_VOID, game_key=f"{SF}: SF 1", player_name="Wes"),
        Dropout("h", QF, DROP_REPLACE, other_id="z", player_name="Hal"),
    ]
    parsed = parse_dropouts_csv(dropouts_csv_text(dropouts))
    assert parsed == dropouts
    assert [d.player_name for d in parsed] == ["Wes", "Hal"]


@pytest.mark.parametrize(
    "text",
    [
        "round,player_id\nQuarterfinals,a\n",
        "round,choice,player_id\nQuarterfinals,leave,a\n",
        "round,choice,player_id\n,slide,a\n",
    ],
)
def test_bad_dropouts_csv_is_reported(text: str) -> None:
    """A missing column, unknown choice, or blank round is an error."""
    from jparty.domain.tournament_store import TournamentFileError

    with pytest.raises(TournamentFileError):
        parse_dropouts_csv(text)


def test_voided_game_and_its_board_are_saved(tmp_path: object) -> None:
    """Voided results, the dropout, and the retired board all survive a reload."""
    settings = TournamentSettings("Fun", boards={f"{SF}: SF 1": board("S1")})
    save_tournament(tmp_path, settings, roster(*TWELVE))
    folder = tmp_path / "Fun"
    _settings, data = load_tournament_data(folder)
    data = replace(data, results=tuple(twelve_through_semifinal_one()))
    after = apply_drop(data, option(data, "w1", DROP_VOID))
    save_tournament_data(folder, settings, after)

    settings, loaded = load_tournament_data(folder)
    assert loaded.dropouts == after.dropouts
    assert sorted(loaded.voided, key=repr) == sorted(after.voided, key=repr)
    assert loaded.results == after.results
    assert [(b.label, b.left_game_key) for b in settings.retired_boards] == [
        ("S1", f"{SF}: SF 1")
    ]
    assert f"{SF}: SF 1" not in settings.boards


def test_two_play_ins_keep_their_names_and_seat_different_players() -> None:
    """Play-in 2 skips Play-in 1's players, and undoing Play-in 1 keeps its name."""
    data = data_for(TWENTY_SEVEN, twenty_seven_prelims() + FIRST_R2, BYES)
    first = option(data, "w1", DROP_PLAY_IN)
    data = apply_drop(data, first)
    second = option(data, "w2", DROP_PLAY_IN)
    assert second.game_key == f"{R2}: Play-in 2"
    data = apply_drop(data, second)
    assert data.standings()[0].play_in_players == (
        "l5-2",
        "l5-1",
        "l4-2",
        "l4-1",
        "l3-2",
        "l3-1",
    )
    data = replace(
        data,
        results=data.results
        + tuple(play(f"{R2}: Play-in 1", {"l5-2": 1, "l5-1": 2, "l4-2": 3}, "l4-2")),
    )
    eligibility = eligible_players(
        data.plan, f"{R2}: Play-in 2", data.slots, data.results, dropouts=data.dropouts
    )
    assert set(eligibility.entrants) == {"l4-1", "l3-2", "l3-1"}
    assert "has been played" in undo_problem(data, first)

    unplayed = replace(data, results=data.results[:-3])
    undone = undo_drop(unplayed, first)
    assert [g.name for g in undone.plan.rounds[1].games][-1] == "Play-in 2"
    assert option(undone, "w1", DROP_PLAY_IN).game_key == f"{R2}: Play-in 3"


def test_chase_game_winner_who_drops_out_opens_one_more_wildcard() -> None:
    """n2 won Chase 1 as a new player: their spot becomes a fifth wildcard."""
    results = quarterfinals(FOURTEEN_LOSERS) + play(
        f"{QF}: Chase 1", {"n1": 10, "n2": 20, "e": 5}, "n2"
    )
    data = data_for(FOURTEEN, results)
    after = apply_drop(data, option(data, "n2", DROP_SLIDE))
    assert after.standings()[0].wildcards == ("a", "b", "c", "d", "e")


def test_entrants_leave_out_players_who_dropped_out() -> None:
    """A voided Semifinal's winner is still a Quarterfinals advancer, not an entrant."""
    data = data_for(TWELVE, twelve_through_semifinal_one())
    after = apply_drop(data, option(data, "w1", DROP_VOID))
    standings = after.standings()
    assert "w1" in standings[0].advancers
    assert "w1" in round_entrants(after.plan, standings, 1).players
    entrants = round_entrants(after.plan, standings, 1, dropped={"w1"}).players
    assert "w1" not in entrants
    assert "f" in entrants


def test_semifinal_winner_cant_drop_once_a_final_without_them_is_saved() -> None:
    """Even a Final saved without them (after a fix) ends their chance to drop."""
    results = twelve_through_semifinal_one() + play(
        "Final: Final", {"x": 1, "y": 2, "z": 3}, "z"
    )
    problem = drop_situation(data_for(TWELVE, results), "w1").problem
    assert problem == "W1 won a Semifinal, but the Final has been played."
