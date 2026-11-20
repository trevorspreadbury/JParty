"""Tournament rankings: every player, best first, and how far they've got.

Players are ranked by how far they've got in the bracket, then by their
latest score:

1. The champion is first.
2. Next come players by the furthest round they've reached. A player
   reaches a round by playing in it or by advancing into it, and a bye
   reaches the round after next.
3. Within a round, players still in the tournament rank above players
   knocked out or dropped out there.
4. Ties go to the higher score in the player's latest round (a chaser's
   chase score doesn't count, as in :class:`RoundStanding.scores`).

Players who haven't played or advanced anywhere have no rank yet and come
last, in roster order.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament import TournamentPlan
from jparty.domain.tournament_advancement import (
    STATUS_OUT,
    RoundStanding,
    Tiebreak,
    player_statuses,
    tournament_standings,
)
from jparty.domain.tournament_dropouts import Dropout, dropped_ids
from jparty.domain.tournament_play import GameResult

NOT_PLAYED_TEXT = "hasn't played"


@dataclass(frozen=True)
class PlayerRanking:
    """One player's place in the tournament.

    Attributes:
        rank: The player's place, from 1, shared by players level on
            everything ranked. ``None`` for a player who hasn't played.
        player_id: The player's id.
        name: The player's Actual Name.
        status: Where the player stands, such as ``"won, in the Final"``.
        reached: The furthest round the player has reached, or ``""``.
        games: Games the player has played.
        total_score: The player's final scores, added up.
        best_score: The player's best final score, or ``None``.
        coryat: The player's Coryat scores, added up, or ``None`` if no game
            recorded one.
        out: Whether the player has been knocked out or dropped out.
    """

    rank: int | None
    player_id: str
    name: str
    status: str
    reached: str = ""
    games: int = 0
    total_score: int = 0
    best_score: int | None = None
    coryat: int | None = None
    out: bool = False


def _reach(
    player_id: str, standings: Sequence[RoundStanding]
) -> tuple[int, int | None]:
    """Return how many rounds in ``player_id`` is, and their latest score.

    Args:
        player_id: A player id.
        standings: Every round's standing.

    Returns:
        ``(stage, score)``. ``stage`` is 0 for a player who hasn't played or
        advanced, ``index + 1`` for one who has reached round ``index``,
        and one more than the round count for the champion. ``score`` is
        the player's score in the latest round they played.
    """
    stage = 0
    score = None
    for index, standing in enumerate(standings):
        if player_id in standing.scores:
            stage = max(stage, index + 1)
            score = standing.scores[player_id]
        if not standing.decided:
            continue
        if player_id in standing.byes:
            stage = max(stage, index + 3)
        elif player_id in standing.advancers or player_id in standing.play_in_players:
            stage = max(stage, index + 2)
    return stage, score


def tournament_rankings(
    plan: TournamentPlan | None,
    slots: Sequence[PlayerSlot],
    results: Sequence[GameResult],
    tiebreaks: Sequence[Tiebreak] = (),
    dropouts: Sequence[Dropout] = (),
) -> list[PlayerRanking]:
    """Return every named player on the roster, best first.

    Args:
        plan: The bracket actually played, with any play-in games (see
            :func:`jparty.domain.tournament_dropouts.effective_plan`), or
            ``None``. A plan that doesn't work ranks nobody.
        slots: The roster.
        results: Every saved result.
        tiebreaks: Every tiebreaker played.
        dropouts: Every player who dropped out.

    Returns:
        One ranking per named player: ranked players best first, then the
        players with no rank, in roster order.
    """
    valid = plan is not None and plan.valid
    standings = (
        tournament_standings(plan, results, tiebreaks, dropouts) if valid else []
    )
    statuses = player_statuses(plan, standings, dropouts) if valid else {}
    round_names = [bracket_round.name for bracket_round in plan.rounds] if valid else []
    dropped = dropped_ids(dropouts)
    rows_by_player: dict[str, list[GameResult]] = {}
    for row in results:
        rows_by_player.setdefault(row.player_id, []).append(row)

    keyed = []
    for order, slot in enumerate(slots):
        name = slot.actual_name.strip()
        if not name:
            continue
        rows = rows_by_player.get(slot.player_id, [])
        stage, latest = _reach(slot.player_id, standings)
        coryats = [row.coryat for row in rows if row.coryat is not None]
        status = statuses.get(slot.player_id, (NOT_PLAYED_TEXT, False))[0]
        # The status is where the player is now, so a player knocked out of
        # one round who then got a play-in seat isn't out.
        out = slot.player_id in dropped or status == STATUS_OUT
        if stage > len(round_names):
            reached = "Champion"
        elif stage:
            reached = round_names[stage - 1]
        else:
            reached = ""
        ranking = PlayerRanking(
            rank=None,
            player_id=slot.player_id,
            name=name,
            status=status,
            reached=reached,
            games=len(rows),
            total_score=sum(row.score for row in rows),
            best_score=max((row.score for row in rows), default=None),
            coryat=sum(coryats) if coryats else None,
            out=out,
        )
        # Higher stage first, players still in before players out, then
        # higher latest score. A player with no score sorts after one with.
        level = (-stage, out, -(latest if latest is not None else -(10**12)))
        keyed.append((stage, level, order, ranking))

    ranked = sorted((item for item in keyed if item[0]), key=lambda i: (i[1], i[2]))
    unranked = [item[3] for item in keyed if not item[0]]
    rankings = []
    previous_level = None
    rank = 0
    for position, (_stage, level, _order, ranking) in enumerate(ranked, start=1):
        if level != previous_level:
            rank = position
            previous_level = level
        rankings.append(replace(ranking, rank=rank))
    return rankings + unranked
