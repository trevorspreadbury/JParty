"""Who advances from each round of a tournament, worked out from its results.

The bracket's shape comes from :mod:`jparty.domain.tournament`, and each
game's rows from ``results.csv`` (see
:class:`jparty.domain.tournament_play.GameResult`). This module applies the
designer's rules to them:

- Every game's winner advances.
- A qualifying round's leftover spots go to wildcards: the non-winners with
  the highest final scores.
- A chase game's third seat goes to a *chaser*, set once the round's regular
  games are done: the first non-winner who would miss out on a wildcard.
  With two chase games, the second player out chases in Chase 1 and the
  first player out in Chase 2 (see
  :func:`jparty.domain.tournament.chaser_place`). A chaser's chase-game
  score doesn't count. A chaser who wins doesn't advance directly; the win
  opens one more wildcard spot, which is ranked on original scores like the
  rest.
- When a round gives byes, its top-scoring winners skip the next round. If
  there are more byes than winners, the top wildcards get the rest.

Players tied on score at a cutoff (the last wildcard, the chaser, or the
last bye) are separated by a tiebreaker (:class:`Tiebreak`). Until one is
played the round can't be decided, and :class:`TieForSpot` says who is
tied for what.

:func:`eligible_players` uses the standings to say who may sit in a game,
so a later round offers only the players who advanced into it.

Players who drop out change these rules as described in
:mod:`jparty.domain.tournament_dropouts`: each round's
:class:`~jparty.domain.tournament_dropouts.RoundDrops` removes them and
says who takes their spot.

These are pure functions over plain data, recomputed from the saved results
every time, so fixing a result changes who advances.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace

from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament import PLAYERS_PER_GAME, BracketRound, TournamentPlan
from jparty.domain.tournament_dropouts import (
    Dropout,
    RoundDrops,
    dropped_ids,
    round_drops,
)
from jparty.domain.tournament_play import GameResult, results_by_game
from jparty.domain.tournament_setup import TournamentBoard, game_key, plan_games

TIE_WILDCARD = "wildcard"
TIE_CHASER = "chaser"
TIE_BYE = "bye"
TIE_PLAY_IN = "play-in"
TIE_REPLACEMENT = "replacement"


@dataclass(frozen=True)
class Tiebreak:
    """A tiebreaker played between players tied on score at a cutoff.

    Attributes:
        round_name: The round the tie was in, such as ``"Quarterfinals"``.
        contenders: Ids of the tied players.
        winner: Id of the player who won, and so ranks first among them.
        winner_name: The winner's Actual Name when it was played, so the
            saved file reads well. Not used to match anything.
    """

    round_name: str
    contenders: frozenset[str]
    winner: str
    winner_name: str = field(default="", compare=False)


@dataclass(frozen=True)
class TieForSpot:
    """Players tied on score where only some of them can go through.

    Attributes:
        round_name: The round.
        reason: :data:`TIE_WILDCARD`, :data:`TIE_CHASER`, :data:`TIE_BYE`,
            :data:`TIE_PLAY_IN`, or :data:`TIE_REPLACEMENT`.
        players: Ids of the tied players, in the order they first played.
        score: The score they share.
        spots: How many of them go through. A tiebreaker decides one; play
            more if more than one spot is left.
    """

    round_name: str
    reason: str
    players: tuple[str, ...]
    score: int
    spots: int


@dataclass(frozen=True)
class RoundStanding:
    """Where one round stands: who has won, advanced, and gone out.

    Attributes:
        name: The round's name.
        games_left: Keys of the round's games with no results yet.
        winners: Ids of game winners, in game order. A chaser who won their
            chase game isn't one; see :attr:`wildcards`.
        wildcards: Ids given a wildcard, best first.
        byes: Ids of advancers who skip the next round, best first.
        advancers: Everyone who moves on, byes included: winners in game
            order, then wildcards.
        eliminated: Ids of players who played the round and don't move on.
        chasers: The chaser for each chase game whose chaser is known, by
            game key. For a played game, the chaser who played it.
        planned_chasers: Who should chase in each chase game, by game key,
            worked out from the regular games alone. It differs from
            :attr:`chasers` for a played game when a fixed result changed
            who should have chased.
        chaser_clashes: Unplayed chase games whose planned chaser already
            chased in another chase game, as ``(chaser id, other game
            key)`` by game key. A fixed result can cause this; the game
            can't be seated until it's sorted out.
        original_chasers: :attr:`planned_chasers` as they were before
            anyone dropped out. A chase game played before a dropout keeps
            the chaser it had then.
        play_in_players: The next players after the advancers, who play
            the play-in games added when players with a bye drop out (see
            :mod:`jparty.domain.tournament_dropouts`), best first.
        play_in_ties: Ties for the last play-in seat. They hold up the
            play-in games, not the rest of the tournament.
        replacements: The player who takes the dropped seat in each voided
            game of a first round, by game key.
        ties: Ties that must be broken before the round can be decided.
        scores: Each player's score for ranking: their score in their first
            game this round (a chaser's chase score doesn't count).
    """

    name: str
    games_left: tuple[str, ...] = ()
    winners: tuple[str, ...] = ()
    wildcards: tuple[str, ...] = ()
    byes: tuple[str, ...] = ()
    advancers: tuple[str, ...] = ()
    eliminated: tuple[str, ...] = ()
    chasers: dict[str, str] = field(default_factory=dict)
    planned_chasers: dict[str, str] = field(default_factory=dict)
    chaser_clashes: dict[str, tuple[str, str]] = field(default_factory=dict)
    original_chasers: dict[str, str] = field(default_factory=dict)
    play_in_players: tuple[str, ...] = ()
    play_in_ties: tuple[TieForSpot, ...] = ()
    replacements: dict[str, str] = field(default_factory=dict)
    ties: tuple[TieForSpot, ...] = ()
    scores: dict[str, int] = field(default_factory=dict)

    @property
    def decided(self) -> bool:
        """Return whether every game is played and every tie is broken."""
        return not self.games_left and not self.ties


def _ranked(
    players: Sequence[str],
    scores: dict[str, int],
    cutoffs: Iterable[int],
    tiebreaks: Sequence[Tiebreak],
    round_name: str,
    reason: str,
) -> tuple[list[str], list[TieForSpot]]:
    """Rank players by score, best first, breaking ties only where needed.

    A tie matters only when it straddles a cutoff: some of the tied players
    are inside the top ``cutoff`` and some aren't. Such a tie is broken by
    tiebreakers between exactly the players still tied, each moving its
    winner to the front. Ties that don't straddle a cutoff keep the order
    the players first played.

    Args:
        players: Ids to rank, in the order they first played.
        scores: Each player's score.
        cutoffs: Numbers of players that go through, such as the wildcard
            count.
        tiebreaks: Tiebreakers played so far.
        round_name: The round, to match tiebreakers and name ties.
        reason: What the cutoffs decide, for :class:`TieForSpot`.

    Returns:
        The ranked ids, and any ties still to break.
    """
    order = sorted(players, key=lambda player_id: -scores[player_id])
    cuts = {cut for cut in cutoffs if 0 < cut < len(order)}
    ranked: list[str] = []
    ties: list[TieForSpot] = []
    start = 0
    while start < len(order):
        end = start
        while end < len(order) and scores[order[end]] == scores[order[start]]:
            end += 1
        group = order[start:end]
        position = start
        while len(group) > 1 and any(
            position < cut < position + len(group) for cut in cuts
        ):
            contenders = frozenset(group)
            winner = next(
                (
                    tiebreak.winner
                    for tiebreak in tiebreaks
                    if tiebreak.round_name == round_name
                    and tiebreak.contenders == contenders
                    and tiebreak.winner in contenders
                ),
                None,
            )
            if winner is None:
                spots = min(
                    cut - position
                    for cut in cuts
                    if position < cut < position + len(group)
                )
                ties.append(
                    TieForSpot(
                        round_name, reason, tuple(group), scores[group[0]], spots
                    )
                )
                break
            ranked.append(winner)
            group.remove(winner)
            position += 1
        ranked.extend(group)
        start = end
    return ranked, ties


def _game_rows(
    bracket_round: BracketRound, by_game: dict[str, list[GameResult]]
) -> list[tuple[str, bool, list[GameResult]]]:
    """Return ``(key, chase, rows)`` for the round's played games, in order."""
    return [
        (key, game.chase, by_game[key])
        for game in bracket_round.games
        if (key := game_key(bracket_round, game)) in by_game
    ]


