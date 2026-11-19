"""Players who drop out of a tournament, and what happens to their spot.

A player can be marked as dropped out at any time. What happens next
depends on how far they got:

- **Before their first game**, the host chooses to *reduce* the field by
  one, so the games not yet played are re-planned for the smaller field, or
  to *replace* them with a new player. Games already played stay as played.
- **After their first game, before they win a Semifinal**, everyone ranked
  beneath them in the last round they played *slides* up a place. If they
  won their game, that round has one more wildcard.
- **A Semifinal winner** who drops out has their Semifinal *voided*: its
  results are set aside and it is replayed on a new board. The next-ranked
  player of the round before the Semifinals (the Second Round, if there is
  one) takes their seat. When the Semifinals are the first round, the best
  non-winner from the other Semifinals takes it.
  That case is only partly specified: these rules are meant for brackets
  with three or more rounds. With 4 to 8 players, where the Semifinals
  also have wildcards or chase games, the replacement has played two
  Semifinals and can be counted twice; check the Final's players by hand.
- **A player with a Semifinal bye**: if no Second Round game has been
  played, the Preliminaries slide up as above. Once one has, the host
  chooses either a *play-in* game for the next three Preliminaries players,
  whose winner takes the bye's Semifinal seat, or to *promote* the
  best-ranked Second Round player who hasn't played yet to the bye, with the
  next Preliminaries player taking their Second Round seat.

A :class:`Dropout` records each choice, in ``dropouts.csv``. This module
turns them into the bracket that is actually played
(:func:`effective_plan`) and into each round's adjustments
(:func:`round_drops`), which
:mod:`jparty.domain.tournament_advancement` applies.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament import (
    ROUND_SEMIFINALS,
    ROUND_SHORT_NAMES,
    BracketGame,
    TournamentPlan,
    plan_tournament,
)
from jparty.domain.tournament_setup import BracketSettings

DROP_REDUCE = "reduce"
DROP_REPLACE = "replace"
DROP_SLIDE = "slide"
DROP_VOID = "void"
DROP_PLAY_IN = "play_in"
DROP_PROMOTE = "promote"
DROP_CHOICES = (
    DROP_REDUCE,
    DROP_REPLACE,
    DROP_SLIDE,
    DROP_VOID,
    DROP_PLAY_IN,
    DROP_PROMOTE,
)
# Choices for a player who dropped out before playing: they aren't part of
# the field at all.
BEFORE_PLAYING = frozenset({DROP_REDUCE, DROP_REPLACE})

PLAY_IN_GAME_NAME = "Play-in"


@dataclass(frozen=True)
class Dropout:
    """One player who dropped out, and what the host chose to do.

    Attributes:
        player_id: The player who dropped out.
        round_name: The round whose spots the dropout changes: the first
            round for :data:`DROP_REDUCE` and :data:`DROP_REPLACE`, the last
            round they played for :data:`DROP_SLIDE`, the Semifinals for
            :data:`DROP_VOID`, and the round their bye came from for
            :data:`DROP_PLAY_IN` and :data:`DROP_PROMOTE`.
        choice: One of :data:`DROP_CHOICES`.
        game_key: The voided game for :data:`DROP_VOID`, or the added
            play-in game for :data:`DROP_PLAY_IN`; ``""`` otherwise.
        other_id: The new player for :data:`DROP_REPLACE`, or the player
            promoted to the bye for :data:`DROP_PROMOTE` (``""`` while a
            tiebreaker still has to pick them); ``""`` otherwise.
        player_name: The player's Actual Name when they dropped out, so the
            saved file reads well. Not used to match anything.
    """

    player_id: str
    round_name: str
    choice: str
    game_key: str = ""
    other_id: str = ""
    player_name: str = field(default="", compare=False)


@dataclass(frozen=True)
class RoundDrops:
    """How dropouts change one round's standing.

    Attributes:
        slide: Players removed from the round's ranking, whose spots go to
            the players beneath them. A removed winner's spot becomes one
            more wildcard.
        extra_wildcards: More wildcard spots, one for each voided Semifinal
            this round feeds.
        byes_out: Players who lose their bye, by player id. The value is the
            player promoted to the bye, or ``""`` when a play-in game fills
            the seat instead.
        pending_promotions: Players who lose their bye to a promoted player
            not chosen yet, because the best waiting players were tied when
            they dropped out. A tiebreaker picks the player.
        replacement_games: Voided games of this round whose dropped seat
            goes to the best non-winner of the round's other games, in the
            order they were voided. Only used when the voided round is the
            first round, so there's no earlier round to take a player from.
    """

    slide: frozenset[str] = frozenset()
    extra_wildcards: int = 0
    byes_out: dict[str, str] = field(default_factory=dict)
    pending_promotions: tuple[str, ...] = ()
    replacement_games: tuple[str, ...] = ()

    @property
    def promotions(self) -> int:
        """Return how many byes go to a promoted player, chosen or not."""
        chosen = sum(1 for promoted in self.byes_out.values() if promoted)
        return chosen + len(self.pending_promotions)

    @property
    def play_ins(self) -> int:
        """Return how many byes are filled by a play-in game."""
        return sum(1 for promoted in self.byes_out.values() if not promoted)


def dropped_ids(dropouts: Sequence[Dropout]) -> frozenset[str]:
    """Return every player who dropped out."""
    return frozenset(dropout.player_id for dropout in dropouts)


def field_size(slots: Sequence[PlayerSlot], dropouts: Sequence[Dropout]) -> int:
    """Return the number of players the bracket is planned for.

    Players who dropped out before playing aren't part of the field. A
    replacement is a new row on the roster, so replacing someone keeps the
    count.

    Args:
        slots: The roster.
        dropouts: Every dropout.

    Returns:
        The roster's size, less players who dropped out before playing.
    """
    before = {d.player_id for d in dropouts if d.choice in BEFORE_PLAYING}
    return sum(1 for slot in slots if slot.player_id not in before)


def play_in_game_key(plan: TournamentPlan, number: int) -> str | None:
    """Return the key of play-in game ``number``, counting from 1.

    Play-in games join the round after the one with byes.

    Args:
        plan: The tournament's bracket.
        number: The play-in game's number.

    Returns:
        The key, or ``None`` if the bracket has no byes.
    """
    index = _bye_round_index(plan)
    if index is None:
        return None
    return f"{plan.rounds[index + 1].name}: {PLAY_IN_GAME_NAME} {number}"


def _bye_round_index(plan: TournamentPlan) -> int | None:
    """Return the index of the round that gives byes, or ``None``."""
    for index, bracket_round in enumerate(plan.rounds[:-1]):
        if bracket_round.byes:
            return index
    return None


def next_play_in_number(dropouts: Sequence[Dropout]) -> int:
    """Return the number for a new play-in game.

    Numbers aren't reused, so taking one play-in back never renames
    another, whose results are saved under its name.

    Args:
        dropouts: Every dropout.

    Returns:
        One more than the highest play-in number so far, or 1.
    """
    numbers = [0]
    for dropout in dropouts:
        if dropout.choice == DROP_PLAY_IN:
            tail = dropout.game_key.rsplit(" ", 1)[-1]
            numbers.append(int(tail) if tail.isdigit() else 0)
    return max(numbers) + 1


def apply_dropouts(plan: TournamentPlan, dropouts: Sequence[Dropout]) -> TournamentPlan:
    """Return ``plan`` with a play-in game for each :data:`DROP_PLAY_IN`.

    Each play-in game is named after its dropout's ``game_key``.

    Args:
        plan: The bracket planned for the field.
        dropouts: Every dropout.

    Returns:
        The bracket that is actually played.
    """
    keys = [d.game_key for d in dropouts if d.choice == DROP_PLAY_IN and d.game_key]
    index = _bye_round_index(plan) if plan.valid else None
    if not keys or index is None:
        return plan
    short_name = ROUND_SHORT_NAMES[plan.rounds[index].name]
    target = plan.rounds[index + 1]
    extra = tuple(
        BracketGame(
            key.split(": ", 1)[-1],
            (f"{short_name} next player",) * 3,
            play_in=True,
        )
        for key in keys
    )
    rounds = list(plan.rounds)
    rounds[index + 1] = replace(target, games=target.games + extra)
    return replace(plan, rounds=tuple(rounds))


def effective_plan(
    bracket: BracketSettings, slots: Sequence[PlayerSlot], dropouts: Sequence[Dropout]
) -> TournamentPlan:
    """Return the bracket actually played, given the dropouts so far.

    Args:
        bracket: The tournament's bracket settings.
        slots: The roster.
        dropouts: Every dropout.

    Returns:
        The planned bracket for the field, with any play-in games added.
    """
    plan = plan_tournament(bracket.options(field_size(slots, dropouts)))
    return apply_dropouts(plan, dropouts)


def round_drops(plan: TournamentPlan, dropouts: Sequence[Dropout]) -> list[RoundDrops]:
    """Return how the dropouts change each round, in playing order.

    Args:
        plan: The bracket actually played, from :func:`effective_plan`.
        dropouts: Every dropout.

    Returns:
        One :class:`RoundDrops` per round of ``plan``.
    """
    names = [bracket_round.name for bracket_round in plan.rounds]
    slide: list[set[str]] = [set() for _ in names]
    extra = [0] * len(names)
    byes_out: list[dict[str, str]] = [{} for _ in names]
    replacements: list[list[str]] = [[] for _ in names]
    pending: list[list[str]] = [[] for _ in names]
    for dropout in dropouts:
        if dropout.round_name not in names:
            continue
        index = names.index(dropout.round_name)
        if dropout.choice == DROP_SLIDE:
            slide[index].add(dropout.player_id)
        elif dropout.choice == DROP_VOID:
            if index > 0:
                extra[index - 1] += 1
            else:
                replacements[index].append(dropout.game_key)
        elif dropout.choice == DROP_PROMOTE and dropout.other_id:
            byes_out[index][dropout.player_id] = dropout.other_id
        elif dropout.choice == DROP_PROMOTE:
            pending[index].append(dropout.player_id)
        elif dropout.choice == DROP_PLAY_IN:
            byes_out[index][dropout.player_id] = ""
    return [
        RoundDrops(
            frozenset(slide[index]),
            extra[index],
            byes_out[index],
            tuple(pending[index]),
            tuple(replacements[index]),
        )
        for index in range(len(names))
    ]


def semifinal_index(plan: TournamentPlan) -> int | None:
    """Return the index of the Semifinals in ``plan``, or ``None``."""
    for index, bracket_round in enumerate(plan.rounds):
        if bracket_round.name == ROUND_SEMIFINALS:
            return index
    return None
