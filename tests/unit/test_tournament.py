"""Unit tests for tournament bracket planning."""

import pytest

from jparty.domain.tournament import (
    SEAT_NEW_PLAYER,
    TournamentOptions,
    describe_plan,
    layout_qualifying_round,
    plan_tournament,
)

pytestmark = pytest.mark.unit


def round_shape(plan: object) -> list[tuple[str, int]]:
    """Return each round's name and game count."""
    return [(r.name, len(r.games)) for r in plan.rounds]


def test_three_players_play_only_a_final() -> None:
    """Three players need nothing but the Final."""
    plan = plan_tournament(TournamentOptions(3))
    assert round_shape(plan) == [("Final", 1)]
    assert plan.multi_game_players == (0, 0)


def test_nine_players_play_semifinals_then_final() -> None:
    """Nine players play three Semifinals whose winners meet in the Final."""
    plan = plan_tournament(TournamentOptions(9))
    assert round_shape(plan) == [("Semifinals", 3), ("Final", 1)]
    assert plan.total_games == 4
    assert plan.multi_game_players == (3, 3)
    assert plan.rounds[1].games[0].seats == (
        "SF 1 winner",
        "SF 2 winner",
        "SF 3 winner",
    )


@pytest.mark.parametrize(
    ("players", "games", "wildcards"), [(15, 5, 4), (18, 6, 3), (27, 9, 0)]
)
def test_multiple_of_three_uses_winners_plus_wildcards(
    players: int, games: int, wildcards: int
) -> None:
    """Quarterfinal winners advance and the top non-winners fill the rest."""
    plan = plan_tournament(TournamentOptions(players))
    assert round_shape(plan) == [
        ("Quarterfinals", games),
        ("Semifinals", 3),
        ("Final", 1),
    ]
    quarterfinals = plan.rounds[0]
    assert quarterfinals.chase_games == 0
    assert quarterfinals.layout.wildcards == wildcards
    assert plan.multi_game_players == (9, 9)
    semifinal_seats = [seat for game in plan.rounds[1].games for seat in game.seats]
    assert semifinal_seats.count("QF wildcard") == wildcards


def test_three_n_plus_two_adds_one_chase_game() -> None:
    """Seventeen players play five regular games and one chase game."""
    plan = plan_tournament(TournamentOptions(17))
    quarterfinals = plan.rounds[0]
    layout = quarterfinals.layout
    assert (layout.regular_games, layout.chase_games, layout.wildcards) == (5, 1, 3)
    chase = quarterfinals.games[-1]
    assert chase.chase
    assert chase.seats[:2] == (SEAT_NEW_PLAYER, SEAT_NEW_PLAYER)
    assert chase.seats[2].startswith("Chaser")
    # The chaser plays twice even if they miss the Semifinals.
    assert plan.multi_game_players == (9, 10)
    assert plan.games_to_win == (3, 4)
    semifinal_seats = [seat for game in plan.rounds[1].games for seat in game.seats]
    assert "Chase 1 winner or wildcard" in semifinal_seats


def test_three_n_plus_one_adds_two_chase_games() -> None:
    """Sixteen players play four regular games and two chase games."""
    plan = plan_tournament(TournamentOptions(16))
    layout = plan.rounds[0].layout
    assert (layout.regular_games, layout.chase_games, layout.wildcards) == (4, 2, 3)
    assert [game.name for game in plan.rounds[0].games[-2:]] == ["Chase 1", "Chase 2"]
    # The second player out chases first; the first player out chases last.
    chase_1, chase_2 = plan.rounds[0].games[-2:]
    assert chase_1.seats[2] == "Chaser (second out after the regular games)"
    assert chase_2.seats[2] == "Chaser (first out after the regular games)"
    assert plan.multi_game_players == (9, 11)


def test_two_chase_games_need_two_non_winners_outside_the_wildcards() -> None:
    """Both chasers come from the regular games, so each needs a spare player.

    Sixteen players with a second round and seven byes play four regular
    preliminaries for seven wildcards: one spare non-winner, two chase games.
    """
    plan = plan_tournament(TournamentOptions(16, True, 7))
    assert not plan.valid
    assert "all 2 chasers" in plan.problems[0]


def test_chase_needs_someone_outside_the_wildcards() -> None:
    """Ten players leave no non-winner outside the wildcards to chase."""
    plan = plan_tournament(TournamentOptions(10))
    assert not plan.valid
    assert "chaser" in plan.problems[0]
    assert plan.rounds == ()


def test_too_many_quarterfinal_games_suggests_second_round() -> None:
    """Twenty-eight players make more winners than Semifinal spots."""
    plan = plan_tournament(TournamentOptions(28))
    assert not plan.valid
    assert "Add a second round" in plan.problems[0]


