"""Tournament bracket planning.

A tournament follows the usual Jeopardy shape: a three-player Final, fed by
three Semifinal games whose winners advance. Larger fields add qualifying
rounds in front of the Semifinals:

- Every qualifying game has three players and its winner advances.
- Leftover spots in the next round go to wildcards: the highest-scoring
  players who did not win their game.
- A field of ``3n + 2`` players plays ``n`` regular games and then one
  *chase game*. Its two new players advance by winning it. The third seat goes
  to the *chaser*, the first player who would miss out on a wildcard. A chaser
  who wins does not advance directly; the win opens one more wildcard spot.
  The chaser's chase-game score does not count, so other players can still
  overtake their original score for that spot.
- A field of ``3n + 1`` players plays two chase games, one after the other.
- An optional second round sits between the preliminaries and the
  Semifinals. The top-scoring preliminary winners get a bye straight to the
  Semifinals and everyone else who advanced plays the second round.

This module only plans the bracket's shape. It does not track results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PLAYERS_PER_GAME = 3
SEMIFINAL_GAME_COUNT = 3
SEMIFINAL_FIELD_SIZE = SEMIFINAL_GAME_COUNT * PLAYERS_PER_GAME
FINAL_FIELD_SIZE = PLAYERS_PER_GAME
MIN_TOURNAMENT_PLAYERS = PLAYERS_PER_GAME
MAX_TOURNAMENT_PLAYERS = 99
# New players in a chase game; the third seat is the chaser.
CHASE_GAME_NEW_PLAYERS = 2
# Chase games needed for each remainder of the field size modulo three.
CHASE_GAMES_BY_REMAINDER = {0: 0, 1: 2, 2: 1}

SEAT_NEW_PLAYER = "New player"
SEAT_CHASER = "Chaser"

ROUND_PRELIMINARIES = "Preliminaries"
ROUND_QUARTERFINALS = "Quarterfinals"
ROUND_SECOND_ROUND = "Second Round"
ROUND_SEMIFINALS = "Semifinals"
ROUND_FINAL = "Final"

ROUND_SHORT_NAMES = {
    ROUND_PRELIMINARIES: "Prelim",
    ROUND_QUARTERFINALS: "QF",
    ROUND_SECOND_ROUND: "R2",
    ROUND_SEMIFINALS: "SF",
    ROUND_FINAL: "Final",
}


@dataclass(frozen=True)
class TournamentOptions:
    """Host choices that decide a tournament bracket's shape.

    Attributes:
        player_count: Number of players in the tournament.
        use_second_round: Whether to add a round between the preliminaries and
            the Semifinals.
        semifinal_byes: Top preliminary winners who skip the second round.
            Ignored without a second round.
        second_round_players: Players in the second round, not counting byes.
            ``None`` uses :func:`default_second_round_players`. Ignored
            without a second round.
    """

    player_count: int
    use_second_round: bool = False
    semifinal_byes: int = 0
    second_round_players: int | None = None


@dataclass(frozen=True)
class QualifyingLayout:
    """How one qualifying round fills the next round's spots.

    Attributes:
        players: Players in the round.
        spots: Spots in the next round this round fills.
        regular_games: Games with three players who have not played yet in
            this round.
        chase_games: Games with two new players and one chaser.
        wildcards: Spots for non-winners if every chase game is won by a new
            player. Each chaser who wins adds one more.
        problems: Reasons the layout cannot be played. Empty when valid.
    """

    players: int
    spots: int
    regular_games: int
    chase_games: int
    wildcards: int
    problems: tuple[str, ...] = ()

    @property
    def game_count(self) -> int:
        """Return the number of games in the round."""
        return self.regular_games + self.chase_games

    @property
    def valid(self) -> bool:
        """Return whether the round can be played."""
        return not self.problems


@dataclass(frozen=True)
class BracketGame:
    """One game in a planned bracket.

    Attributes:
        name: Display name, such as ``"QF 3"`` or ``"Chase 1"``.
        seats: Where each of the three players comes from.
        chase: Whether this is a chase game.
    """

    name: str
    seats: tuple[str, ...]
    chase: bool = False


@dataclass(frozen=True)
class BracketRound:
    """One round of a planned bracket.

    Attributes:
        name: Round name, such as ``"Quarterfinals"``.
        games: Games in the order they are played.
        layout: Qualifying layout, or ``None`` for rounds where only winners
            advance and no wildcards or chase games are used.
        byes: Winners of this round who skip the next round.
        advance_text: Short description of who moves on from this round.
    """

    name: str
    games: tuple[BracketGame, ...]
    layout: QualifyingLayout | None = None
    byes: int = 0
    advance_text: str = ""

    @property
    def chase_games(self) -> int:
        """Return the number of chase games in the round."""
        return self.layout.chase_games if self.layout else 0


@dataclass(frozen=True)
class TournamentPlan:
    """A full bracket plus the numbers a host needs to compare designs.

    Attributes:
        options: Options the plan was built from.
        rounds: Rounds in the order they are played. Empty when invalid.
        problems: Reasons the options cannot make a bracket.
    """

    options: TournamentOptions
    rounds: tuple[BracketRound, ...] = ()
    problems: tuple[str, ...] = field(default_factory=tuple)

    @property
    def valid(self) -> bool:
        """Return whether the options make a playable bracket."""
        return not self.problems

    @property
    def total_games(self) -> int:
        """Return the number of games across every round."""
        return sum(len(bracket_round.games) for bracket_round in self.rounds)

    @property
    def multi_game_players(self) -> tuple[int, int]:
        """Return the fewest and most players who play two or more games.

        Everyone who advances out of the first round plays again. A chaser
        who misses out still played twice, so each first-round chase game can
        add one more player, depending on results.
        """
        if len(self.rounds) <= 1:
            return (0, 0)
        first_round = self.rounds[0]
        advancing = _advancing_count(first_round)
        return (advancing, advancing + first_round.chase_games)

    @property
    def games_to_win(self) -> tuple[int, int]:
        """Return the fewest and most games a champion can play.

        A bye skips one game. Each chase game a player is the chaser in adds
        one.
        """
        rounds = len(self.rounds)
        fewest = rounds - (1 if any(r.byes for r in self.rounds) else 0)
        most = rounds + sum(1 for r in self.rounds if r.chase_games)
        return (fewest, most)

    @property
    def wildcards(self) -> int:
        """Return the wildcard spots across every round, before chase results."""
        return sum(r.layout.wildcards for r in self.rounds if r.layout is not None)


def default_second_round_players(semifinal_byes: int) -> int:
    """Return a second-round field that fills the Semifinals with winners only.

    Args:
        semifinal_byes: Preliminary winners who skip the second round.

    Returns:
        Three players for each Semifinal spot the second round must fill.
    """
    return PLAYERS_PER_GAME * (SEMIFINAL_FIELD_SIZE - semifinal_byes)


def layout_qualifying_round(
    players: int, spots: int, round_name: str, too_many_games_hint: str = ""
) -> QualifyingLayout:
    """Lay out a qualifying round that fills ``spots`` in the next round.

    Args:
        players: Players in the round.
        spots: Spots in the next round this round fills.
        round_name: Round name used in problem messages.
        too_many_games_hint: Advice added when the round would produce more
            winners than ``spots``.

    Returns:
        The round layout, with ``problems`` describing why it cannot be played.
    """
    chase_games = CHASE_GAMES_BY_REMAINDER[players % PLAYERS_PER_GAME]
    regular_games = (players - CHASE_GAME_NEW_PLAYERS * chase_games) // PLAYERS_PER_GAME
    wildcards = spots - regular_games - chase_games
    problems = []
    if players <= spots:
        problems.append(
            f"{round_name}: {players} players for {spots} spots means everyone "
            "advances."
        )
    elif chase_games and regular_games == 0:
        problems.append(
            f"{round_name}: {players} players would need a chase game before "
            "any regular game."
        )
    elif wildcards < 0:
        problems.append(
            f"{round_name}: {players} players need "
            f"{regular_games + chase_games} games, which is more winners than "
            f"the {spots} spots in the next round. {too_many_games_hint}"
        )
    elif chase_games and 2 * regular_games <= wildcards:
        # The chaser is the first non-winner outside the wildcard spots, so
        # the regular games need more non-winners than there are wildcards.
        problems.append(
            f"{round_name}: every non-winner of the regular games already gets "
            "a wildcard, so no one is left to be the chaser."
        )
    return QualifyingLayout(
        players=players,
        spots=spots,
        regular_games=regular_games,
        chase_games=chase_games,
        wildcards=max(wildcards, 0),
        problems=tuple(problems),
    )


def plan_tournament(options: TournamentOptions) -> TournamentPlan:
    """Plan the bracket for a set of tournament options.

    Args:
        options: Host choices for the tournament.

    Returns:
        The planned bracket, or a plan with ``problems`` and no rounds when
        the options cannot work.
    """
    players = options.player_count
    if not MIN_TOURNAMENT_PLAYERS <= players <= MAX_TOURNAMENT_PLAYERS:
        return TournamentPlan(
            options,
            problems=(
                f"Tournaments need {MIN_TOURNAMENT_PLAYERS} to "
                f"{MAX_TOURNAMENT_PLAYERS} players.",
            ),
        )
    if players == FINAL_FIELD_SIZE:
        return TournamentPlan(options, rounds=(_final_round(None),))
    if players <= SEMIFINAL_FIELD_SIZE:
        if options.use_second_round:
            return TournamentPlan(
                options,
                problems=(
                    f"A second round needs more than {SEMIFINAL_FIELD_SIZE} players.",
                ),
            )
        return _plan_without_quarterfinals(options)
    if options.use_second_round:
        return _plan_with_second_round(options)
    return _plan_with_quarterfinals(options)


def describe_plan(plan: TournamentPlan) -> list[str]:
    """Return short summary lines for a valid plan.

    Args:
        plan: Planned bracket.

    Returns:
        Lines covering total games, repeat players, and wildcards.
    """
    if not plan.valid:
        return list(plan.problems)
    per_round = ", ".join(f"{len(r.games)} {r.name}" for r in plan.rounds)
    fewest_repeat, most_repeat = plan.multi_game_players
    fewest_games, most_games = plan.games_to_win
    lines = [
        f"Total games: {plan.total_games} ({per_round})",
        "Players with more than one game: "
        + _format_range(fewest_repeat, most_repeat)
        + f" of {plan.options.player_count}",
        "Games played by the champion: " + _format_range(fewest_games, most_games),
        f"Wildcard spots: {plan.wildcards}",
    ]
    chase_games = sum(r.chase_games for r in plan.rounds)
    if chase_games:
        lines.append(
            f"Chase games: {chase_games} (each winning chaser opens one more "
            "wildcard spot)"
        )
    byes = sum(r.byes for r in plan.rounds)
    if byes:
        lines.append(f"Semifinal byes: {byes}")
    return lines


def _format_range(fewest: int, most: int) -> str:
    """Return ``"n"`` or ``"n-m"`` for a count that may depend on results."""
    return str(fewest) if fewest == most else f"{fewest}-{most}"


def _advancing_count(bracket_round: BracketRound) -> int:
    """Return how many players move on from a round, byes included."""
    if bracket_round.layout is not None:
        return bracket_round.layout.spots
    if bracket_round.name == ROUND_FINAL:
        return 0
    return len(bracket_round.games)


def _plan_without_quarterfinals(options: TournamentOptions) -> TournamentPlan:
    """Plan four to nine players: Semifinals, then the Final."""
    players = options.player_count
    if players == SEMIFINAL_FIELD_SIZE:
        semifinals = _winners_only_round(ROUND_SEMIFINALS, [SEAT_NEW_PLAYER] * players)
    else:
        layout = layout_qualifying_round(players, FINAL_FIELD_SIZE, ROUND_SEMIFINALS)
        if not layout.valid:
            return TournamentPlan(options, problems=layout.problems)
        semifinals = _qualifying_round(
            ROUND_SEMIFINALS, layout, [SEAT_NEW_PLAYER] * players
        )
    return TournamentPlan(options, rounds=(semifinals, _final_round(semifinals)))


def _plan_with_quarterfinals(options: TournamentOptions) -> TournamentPlan:
    """Plan Quarterfinals that fill the Semifinals, then the Final."""
    players = options.player_count
    layout = layout_qualifying_round(
        players,
        SEMIFINAL_FIELD_SIZE,
        ROUND_QUARTERFINALS,
        "Add a second round.",
    )
    if not layout.valid:
        return TournamentPlan(options, problems=layout.problems)
    quarterfinals = _qualifying_round(
        ROUND_QUARTERFINALS, layout, [SEAT_NEW_PLAYER] * players
    )
    semifinals = _winners_only_round(ROUND_SEMIFINALS, _advancers(quarterfinals))
    return TournamentPlan(
        options, rounds=(quarterfinals, semifinals, _final_round(semifinals))
    )


def _plan_with_second_round(options: TournamentOptions) -> TournamentPlan:
    """Plan preliminaries, a second round with byes, Semifinals, and the Final."""
    players = options.player_count
    byes = options.semifinal_byes
    if not 0 <= byes < SEMIFINAL_FIELD_SIZE:
        return TournamentPlan(
            options,
            problems=(f"Byes must be between 0 and {SEMIFINAL_FIELD_SIZE - 1}.",),
        )
    second_round_players = options.second_round_players
    if second_round_players is None:
        second_round_players = default_second_round_players(byes)
    second_layout = layout_qualifying_round(
        second_round_players,
        SEMIFINAL_FIELD_SIZE - byes,
        ROUND_SECOND_ROUND,
        "Use fewer second-round players or fewer byes.",
    )
    prelim_layout = layout_qualifying_round(
        players,
        byes + second_round_players,
        ROUND_PRELIMINARIES,
        "Use more second-round players or more byes.",
    )
    problems = list(prelim_layout.problems) + list(second_layout.problems)
    if prelim_layout.valid and byes > prelim_layout.regular_games:
        problems.append(
            f"Only {prelim_layout.regular_games} Preliminaries winners are "
            f"certain, so {byes} byes is too many."
        )
    if problems:
        return TournamentPlan(options, problems=tuple(problems))
    prelims = _qualifying_round(
        ROUND_PRELIMINARIES, prelim_layout, [SEAT_NEW_PLAYER] * players, byes=byes
    )
    advancers = _advancers(prelims)
    bye_seats, second_round_seats = advancers[:byes], advancers[byes:]
    second_round = _qualifying_round(
        ROUND_SECOND_ROUND, second_layout, second_round_seats
    )
    semifinals = _winners_only_round(
        ROUND_SEMIFINALS, bye_seats + _advancers(second_round)
    )
    return TournamentPlan(
        options,
        rounds=(prelims, second_round, semifinals, _final_round(semifinals)),
    )


def _qualifying_round(
    name: str, layout: QualifyingLayout, entrants: list[str], byes: int = 0
) -> BracketRound:
    """Build a round with regular games, chase games, and wildcards.

    Entrants are dealt across games in turn so players from the same earlier
    game or seed group are spread out.
    """
    short_name = ROUND_SHORT_NAMES[name]
    capacities = [PLAYERS_PER_GAME] * layout.regular_games
    capacities += [CHASE_GAME_NEW_PLAYERS] * layout.chase_games
    seats = _deal(entrants, capacities)
    games = [
        BracketGame(f"{short_name} {index + 1}", tuple(seats[index]))
        for index in range(layout.regular_games)
    ]
    for chase_index in range(layout.chase_games):
        game_seats = seats[layout.regular_games + chase_index]
        after = "regular games" if chase_index == 0 else f"Chase {chase_index}"
        games.append(
            BracketGame(
                f"Chase {chase_index + 1}",
                (*game_seats, f"{SEAT_CHASER} (first out after {after})"),
                chase=True,
            )
        )
    advance_parts = [f"{layout.regular_games + layout.chase_games} winners"]
    if layout.wildcards:
        advance_parts.append(f"{layout.wildcards} wildcards")
    advance_text = " + ".join(advance_parts)
    if byes:
        advance_text += f"; top {byes} winners get a Semifinal bye"
    return BracketRound(
        name, tuple(games), layout=layout, byes=byes, advance_text=advance_text
    )


def _winners_only_round(name: str, entrants: list[str]) -> BracketRound:
    """Build a round of three-player games where only winners advance."""
    short_name = ROUND_SHORT_NAMES[name]
    game_count = len(entrants) // PLAYERS_PER_GAME
    seats = _deal(entrants, [PLAYERS_PER_GAME] * game_count)
    games = tuple(
        BracketGame(f"{short_name} {index + 1}", tuple(game_seats))
        for index, game_seats in enumerate(seats)
    )
    return BracketRound(name, games, advance_text=f"{game_count} winners")


def _final_round(previous: BracketRound | None) -> BracketRound:
    """Build the Final, seated from the previous round's advancers."""
    if previous is None:
        seats = (SEAT_NEW_PLAYER,) * FINAL_FIELD_SIZE
    else:
        seats = tuple(_advancers(previous))
    return BracketRound(
        ROUND_FINAL, (BracketGame(ROUND_FINAL, seats),), advance_text="Champion"
    )