def round_standing(
    plan: TournamentPlan,
    round_index: int,
    results: Sequence[GameResult],
    tiebreaks: Sequence[Tiebreak] = (),
    drops: RoundDrops | None = None,
) -> RoundStanding:
    """Work out where one round stands from its results.

    Args:
        plan: The tournament's bracket.
        round_index: The round, as an index into ``plan.rounds``.
        results: Every saved result.
        tiebreaks: Every tiebreaker played.
        drops: How dropouts change the round, or ``None`` for no dropouts.

    Returns:
        The round's standing. Advancers, wildcards, and byes are filled in
        only once the round is :attr:`RoundStanding.decided`.
    """
    drops = drops or RoundDrops()
    bracket_round = plan.rounds[round_index]
    name = bracket_round.name
    by_game = results_by_game(results)
    keys = [game_key(bracket_round, game) for game in bracket_round.games]
    games_left = tuple(key for key in keys if key not in by_game)
    played = _game_rows(bracket_round, by_game)
    first_seen: list[str] = []
    scores: dict[str, int] = {}
    for _key, _chase, rows in played:
        for row in rows:
            if row.player_id not in scores:
                first_seen.append(row.player_id)
                scores[row.player_id] = row.score
    layout = bracket_round.layout
    if layout is None:
        return _winners_only_standing(
            name, keys, games_left, played, first_seen, scores, drops, tiebreaks
        )

    winners: list[str] = []
    pool: list[str] = []
    wildcard_spots = layout.wildcards + drops.extra_wildcards
    chasers: dict[str, str] = {}
    ties: list[TieForSpot] = []
    games = list(zip(keys, bracket_round.games, strict=True))
    for key, game in games:
        if not game.chase and not game.play_in:
            for row in by_game.get(key, []):
                (winners if row.won else pool).append(row.player_id)
    # A winner who dropped out leaves their spot to one more wildcard.
    wildcard_spots += sum(1 for player_id in winners if player_id in drops.slide)
    chase_keys = [key for key, game in games if game.chase]
    regular_left = any(
        key in games_left for key, game in games if not game.chase and not game.play_in
    )
    # Both chasers are set once the regular games are done: the first
    # players out of the wildcards, with the last chase game going to the
    # first player out (see chaser_place). Players who dropped out slide
    # out of the ranking.
    planned: dict[str, str] = {}
    original: dict[str, str] = {}
    if chase_keys and not regular_left:
        ranking = [player_id for player_id in pool if player_id not in drops.slide]
        planned, chaser_ties = _plan_chasers(
            ranking, scores, wildcard_spots, chase_keys, tiebreaks, name
        )
        ties.extend(chaser_ties)
        original = planned
        if drops != RoundDrops():
            original, _ties = _plan_chasers(
                pool, scores, layout.wildcards, chase_keys, tiebreaks, name
            )
    # A chase game's chaser is whoever in it already played a regular
    # game this round; the other two are new players. Only a chaser who
    # lost their regular game can open a wildcard spot. (One who won it,
    # after a fixed result, is already a winner and is counted once.)
    regular_losers = set(pool)
    regular_players = regular_losers | set(winners)
    chased_in: dict[str, str] = {}
    for key in chase_keys:
        rows = by_game.get(key)
        if rows is None:
            continue
        chaser_rows = [row for row in rows if row.player_id in regular_players]
        if chaser_rows:
            chaser = chaser_rows[0]
            chasers[key] = chaser.player_id
            chased_in[chaser.player_id] = key
            if chaser.won and chaser.player_id in regular_losers:
                wildcard_spots += 1
        for row in rows:
            if row.player_id in regular_players:
                continue
            if row.won and row.player_id in drops.slide:
                wildcard_spots += 1
            (winners if row.won else pool).append(row.player_id)
    clashes: dict[str, tuple[str, str]] = {}
    for key in chase_keys:
        chaser = planned.get(key)
        if key in by_game or chaser is None:
            continue
        if chaser in chased_in:
            clashes[key] = (chaser, chased_in[chaser])
        else:
            chasers[key] = chaser
    play_in_winners = [
        row.player_id
        for key, game in games
        if game.play_in
        for row in by_game.get(key, [])
        if row.won
    ]
    ranking = [player_id for player_id in pool if player_id not in drops.slide]
    replacements: dict[str, str] = {}
    if drops.replacement_games:
        replacements, replacement_ties = _replacements(
            ranking, scores, drops.replacement_games, tiebreaks, name
        )
        ties.extend(replacement_ties)
    unfinished = RoundStanding(
        name,
        games_left=games_left,
        winners=tuple(winners),
        chasers=chasers,
        planned_chasers=planned,
        chaser_clashes=clashes,
        original_chasers=original,
        replacements=replacements,
        ties=tuple(ties),
        scores=scores,
    )
    if games_left:
        return unfinished
    order, wildcard_ties = _ranked(
        ranking, scores, (wildcard_spots,), tiebreaks, name, TIE_WILDCARD
    )
    ties.extend(wildcard_ties)
    winners = [player_id for player_id in winners if player_id not in drops.slide]
    wildcards = order[:wildcard_spots]
    rest = order[wildcard_spots:]
    byes: list[str] = []
    if bracket_round.byes and not ties:
        byes, bye_ties = _byes(
            winners, wildcards, scores, bracket_round.byes, tiebreaks, name
        )
        ties.extend(bye_ties)
    play_in_players: list[str] = []
    play_in_ties: list[TieForSpot] = []
    if drops.byes_out and not ties:
        # A bye who dropped out leaves. Either the player promoted to
        # their bye has their place taken by the next player, or a play-in
        # game for the next three players fills the bye's seat.
        out = set(drops.byes_out)
        winners = [player_id for player_id in winners if player_id not in out]
        wildcards = [player_id for player_id in wildcards if player_id not in out]
        byes = [
            drops.byes_out[player_id] if player_id in out else player_id
            for player_id in byes
        ]
        byes = [player_id for player_id in byes if player_id]
        promoted, promote_ties = _ranked(
            rest, scores, (drops.promotions,), tiebreaks, name, TIE_WILDCARD
        )
        ties.extend(promote_ties)
        wildcards += promoted[: drops.promotions]
        seats = PLAYERS_PER_GAME * drops.play_ins
        players, play_in_ties = _ranked(
            promoted[drops.promotions :], scores, (seats,), tiebreaks, name, TIE_PLAY_IN
        )
        if not play_in_ties:
            play_in_players = players[:seats]
    if ties:
        return replace(unfinished, ties=tuple(ties))
    winners += play_in_winners
    advancers = winners + wildcards
    return replace(
        unfinished,
        winners=tuple(winners),
        wildcards=tuple(wildcards),
        byes=tuple(byes),
        advancers=tuple(advancers),
        eliminated=tuple(p for p in first_seen if p not in advancers),
        chaser_clashes={},
        play_in_players=tuple(play_in_players),
        play_in_ties=tuple(play_in_ties),
    )


