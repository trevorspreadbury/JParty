"""Who advances from each round of a tournament, worked out from its results.

The bracket's shape comes from :mod:`jparty.domain.tournament.bracket`, and each
game's rows from ``results.csv`` (see
:class:`jparty.domain.tournament.play.GameResult`). This module applies the
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
- When dropouts leave no one to chase, a chase game is played by its two
  new players alone, and its winner advances.

Players tied on score at a cutoff (the last wildcard, the chaser, or the
last bye) are separated by a tiebreaker (:class:`Tiebreak`). Until one is
played the round can't be decided, and :class:`TieForSpot` says who is
tied for what.

:func:`eligible_players` uses the standings to say who may sit in a game,
so a later round offers only the players who advanced into it.

Players who drop out change these rules as described in
:mod:`jparty.domain.tournament.dropouts`: each round's
:class:`~jparty.domain.tournament.dropouts.RoundDrops` removes them and
says who takes their spot.

These are pure functions over plain data, recomputed from the saved results
every time, so fixing a result changes who advances.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace

from jparty.domain.tournament.bracket import (
    CHASE_GAME_NEW_PLAYERS,
    PLAYERS_PER_GAME,
    BracketRound,
    TournamentPlan,
)
from jparty.domain.tournament.dropouts import (
    Dropout,
    RoundDrops,
    dropped_ids,
    round_drops,
)
from jparty.domain.tournament.play import GameResult, results_by_game
from jparty.domain.tournament.roster import PlayerSlot
from jparty.domain.tournament.setup import TournamentBoard, game_key, plan_games

TIE_WILDCARD = "wildcard"
TIE_CHASER = "chaser"
TIE_BYE = "bye"
TIE_PLAY_IN = "play-in"
TIE_REPLACEMENT = "replacement"
# A knocked-out player's status in player_statuses.
STATUS_OUT = "out"


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
            who should have chased. When every played chase game's chaser
            is in :attr:`accepted_chasers`, those chasers stand, and the
            unplayed chase games are planned around them.
        chaser_clashes: Unplayed chase games whose planned chaser already
            chased in another chase game, as ``(chaser id, other game
            key)`` by game key. A fixed result can cause this; the game
            can't be seated until it's sorted out.
        accepted_chasers: For each played chase game, every chaser the
            regular games gave it at some point as players dropped out (and
            before or after any voided Semifinal added wildcards). A chase
            game played between two dropouts keeps the chaser it had then,
            so only a fixed result makes its chaser wrong.
        play_in_players: The next players after the advancers, who play
            the play-in games added when players with a bye drop out (see
            :mod:`jparty.domain.tournament.dropouts`), best first.
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
    accepted_chasers: dict[str, frozenset[str]] = field(default_factory=dict)
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
    coryats: dict[str, int | None] | None = None,
    seeding: Iterable[int] = (),
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
        coryats: Each player's Coryat score, or ``None`` if unknown.
        seeding: Cutoffs that only decide seeding, such as which chase game
            a chaser plays, not who gets into a round. A tie across only
            these goes to the higher Coryat score; a tiebreaker is needed
            only if that's tied or unknown too.

    Returns:
        The ranked ids, and any ties still to break.
    """
    order = sorted(players, key=lambda player_id: -scores[player_id])
    cuts = {cut for cut in cutoffs if 0 < cut < len(order)}
    seeding_cuts = set(seeding)
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
            straddled = [c for c in cuts if position < c < position + len(group)]
            best = _best_coryat(group, coryats or {})
            if best is not None and all(c in seeding_cuts for c in straddled):
                ranked.append(best)
                group.remove(best)
                position += 1
                continue
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


def _best_coryat(group: Sequence[str], coryats: dict[str, int | None]) -> str | None:
    """Return the one player in ``group`` with the highest Coryat, or ``None``.

    ``None`` when any Coryat is unknown or the highest is shared.
    """
    values = [coryats.get(player_id) for player_id in group]
    if not values or any(value is None for value in values):
        return None
    top = max(values)
    if values.count(top) != 1:
        return None
    return group[values.index(top)]