def _advancers(bracket_round: BracketRound) -> list[str]:
    """Return seat labels for everyone who moves on from a round.

    Byes come first, then winners, then chase-game spots, then wildcards, so
    dealing them into the next round spreads each group across its games.
    """
    short_name = ROUND_SHORT_NAMES[bracket_round.name]
    layout = bracket_round.layout
    if layout is None:
        return [f"{game.name} winner" for game in bracket_round.games]
    labels = [f"Bye ({short_name} top winner)"] * bracket_round.byes
    if bracket_round.byes:
        winners = [f"{short_name} winner"] * (layout.regular_games - bracket_round.byes)
    else:
        winners = [
            f"{game.name} winner" for game in bracket_round.games if not game.chase
        ]
    labels += winners
    labels += [
        f"{game.name} winner or wildcard" for game in bracket_round.games if game.chase
    ]
    labels += [f"{short_name} wildcard"] * layout.wildcards
    return labels


def _deal(entrants: list[str], capacities: list[int]) -> list[list[str]]:
    """Deal entrants across games in turn, skipping games that are full."""
    seats: list[list[str]] = [[] for _ in capacities]
    index = 0
    for entrant in entrants:
        while len(seats[index % len(seats)]) >= capacities[index % len(seats)]:
            index += 1
        seats[index % len(seats)].append(entrant)
        index += 1
    return seats