def _plan_chasers(
    ranking: Sequence[str],
    scores: dict[str, int],
    wildcard_spots: int,
    chase_keys: Sequence[str],
    tiebreaks: Sequence[Tiebreak],
    round_name: str,
) -> tuple[dict[str, str], list[TieForSpot]]:
    """Return who should chase in each chase game, by key, and any ties."""
    cutoffs = range(wildcard_spots, wildcard_spots + len(chase_keys) + 1)
    order, ties = _ranked(ranking, scores, cutoffs, tiebreaks, round_name, TIE_CHASER)
    planned: dict[str, str] = {}
    if not ties and len(order) >= wildcard_spots + len(chase_keys):
        for index, key in enumerate(chase_keys):
            planned[key] = order[wildcard_spots + len(chase_keys) - 1 - index]
    return planned, ties


def _replacements(
    ranking: Sequence[str],
    scores: dict[str, int],
    games: Sequence[str],
    tiebreaks: Sequence[Tiebreak],
    round_name: str,
) -> tuple[dict[str, str], list[TieForSpot]]:
    """Return who takes the dropped seat in each voided first-round game.

    The best non-winners of the round's other games take them, in the
    order the games were voided.
    """
    order, ties = _ranked(
        ranking, scores, (len(games),), tiebreaks, round_name, TIE_REPLACEMENT
    )
    if ties:
        return {}, ties
    return dict(zip(games, order, strict=False)), []