def test_second_round_with_byes() -> None:
    """Top preliminary winners skip the second round into the Semifinals."""
    plan = plan_tournament(
        TournamentOptions(30, use_second_round=True, semifinal_byes=3)
    )
    assert round_shape(plan) == [
        ("Preliminaries", 10),
        ("Second Round", 6),
        ("Semifinals", 3),
        ("Final", 1),
    ]
    prelims = plan.rounds[0]
    assert prelims.byes == 3
    assert prelims.layout.spots == 21
    assert prelims.layout.wildcards == 11
    for game in plan.rounds[2].games:
        assert game.seats[0] == "Bye (Prelim top winner)"
    assert plan.total_games == 20
    assert plan.multi_game_players == (21, 21)
    assert plan.games_to_win == (3, 4)


def test_second_round_field_size_can_be_chosen() -> None:
    """A smaller second round with wildcards needs fewer preliminary spots."""
    plan = plan_tournament(
        TournamentOptions(
            30, use_second_round=True, semifinal_byes=3, second_round_players=12
        )
    )
    assert plan.valid
    second_round = plan.rounds[1].layout
    assert (second_round.regular_games, second_round.wildcards) == (4, 2)
    assert plan.rounds[0].layout.spots == 15


def test_byes_can_go_to_chase_winners_and_wildcards() -> None:
    """Byes beyond the regular-game winners go to chase spots, then wildcards."""
    plan = plan_tournament(
        TournamentOptions(
            14, use_second_round=True, semifinal_byes=6, second_round_players=6
        )
    )
    assert plan.valid
    prelims = plan.rounds[0].layout
    assert (prelims.regular_games, prelims.chase_games, prelims.wildcards) == (
        4,
        1,
        7,
    )
    semifinal_seats = [seat for game in plan.rounds[2].games for seat in game.seats]
    assert semifinal_seats.count("Bye (Prelim top winner)") == 4
    assert semifinal_seats.count("Bye (Prelim top winner or wildcard)") == 1
    assert semifinal_seats.count("Bye (Prelim top wildcard)") == 1
    second_round_seats = [seat for game in plan.rounds[1].games for seat in game.seats]
    assert second_round_seats == ["Prelim wildcard"] * 6
    assert "winners first, then wildcards" in plan.rounds[0].advance_text


def test_second_round_needs_more_than_nine_players() -> None:
    """Small fields cannot use a second round."""
    plan = plan_tournament(TournamentOptions(9, use_second_round=True))
    assert not plan.valid


@pytest.mark.parametrize("players", [5, 6, 7, 8])
def test_small_fields_feed_the_final_directly(players: int) -> None:
    """Fewer than nine players play Semifinals with wildcards into the Final."""
    plan = plan_tournament(TournamentOptions(players))
    assert plan.valid
    assert plan.rounds[0].name == "Semifinals"
    assert plan.rounds[0].layout.spots == 3
    assert len(plan.rounds[-1].games[0].seats) == 3


def test_four_players_cannot_start_with_a_chase_game() -> None:
    """Four players would need a chase game with no regular game first."""
    assert not plan_tournament(TournamentOptions(4)).valid


@pytest.mark.parametrize("players", range(3, 100))
def test_every_game_seats_three_players(players: int) -> None:
    """Every valid plan seats three per game and starts everyone once."""
    for options in (
        TournamentOptions(players),
        TournamentOptions(players, use_second_round=True),
    ):
        plan = plan_tournament(options)
        if not plan.valid:
            continue
        for bracket_round in plan.rounds:
            for game in bracket_round.games:
                assert len(game.seats) == 3
        new_seats = sum(
            seat == SEAT_NEW_PLAYER
            for game in plan.rounds[0].games
            for seat in game.seats
        )
        assert new_seats == players


def test_layout_qualifying_round_counts() -> None:
    """Layout splits players into regular and chase games."""
    layout = layout_qualifying_round(23, 9, "Quarterfinals")
    assert (layout.regular_games, layout.chase_games, layout.wildcards) == (7, 1, 1)
    assert layout.game_count == 8
    assert layout.valid


def test_describe_plan_lists_totals() -> None:
    """The summary reports games, repeat players, and chase games."""
    lines = describe_plan(plan_tournament(TournamentOptions(17)))
    assert lines[0] == "Total games: 10 (6 Quarterfinals, 3 Semifinals, 1 Final)"
    assert lines[1] == "Players with more than one game: 9-10 of 17"
    assert any(line.startswith("Chase games: 1") for line in lines)