def promotion_choice(
    standing: RoundStanding,
    candidates: Sequence[str],
    tiebreaks: Sequence[Tiebreak] = (),
) -> tuple[str | None, list[TieForSpot]]:
    """Return the waiting player to promote to a dropped player's bye.

    Winners come first, like the byes themselves, then wildcards, each by
    score. A tie for the top spot needs a tiebreaker, since it decides who
    goes straight to the next round.

    Args:
        standing: The standing of the round that gives the byes.
        candidates: Players who could be promoted: in the next round, and
            not played it yet.
        tiebreaks: Every tiebreaker played.

    Returns:
        The player, or ``None`` with the tie when it's tied (or ``None`` and
        no tie when there's no one to promote).
    """
    winners = [p for p in candidates if p in standing.winners]
    group = winners or list(candidates)
    if not group:
        return None, []
    order, ties = _ranked(
        group, standing.scores, (1,), tiebreaks, standing.name, TIE_BYE
    )
    return (None, ties) if ties else (order[0], [])


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
    next_round_players: Iterable[str] = (),
) -> RoundStanding:
    """Work out where one round stands from its results.

    Args:
        plan: The tournament's bracket.
        round_index: The round, as an index into ``plan.rounds``.
        results: Every saved result.
        tiebreaks: Every tiebreaker played.
        drops: How dropouts change the round, or ``None`` for no dropouts.
        next_round_players: Players who have played the next round, for a
            promotion to a bye that a tiebreaker still has to settle.

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
    coryats: dict[str, int | None] = {}
    for _key, _chase, rows in played:
        for row in rows:
            if row.player_id not in scores:
                first_seen.append(row.player_id)
                scores[row.player_id] = row.score
                coryats[row.player_id] = row.coryat
    layout = bracket_round.layout
    if layout is None:
        return _winners_only_standing(
            bracket_round, games_left, played, first_seen, scores, drops, tiebreaks
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
    # A chase game's chaser is whoever in it already played a regular
    # game this round; the other two are new players.
    regular_losers = set(pool)
    regular_ranking = [p for p in pool if p not in drops.slide]
    regular_players = regular_losers | set(winners)
    played_chasers: dict[str, str] = {}
    for key in chase_keys:
        rows = by_game.get(key)
        chaser_rows = [row for row in rows or () if row.player_id in regular_players]
        if chaser_rows:
            played_chasers[key] = chaser_rows[0].player_id
    # Both chasers are set once the regular games are done: the first
    # players out of the wildcards, with the last chase game going to the
    # first player out (see chaser_place). Players who dropped out slide
    # out of the ranking.
    planned: dict[str, str] = {}
    accepted: dict[str, frozenset[str]] = {}
    if chase_keys and not regular_left:
        planned, chaser_ties, accepted = _chaser_plan(
            pool,
            winners,
            scores,
            layout.wildcards,
            drops,
            chase_keys,
            played_chasers,
            tiebreaks,
            name,
            coryats,
        )
        ties.extend(chaser_ties)
    # Only a chaser who lost their regular game can open a wildcard spot.
    # (One who won it, after a fixed result, is already a winner and is
    # counted once.)
    chased_in: dict[str, str] = {}
    for key in chase_keys:
        rows = by_game.get(key)
        if rows is None:
            continue
        if key in played_chasers:
            chaser = next(row for row in rows if row.player_id == played_chasers[key])
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
    if drops.replacement_games and not _others_left(bracket_round, games_left, drops):
        # Only the regular games' non-winners: a chase game may need the
        # replay's result first, so its players can't decide the seat.
        replacements, replacement_ties = _replacements(
            regular_ranking, scores, drops.replacement_games, tiebreaks, name
        )
        ties.extend(replacement_ties)
    unfinished = RoundStanding(
        name,
        games_left=games_left,
        winners=tuple(winners),
        chasers=chasers,
        planned_chasers=planned,
        chaser_clashes=clashes,
        accepted_chasers=accepted,
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
    byes_out = dict(drops.byes_out)
    if drops.pending_promotions and not ties:
        # Promotions a tiebreaker had to settle: pick from the players
        # still waiting to play the next round.
        gone = set(byes_out) | set(drops.pending_promotions)
        waiting = set(next_round_players)
        for player_id in drops.pending_promotions:
            candidates = [
                p
                for p in winners + wildcards
                if p not in byes
                and p not in waiting
                and p not in gone
                and p not in byes_out.values()
            ]
            standing = RoundStanding(name, winners=tuple(winners), scores=scores)
            promoted, promote_ties = promotion_choice(standing, candidates, tiebreaks)
            ties.extend(promote_ties)
            byes_out[player_id] = promoted or ""
    if byes_out and not ties:
        # A bye who dropped out leaves. Either the player promoted to
        # their bye has their place taken by the next player, or a play-in
        # game for the next three players fills the bye's seat.
        out = set(byes_out)
        winners = [player_id for player_id in winners if player_id not in out]
        wildcards = [player_id for player_id in wildcards if player_id not in out]
        byes = [
            byes_out[player_id] if player_id in out else player_id for player_id in byes
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


def _chaser_plan(
    pool: Sequence[str],
    winners: Sequence[str],
    scores: dict[str, int],
    wildcards: int,
    drops: RoundDrops,
    chase_keys: Sequence[str],
    played_chasers: dict[str, str],
    tiebreaks: Sequence[Tiebreak],
    round_name: str,
    coryats: dict[str, int | None],
) -> tuple[dict[str, str], list[TieForSpot], dict[str, frozenset[str]]]:
    """Return the planned chasers, any ties, and each played game's accepted chasers.

    A played chase game's chaser is accepted if the regular games gave it
    to them at some point: before any dropout, after each one in turn, and
    with or without the wildcards a voided Semifinal adds. Earlier chase
    games' accepted chasers are held fixed while later ones are checked.
    When every played chaser is accepted, they stand, and the unplayed
    chase games go to the next players out who haven't chased. Otherwise
    a fixed result changed who should have chased, and every chase game is
    planned afresh, so the clash or conflict shows.

    Args:
        pool: The round's regular-game losers, in the order they played.
        winners: The round's regular-game winners.
        scores: Each player's score.
        wildcards: The layout's wildcard count.
        drops: How dropouts change the round.
        chase_keys: The round's chase games, in order.
        played_chasers: The chaser of each played chase game, by key.
        tiebreaks: Every tiebreaker played.
        round_name: The round.
        coryats: Each player's Coryat score.

    Returns:
        ``(planned, ties, accepted)``: see :class:`RoundStanding`.
    """

    def plan(
        slid: frozenset[str], extra: int, fixed: dict[str, str]
    ) -> tuple[dict[str, str], list[TieForSpot]]:
        ranking = [player_id for player_id in pool if player_id not in slid]
        spots = wildcards + extra + sum(1 for p in winners if p in slid)
        return _plan_chasers(
            ranking, scores, spots, chase_keys, tiebreaks, round_name, coryats, fixed
        )

    order = drops.slide_order
    if set(order) != drops.slide:
        order = tuple(sorted(drops.slide))
    moments = [
        (frozenset(order[:count]), extra)
        for count in range(len(order) + 1)
        for extra in dict.fromkeys((0, drops.extra_wildcards))
    ]
    accepted: dict[str, frozenset[str]] = {}
    fixed: dict[str, str] = {}
    for key in chase_keys:
        if key not in played_chasers:
            continue
        options = {
            planned[key]
            for slid, extra in moments
            if key in (planned := plan(slid, extra, fixed)[0])
        }
        accepted[key] = frozenset(options)
        if played_chasers[key] in options:
            fixed[key] = played_chasers[key]
    if played_chasers and fixed == played_chasers:
        planned, ties = plan(drops.slide, drops.extra_wildcards, fixed)
        return {**planned, **fixed}, ties, accepted
    planned, ties = plan(drops.slide, drops.extra_wildcards, {})
    return planned, ties, accepted


def _plan_chasers(
    ranking: Sequence[str],
    scores: dict[str, int],
    wildcard_spots: int,
    chase_keys: Sequence[str],
    tiebreaks: Sequence[Tiebreak],
    round_name: str,
    coryats: dict[str, int | None] | None = None,
    fixed: dict[str, str] | None = None,
) -> tuple[dict[str, str], list[TieForSpot]]:
    """Return who should chase in each chase game, by key, and any ties.

    The cutoffs between chasers only decide which chase game each plays, so
    a tie there goes to the higher Coryat score first.

    Chase games in ``fixed`` already have their chaser. The others go to the
    first players out of the wildcards who aren't in ``fixed``, the last
    open game to the first of them. When dropouts leave too few players to
    chase, the first chase games go without: they're played by their two
    new players alone (see :attr:`Eligibility.seats`).
    """
    if not fixed:
        cutoffs = range(wildcard_spots, wildcard_spots + len(chase_keys) + 1)
        seeding = range(wildcard_spots + 1, wildcard_spots + len(chase_keys))
        order, ties = _ranked(
            ranking,
            scores,
            cutoffs,
            tiebreaks,
            round_name,
            TIE_CHASER,
            coryats,
            seeding,
        )
        planned: dict[str, str] = {}
        if not ties:
            for index, key in enumerate(chase_keys):
                position = wildcard_spots + len(chase_keys) - 1 - index
                if position < len(order):
                    planned[key] = order[position]
        return planned, ties
    open_keys = [key for key in chase_keys if key not in fixed]
    if not open_keys:
        return {}, []
    order, ties = _ranked(
        ranking, scores, (wildcard_spots,), tiebreaks, round_name, TIE_CHASER
    )
    if ties:
        return {}, ties
    chased = set(fixed.values())
    below = [
        player_id for player_id in order[wildcard_spots:] if player_id not in chased
    ]
    count = len(open_keys)
    order, ties = _ranked(
        below,
        scores,
        range(1, count + 1),
        tiebreaks,
        round_name,
        TIE_CHASER,
        coryats,
        range(1, count),
    )
    if ties:
        return {}, ties
    return {
        key: order[count - 1 - index]
        for index, key in enumerate(open_keys)
        if count - 1 - index < len(order)
    }, []


def _others_left(
    bracket_round: BracketRound, games_left: Sequence[str], drops: RoundDrops
) -> bool:
    """Return whether regular games other than the voided ones are still to play.

    A voided game's replacement is the best non-winner of the round's other
    regular games, so it's known only once they're all played. Chase games
    don't count: their chaser can come from the voided game's replay.
    """
    return any(
        key in games_left and key not in drops.replacement_games
        for game in bracket_round.games
        if not game.chase and not game.play_in
        for key in (game_key(bracket_round, game),)
    )


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
    bracket_round: BracketRound,
    games_left: tuple[str, ...],
    played: Sequence[tuple[str, bool, list[GameResult]]],
    first_seen: Sequence[str],
    scores: dict[str, int],
    drops: RoundDrops,
    tiebreaks: Sequence[Tiebreak],
) -> RoundStanding:
    """Return the standing of a round where only game winners advance."""
    name = bracket_round.name
    winners = [
        row.player_id for _key, _chase, rows in played for row in rows if row.won
    ]
    replacements: dict[str, str] = {}
    ties: list[TieForSpot] = []
    if drops.replacement_games and not _others_left(bracket_round, games_left, drops):
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
            :func:`jparty.domain.tournament.dropouts.effective_plan`).
        results: Every saved result.
        tiebreaks: Every tiebreaker played.
        dropouts: Every player who dropped out.

    Returns:
        One standing per round of ``plan``.
    """
    drops = round_drops(plan, dropouts)
    by_game = results_by_game(results)
    next_players = []
    for index in range(len(plan.rounds)):
        later = plan.rounds[index + 1] if index + 1 < len(plan.rounds) else None
        next_players.append(
            {
                row.player_id
                for game in (later.games if later else ())
                for row in by_game.get(game_key(later, game), [])
            }
        )
    return [
        round_standing(
            plan, index, results, tiebreaks, drops[index], next_players[index]
        )
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
        seats: How many podiums the game needs. A chase game has only its
            two new players when dropouts left no one to chase in it.
    """

    entrants: tuple[str, ...] = ()
    chasers: tuple[str, ...] = ()
    chase: bool = False
    waiting: str = ""
    seats: int = PLAYERS_PER_GAME

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
        key: The game, as :func:`jparty.domain.tournament.setup.game_key`
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
    if key in round_drops(plan, dropouts)[round_index].replacement_games:
        waiting = (
            tie_text(standing.ties[0], names)
            if standing.ties
            else "The player taking the dropped seat is known once the rest of "
            f"the {standing.name} are played."
        )
        return Eligibility(open_seats, chase=game.chase, waiting=waiting)
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
        bracket_round = plan.rounds[round_index]
        regular_left = any(
            game_key(bracket_round, other) in standing.games_left
            for other in bracket_round.games
            if not other.chase and not other.play_in
        )
        if standing.ties:
            waiting = tie_text(standing.ties[0], names)
        elif regular_left:
            waiting = "The chaser is known once this round's regular games are played."
        else:
            # Dropouts left no one to chase: the two new players play for
            # the game's spot on their own.
            return Eligibility(open_seats, chase=True, seats=CHASE_GAME_NEW_PLAYERS)
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


def seating_gaps(
    plan: TournamentPlan,
    slots: Sequence[PlayerSlot],
    results: Sequence[GameResult],
    tiebreaks: Sequence[Tiebreak] = (),
    dropouts: Sequence[Dropout] = (),
) -> list[str]:
    """Return seats that nobody is left to fill.

    Dropouts can cause these, so :mod:`jparty.domain.tournament.drop_choices`
    refuses a choice that would. Three things are checked:

    - Each qualifying round knocks out a set number of players: its field
      less the spots it fills. Every dropout that someone moves up for uses
      one of them up, as does each wildcard added for a voided game and
      each promotion to a dropped bye; a play-in game not yet played needs
      three. This is counted ahead, before the round is played, so a gap
      shows as soon as the dropout that causes it.
    - In a round whose players are known, fewer players waiting to play
      than its unplayed games have new seats.
    - A play-in game with too few players.

    A chase game with no one left to chase in it isn't a gap: its two new
    players play it (see :attr:`Eligibility.seats`).

    Args:
        plan: The tournament's bracket, with any play-in games.
        slots: The roster.
        results: Every saved result.
        tiebreaks: Every tiebreaker played.
        dropouts: Every player who dropped out.

    Returns:
        One message per gap, or an empty list.
    """
    gone = dropped_ids(dropouts)
    names = {slot.player_id: slot.actual_name.strip() for slot in slots}
    named = [
        slot.player_id
        for slot in slots
        if slot.actual_name.strip() and slot.player_id not in gone
    ]
    standings = tournament_standings(plan, results, tiebreaks, dropouts)
    drops = round_drops(plan, dropouts)
    by_game = results_by_game(results)
    gaps: list[str] = []
    for index, bracket_round in enumerate(plan.rounds):
        later = plan.rounds[index + 1] if index + 1 < len(plan.rounds) else None
        short = _knocked_out_short(bracket_round, later, drops[index], by_game)
        if short:
            gaps.append(
                f"The {bracket_round.name} would have {short} too few players left "
                "to move up into dropped players' spots."
            )
        unplayed = [
            (game_key(bracket_round, game), game)
            for game in bracket_round.games
            if game_key(bracket_round, game) not in by_game
        ]
        if not unplayed:
            continue
        standing = standings[index]
        play_ins = [key for key, game in unplayed if game.play_in]
        if play_ins:
            seats = _play_in_eligibility(standings[index - 1], named, names, standing)
            needed = PLAYERS_PER_GAME * len(play_ins)
            if not seats.waiting and len(seats.entrants) < needed:
                gaps.append(
                    f"{_game_name(play_ins[0])} would have only "
                    f"{len(seats.entrants)} of its {needed} players."
                )
        entrants = round_entrants(plan, standings, index, names, gone)
        if entrants.waiting:
            continue
        allowed = None if entrants.players is None else set(entrants.players)
        waiting = [
            player_id
            for player_id in named
            if player_id not in standing.scores
            and (allowed is None or player_id in allowed)
        ]
        new_seats = 0
        for key, game in unplayed:
            if game.play_in:
                continue
            if game.chase:
                new_seats += CHASE_GAME_NEW_PLAYERS
            elif key in drops[index].replacement_games:
                new_seats += PLAYERS_PER_GAME - 1
            else:
                new_seats += PLAYERS_PER_GAME
        if len(waiting) < new_seats:
            gaps.append(
                f"The {bracket_round.name} would have {len(waiting)} players for "
                f"{new_seats} open seats."
            )
    return gaps


def _knocked_out_short(
    bracket_round: BracketRound,
    later: BracketRound | None,
    drops: RoundDrops,
    by_game: dict[str, list[GameResult]],
) -> int:
    """Return how many more players a qualifying round's dropouts need than it knocks out.

    Args:
        bracket_round: The round.
        later: The round after it, which holds any play-in games.
        drops: How dropouts change the round.
        by_game: Every saved result, by game key.

    Returns:
        The shortfall, or 0.
    """
    layout = bracket_round.layout
    if layout is None:
        return 0
    play_ins = [
        game_key(later, game) for game in (later.games if later else ()) if game.play_in
    ]
    used = (
        len(drops.slide)
        + drops.extra_wildcards
        + drops.promotions
        + len(drops.replacement_games)
        + sum(1 if key in by_game else PLAYERS_PER_GAME for key in play_ins)
    )
    return max(0, used - (layout.players - layout.spots))


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
    if len(picked) != eligibility.seats:
        if eligibility.seats < PLAYERS_PER_GAME:
            return (
                f"No one is left to chase in this game: choose its "
                f"{eligibility.seats} new players and leave one podium empty."
            )
        return f"Choose a player for each of the {eligibility.seats} podiums."
    if len(set(picked)) != len(picked):
        return "Choose a different player for each podium."
    if any(player_id not in eligibility.player_ids for player_id in picked):
        return "One of the chosen players can't play this game."
    if eligibility.chase and eligibility.seats == PLAYERS_PER_GAME:
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
            statuses[player_id] = (STATUS_OUT, True)
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
        # without advancing out of it, so they may only sit in play-in games.
        extra = set(standings[index - 1].play_in_players) if index > 0 else set()
        if entrants.waiting:
            feeders = [index - 1]
            skipped_from = index - 2
            if skipped_from >= 0 and plan.rounds[skipped_from].byes:
                feeders.append(skipped_from)
            allowed = {p for feeder in feeders for p in standings[feeder].scores}
        else:
            allowed = None if entrants.players is None else set(entrants.players)
        regular_left = [
            game_key(bracket_round, game)
            for game in bracket_round.games
            if not game.chase
            and not game.play_in
            and game_key(bracket_round, game) not in by_game
        ]
        for game in bracket_round.games:
            key = game_key(bracket_round, game)
            rows = by_game.get(key, [])
            if not rows:
                continue
            if game.chase and regular_left and bracket_round.layout is not None:
                # The chaser comes from the regular games, so a chase game
                # can't stand before they're all played (for example after
                # a regular game's results were deleted).
                left = ", ".join(_game_name(other) for other in regular_left)
                were, are = ("was", "is") if len(regular_left) == 1 else ("were", "are")
                players = ", ".join(name(row.player_id, row) for row in rows)
                problems.append(
                    f"{_game_name(key)}: {players} played it before {left} {were} "
                    f"played. Delete its results too, and replay it once {left} "
                    f"{are} played."
                )
                continue
            chaser = standing.chasers.get(key) if game.chase else None
            seat_ok = allowed
            if allowed is not None and game.play_in:
                seat_ok = allowed | extra
            if seat_ok is not None:
                for row in rows:
                    if row.player_id != chaser and row.player_id not in seat_ok:
                        problems.append(
                            f"{_game_name(key)}: {name(row.player_id, row)} played, "
                            f"but they didn't advance into the {bracket_round.name}."
                        )
            planned = standing.planned_chasers.get(key) if game.chase else None
            if (
                planned is not None
                and chaser != planned
                and chaser not in standing.accepted_chasers.get(key, frozenset())
            ):
                played = (
                    f"{name(chaser)} chased"
                    if chaser
                    else ", ".join(name(row.player_id, row) for row in rows)
                    + " played it with no chaser"
                )
                problems.append(
                    f"{_game_name(key)}: {played}, but the chaser should be "
                    f"{name(planned)}."
                )
    return problems