def _winners_only_standing(
    name: str,
    keys: Sequence[str],
    games_left: tuple[str, ...],
    played: Sequence[tuple[str, bool, list[GameResult]]],
    first_seen: Sequence[str],
    scores: dict[str, int],
    drops: RoundDrops,
    tiebreaks: Sequence[Tiebreak],
) -> RoundStanding:
    """Return the standing of a round where only game winners advance."""
    winners = [
        row.player_id for _key, _chase, rows in played for row in rows if row.won
    ]
    replacements: dict[str, str] = {}
    ties: list[TieForSpot] = []
    if drops.replacement_games:
        ranking = [player_id for player_id in first_seen if player_id not in winners]
        replacements, ties = _replacements(
            ranking, scores, drops.replacement_games, tiebreaks, name
        )
    if games_left or ties:
        return RoundStanding(
            name,
            games_left=games_left,
            winners=tuple(winners),
            replacements=replacements,
            ties=tuple(ties),
            scores=scores,
        )
    return RoundStanding(
        name,
        winners=tuple(winners),
        advancers=tuple(winners),
        eliminated=tuple(p for p in first_seen if p not in winners),
        scores=scores,
    )


def _byes(
    winners: Sequence[str],
    wildcards: Sequence[str],
    scores: dict[str, int],
    byes: int,
    tiebreaks: Sequence[Tiebreak],
    round_name: str,
) -> tuple[list[str], list[TieForSpot]]:
    """Return who gets a bye: top winners, then top wildcards if needed."""
    ranked_winners, ties = _ranked(
        winners, scores, (byes,), tiebreaks, round_name, TIE_BYE
    )
    if byes <= len(ranked_winners):
        return ranked_winners[:byes], ties
    # Every winner gets a bye, and the top wildcards get the rest. That's a
    # second cutoff among the wildcards, which can be tied too.
    extra = byes - len(ranked_winners)
    ranked_wildcards, wildcard_ties = _ranked(
        list(wildcards), scores, (extra,), tiebreaks, round_name, TIE_BYE
    )
    return ranked_winners + ranked_wildcards[:extra], ties + wildcard_ties


def tournament_standings(
    plan: TournamentPlan,
    results: Sequence[GameResult],
    tiebreaks: Sequence[Tiebreak] = (),
    dropouts: Sequence[Dropout] = (),
) -> list[RoundStanding]:
    """Return every round's standing, in playing order.

    Args:
        plan: The tournament's bracket, with any play-in games (see
            :func:`jparty.domain.tournament_dropouts.effective_plan`).
        results: Every saved result.
        tiebreaks: Every tiebreaker played.
        dropouts: Every player who dropped out.

    Returns:
        One standing per round of ``plan``.
    """
    drops = round_drops(plan, dropouts)
    return [
        round_standing(plan, index, results, tiebreaks, drops[index])
        for index in range(len(plan.rounds))
    ]


@dataclass(frozen=True)
class RoundEntrants:
    """Who may play in a round, or why no one can yet.

    Attributes:
        players: Ids of the round's entrants, or ``None`` when the round is
            open to everyone (the first round).
        waiting: Why the round can't be played yet, or ``""``.
    """

    players: tuple[str, ...] | None
    waiting: str = ""


def round_entrants(
    plan: TournamentPlan,
    standings: Sequence[RoundStanding],
    round_index: int,
    names: dict[str, str] | None = None,
    dropped: Iterable[str] = (),
) -> RoundEntrants:
    """Return the players who advanced into ``round_index``.

    A round after one with byes takes that round's advancers minus its byes.
    The round after that also takes the byes. Players who dropped out are
    left out.

    Args:
        plan: The tournament's bracket.
        standings: Every round's standing, from :func:`tournament_standings`.
        round_index: The round.
        names: Display names by player id, for messages about ties.
        dropped: Ids of players who dropped out.

    Returns:
        The entrants, or why they aren't known yet.
    """
    if round_index <= 0:
        return RoundEntrants(None)
    feeder = standings[round_index - 1]
    waiting = _waiting_text(feeder, names)
    if waiting:
        return RoundEntrants((), waiting)
    players = [p for p in feeder.advancers if p not in feeder.byes]
    skipped_from = round_index - 2
    if skipped_from >= 0 and plan.rounds[skipped_from].byes:
        bye_round = standings[skipped_from]
        waiting = _waiting_text(bye_round, names)
        if waiting:
            return RoundEntrants((), waiting)
        players = list(bye_round.byes) + players
    gone = set(dropped)
    return RoundEntrants(tuple(p for p in players if p not in gone))


def _waiting_text(standing: RoundStanding, names: dict[str, str] | None) -> str:
    """Return why a round's advancers aren't known yet, or ``""``."""
    if standing.games_left:
        count = len(standing.games_left)
        games = ", ".join(_game_name(key) for key in standing.games_left)
        return (
            f"The {standing.name} aren't finished: {count} game"
            f"{'' if count == 1 else 's'} left ({games})."
        )
    if standing.ties:
        return tie_text(standing.ties[0], names)
    return ""


def tie_spot_text(tie: TieForSpot) -> str:
    """Return what a tie is for, such as ``"the last wildcard spot"``."""
    if tie.reason == TIE_WILDCARD:
        if tie.spots > 1:
            return f"the last {tie.spots} wildcard spots"
        return "the last wildcard spot"
    if tie.reason == TIE_CHASER:
        return "a chaser seat"
    if tie.reason == TIE_PLAY_IN:
        return "the last play-in seat"
    if tie.reason == TIE_REPLACEMENT:
        return "a dropped-out player's seat"
    return "the last Semifinal bye"


def tie_text(tie: TieForSpot, names: dict[str, str] | None = None) -> str:
    """Return a message for the host about a tie that needs a tiebreaker.

    Args:
        tie: The tie.
        names: Display names by player id; ids are shown when missing.

    Returns:
        Who is tied, on what score, for what.
    """
    names = names or {}
    who = ", ".join(names.get(player_id, player_id) for player_id in tie.players)
    return (
        f"{who} are tied at ${tie.score:,} in the {tie.round_name} for "
        f"{tie_spot_text(tie)}. Play a tiebreaker to settle it."
    )


def open_ties(standings: Sequence[RoundStanding]) -> list[TieForSpot]:
    """Return every tie that needs a tiebreaker, earliest round first."""
    return [
        tie
        for standing in standings
        for tie in (*standing.ties, *standing.play_in_ties)
    ]


@dataclass(frozen=True)
class TiebreakerSession:
    """A tiebreaker to play between tied players, outside any game.

    The tied players join on phones, in the order of :attr:`players`, and
    play tiebreaker clues until one of them wins. The win is saved as a
    :class:`Tiebreak`.

    Attributes:
        tournament: The tournament's name, which is also its folder name.
        tie: The tie being broken.
        players: ``(player_id, actual_name)`` for each tied player, in the
            order their phones are seated.
    """

    tournament: str
    tie: TieForSpot
    players: tuple[tuple[str, str], ...]

    @property
    def description(self) -> str:
        """Return what the tiebreaker is for, for the host's prompts."""
        return f"{tie_spot_text(self.tie)} in the {self.tie.round_name}"

    def tiebreak(self, winner_id: str) -> Tiebreak:
        """Return the :class:`Tiebreak` that records ``winner_id``'s win."""
        names = dict(self.players)
        return Tiebreak(
            self.tie.round_name,
            frozenset(names),
            winner_id,
            names.get(winner_id, ""),
        )


@dataclass(frozen=True)
class Eligibility:
    """Who may sit in one tournament game.

    Attributes:
        entrants: Ids of players who may take a regular seat, in roster
            order.
        chasers: Ids of players who may take a chase game's chaser seat: the
            round's chaser once known. Empty for other games.
        chase: Whether the game is a chase game.
        waiting: Why the game can't be seated yet, or ``""``: an earlier
            round that isn't finished, a tie that needs a tiebreaker, or a
            chaser who isn't known yet.
    """

    entrants: tuple[str, ...] = ()
    chasers: tuple[str, ...] = ()
    chase: bool = False
    waiting: str = ""

    @property
    def player_ids(self) -> tuple[str, ...]:
        """Return everyone who may sit in the game, entrants first."""
        return self.entrants + tuple(
            player_id for player_id in self.chasers if player_id not in self.entrants
        )


def eligible_players(
    plan: TournamentPlan,
    key: str,
    slots: Sequence[PlayerSlot],
    results: Sequence[GameResult],
    board: TournamentBoard | None = None,
    tiebreaks: Sequence[Tiebreak] = (),
    dropouts: Sequence[Dropout] = (),
) -> Eligibility:
    """Return who may sit in the game ``key``.

    - A first-round game is open to players who haven't played that round.
    - A later round is open to the players who advanced into it (see
      :func:`round_entrants`) and haven't played it yet. Until the rounds
      feeding it are decided, no one is.
    - A chase game's two new seats follow the same rule, and its chaser seat
      is for the round's chaser (see :class:`RoundStanding`), once the games
      before it are played.
    - A play-in game is for the next players of the round before (see
      :attr:`RoundStanding.play_in_players`).
    - A voided first-round game's dropped seat goes to its replacement
      (see :attr:`RoundStanding.replacements`), offered like a chaser.
    - Players on the board's Can't Play list, players with no name, and
      players who dropped out are never eligible.

    Args:
        plan: The tournament's bracket.
        key: The game, as :func:`jparty.domain.tournament_setup.game_key`
            names it.
        slots: The roster.
        results: Every saved result.
        board: The game's board, for its Can't Play list.
        tiebreaks: Every tiebreaker played.
        dropouts: Every player who dropped out.

    Returns:
        The eligible players. Empty if ``key`` isn't a game in ``plan``.
    """
    games = plan_games(plan)
    round_indices = {
        id(bracket_round): index for index, bracket_round in enumerate(plan.rounds)
    }
    found = next(
        (
            (round_indices[id(bracket_round)], game)
            for game_id, bracket_round, game in games
            if game_id == key
        ),
        None,
    )
    if found is None:
        return Eligibility()
    round_index, game = found
    gone = dropped_ids(dropouts)
    excluded = set(board.cant_play) if board is not None else set()
    names = {slot.player_id: slot.actual_name.strip() for slot in slots}
    named = [
        slot.player_id
        for slot in slots
        if slot.actual_name.strip()
        and slot.player_id not in excluded
        and slot.player_id not in gone
    ]
    standings = tournament_standings(plan, results, tiebreaks, dropouts)
    if game.play_in:
        return _play_in_eligibility(
            standings[round_index - 1], named, names, standings[round_index]
        )
    entrants = round_entrants(plan, standings, round_index, names, gone)
    if entrants.waiting:
        return Eligibility(chase=game.chase, waiting=entrants.waiting)
    standing = standings[round_index]
    played_round = set(standing.scores)
    allowed = None if entrants.players is None else set(entrants.players)
    open_seats = tuple(
        player_id
        for player_id in named
        if player_id not in played_round and (allowed is None or player_id in allowed)
    )
    replacement = standing.replacements.get(key)
    if replacement is not None and replacement in named:
        return Eligibility(open_seats, (replacement,), chase=game.chase)
    if not game.chase:
        return Eligibility(open_seats)
    if key in standing.chaser_clashes:
        chaser, other = standing.chaser_clashes[key]
        return Eligibility(
            open_seats,
            chase=True,
            waiting=f"{names.get(chaser) or chaser} should chase in this game, but "
            f"already chased in {_game_name(other)}. Fix the results first.",
        )
    chaser = standing.chasers.get(key)
    if chaser is None:
        waiting = (
            tie_text(standing.ties[0], names)
            if standing.ties
            else "The chaser is known once this round's regular games are played."
        )
        return Eligibility(open_seats, chase=True, waiting=waiting)
    if chaser not in named:
        return Eligibility(
            open_seats,
            chase=True,
            waiting=f"{names.get(chaser) or chaser} is the chaser, but can't play "
            "this board. Change its Can't Play list.",
        )
    return Eligibility(open_seats, (chaser,), chase=True)


def _play_in_eligibility(
    feeder: RoundStanding,
    named: Sequence[str],
    names: dict[str, str],
    standing: RoundStanding,
) -> Eligibility:
    """Return who may sit in a play-in game: the feeder round's next players.

    Players who already played a play-in game this round aren't offered
    another.
    """
    waiting = _waiting_text(feeder, names)
    if not waiting and feeder.play_in_ties:
        waiting = tie_text(feeder.play_in_ties[0], names)
    if waiting:
        return Eligibility(waiting=waiting)
    seats = set(feeder.play_in_players) - set(standing.scores)
    return Eligibility(tuple(player_id for player_id in named if player_id in seats))


def seating_problem(
    eligibility: Eligibility, chosen: Sequence[str | None]
) -> str | None:
    """Return why ``chosen`` can't play a game, or ``None`` if they can.

    Args:
        eligibility: Who may sit in the game.
        chosen: The player id picked for each podium, or ``None`` for an
            empty podium.

    Returns:
        A message for the host, or ``None``.
    """
    if eligibility.waiting:
        return eligibility.waiting
    picked = [player_id for player_id in chosen if player_id]
    if len(picked) < PLAYERS_PER_GAME:
        return f"Choose a player for each of the {PLAYERS_PER_GAME} podiums."
    if len(set(picked)) != len(picked):
        return "Choose a different player for each podium."
    if any(player_id not in eligibility.player_ids for player_id in picked):
        return "One of the chosen players can't play this game."
    if eligibility.chase:
        chasers = [
            player_id for player_id in picked if player_id in eligibility.chasers
        ]
        if len(chasers) != 1:
            return (
                "A chase game has two new players and the round's chaser, "
                "marked (chaser)."
            )
    return None


def player_statuses(
    plan: TournamentPlan,
    standings: Sequence[RoundStanding],
    dropouts: Sequence[Dropout] = (),
) -> dict[str, tuple[str, bool]]:
    """Return a short status for every player who has played.

    Later rounds replace earlier ones, so each player shows where they are
    now: for example ``"wildcard, in the Semifinals"`` or ``"out"``.

    Args:
        plan: The tournament's bracket.
        standings: Every round's standing.
        dropouts: Every player who dropped out; they show as dropped out.

    Returns:
        ``(text, waiting)`` by player id. ``waiting`` is whether the player
        has nothing to play for now: they're out, or they've played a round
        that isn't decided yet. The panel greys those players out.
    """
    statuses: dict[str, tuple[str, bool]] = {}
    for index, standing in enumerate(standings):
        later = plan.rounds[index + 1].name if index + 1 < len(plan.rounds) else ""
        after = plan.rounds[index + 2].name if index + 2 < len(plan.rounds) else ""
        for player_id in standing.scores:
            statuses[player_id] = (f"played the {standing.name}", True)
        for key, chaser in standing.chasers.items():
            if key in standing.games_left:
                statuses[chaser] = (f"chaser in {_game_name(key)}", False)
        if not standing.decided:
            continue
        for player_id in standing.eliminated:
            statuses[player_id] = ("out", True)
        if not later:
            for player_id in standing.winners:
                statuses[player_id] = ("champion", False)
            continue
        for player_id in standing.winners:
            statuses[player_id] = (f"won, in the {later}", False)
        for player_id in standing.wildcards:
            statuses[player_id] = (f"wildcard, in the {later}", False)
        for player_id in standing.byes:
            statuses[player_id] = (f"bye to the {after}", False)
        for player_id in standing.play_in_players:
            statuses[player_id] = (f"play-in, in the {later}", False)
    for dropout in dropouts:
        statuses[dropout.player_id] = ("dropped out", True)
    return statuses


def _game_name(key: str) -> str:
    """Return a game key's game name, such as ``"Chase 1"``."""
    return key.split(": ", 1)[-1]


def advancement_conflicts(
    plan: TournamentPlan,
    standings: Sequence[RoundStanding],
    results: Sequence[GameResult],
    names: dict[str, str] | None = None,
    dropouts: Sequence[Dropout] = (),
) -> list[str]:
    """Return played games that no longer match who advanced.

    Fixing a result can change who advanced, or who should have chased,
    after a later game was already played. That game then needs fixing, or
    deleting and replaying.

    - A player in a later round who didn't advance into it. While the round
      before is still undecided (a game left, or a tie), only players who
      didn't play it at all are flagged, since everyone else might still
      advance.
    - A played chase game whose chaser isn't the one the regular games
      give, either now or before anyone dropped out.

    Args:
        plan: The tournament's bracket.
        standings: Every round's standing.
        results: Every saved result.
        names: Display names by player id.
        dropouts: Every player who dropped out.

    Returns:
        One message per problem.
    """
    names = names or {}
    by_game = results_by_game(results)

    def name(player_id: str, row: GameResult | None = None) -> str:
        """Return a player's display name."""
        return names.get(player_id) or (row.player if row else "") or player_id

    problems = []
    for index, bracket_round in enumerate(plan.rounds):
        standing = standings[index]
        entrants = round_entrants(plan, standings, index, names)
        # Entrants here include players who dropped out later, since their
        # games stay as played. Play-in players come from the round before
        # without advancing out of it.
        extra = set(standings[index - 1].play_in_players) if index > 0 else set()
        if entrants.waiting:
            feeders = [index - 1]
            skipped_from = index - 2
            if skipped_from >= 0 and plan.rounds[skipped_from].byes:
                feeders.append(skipped_from)
            allowed = {p for feeder in feeders for p in standings[feeder].scores}
        else:
            allowed = None if entrants.players is None else set(entrants.players)
        if allowed is not None:
            allowed |= extra
        for game in bracket_round.games:
            key = game_key(bracket_round, game)
            rows = by_game.get(key, [])
            if not rows:
                continue
            chaser = standing.chasers.get(key) if game.chase else None
            if allowed is not None:
                for row in rows:
                    if row.player_id != chaser and row.player_id not in allowed:
                        problems.append(
                            f"{_game_name(key)}: {name(row.player_id, row)} played, "
                            f"but they didn't advance into the {bracket_round.name}."
                        )
            planned = standing.planned_chasers.get(key) if game.chase else None
            if (
                planned is not None
                and chaser != planned
                and chaser != standing.original_chasers.get(key)
            ):
                played = (
                    f"{name(chaser)} chased"
                    if chaser
                    else "No one from the regular games chased"
                )
                problems.append(
                    f"{_game_name(key)}: {played}, but the chaser should be "
                    f"{name(planned)}."
                )
    return problems
