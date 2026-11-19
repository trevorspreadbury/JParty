"""What the host can choose when a tournament player drops out.

:func:`drop_situation` works out where a player stands and which of the
rules in :mod:`jparty.domain.tournament_dropouts` apply to them, as
:class:`DropOption` choices for the host. :func:`apply_drop` and
:func:`undo_drop` return the tournament's data with a dropout added or
taken back, as a :class:`TournamentData` for the store to save.

These are pure functions over plain data, like the rest of the tournament
rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament import ROUND_FINAL, ROUND_SEMIFINALS, TournamentPlan
from jparty.domain.tournament_advancement import (
    RoundStanding,
    Tiebreak,
    advancement_conflicts,
    promotion_choice,
    round_entrants,
    tournament_standings,
)
from jparty.domain.tournament_dropouts import (
    DROP_PLAY_IN,
    DROP_PROMOTE,
    DROP_REDUCE,
    DROP_REPLACE,
    DROP_SLIDE,
    DROP_VOID,
    Dropout,
    dropped_ids,
    effective_plan,
    field_size,
    next_play_in_number,
    play_in_game_key,
)
from jparty.domain.tournament_play import GameResult, results_by_game
from jparty.domain.tournament_setup import (
    BracketSettings,
    TournamentBoard,
    game_key,
    plan_games,
    reconcile_boards,
)


@dataclass(frozen=True)
class TournamentData:
    """Everything a dropout can change, as saved in the tournament folder.

    Attributes:
        bracket: Bracket settings.
        slots: The roster.
        results: Every saved result.
        tiebreaks: Every tiebreaker played.
        dropouts: Every dropout, in the order they happened.
        voided: Results of voided games, set aside.
        boards: Board for each game, by game key.
        unassigned: Boards not assigned to any game.
        retired: Boards of voided games, kept so they aren't played again.
            Each remembers its game in ``left_game_key``.
    """

    bracket: BracketSettings
    slots: tuple[PlayerSlot, ...]
    results: tuple[GameResult, ...] = ()
    tiebreaks: tuple[Tiebreak, ...] = ()
    dropouts: tuple[Dropout, ...] = ()
    voided: tuple[GameResult, ...] = ()
    boards: dict[str, TournamentBoard] = field(default_factory=dict)
    unassigned: tuple[TournamentBoard, ...] = ()
    retired: tuple[TournamentBoard, ...] = ()

    @property
    def plan(self) -> TournamentPlan:
        """Return the bracket actually played."""
        return effective_plan(self.bracket, self.slots, self.dropouts)

    def standings(self) -> list[RoundStanding]:
        """Return every round's standing."""
        return tournament_standings(
            self.plan, self.results, self.tiebreaks, self.dropouts
        )

    def names(self) -> dict[str, str]:
        """Return each player's Actual Name, by player id."""
        return {slot.player_id: slot.actual_name.strip() for slot in self.slots}


@dataclass(frozen=True)
class DropOption:
    """One thing the host can choose to do about a dropout.

    Attributes:
        dropout: The dropout this option records. For
            :data:`DROP_REPLACE`, ``other_id`` is filled in by
            :func:`apply_drop` once the new player is named.
        label: Short text for the choice.
        detail: What happens, for the host.
        problem: Why this option can't be chosen, or ``""``.
    """

    dropout: Dropout
    label: str
    detail: str
    problem: str = ""


@dataclass(frozen=True)
class DropSituation:
    """Where a player stands, and what the host can do if they drop out.

    Attributes:
        player_id: The player.
        summary: Where they stand, for the host.
        options: The host's choices. Empty when :attr:`problem` is set.
        problem: Why the player can't be dropped, or ``""``.
    """

    player_id: str
    summary: str
    options: tuple[DropOption, ...] = ()
    problem: str = ""


def drop_situation(data: TournamentData, player_id: str) -> DropSituation:
    """Return what can happen if ``player_id`` drops out now.

    Args:
        data: The tournament.
        player_id: The player dropping out.

    Returns:
        The player's situation and the host's choices.
    """
    names = data.names()
    name = names.get(player_id) or player_id
    if player_id in dropped_ids(data.dropouts):
        return DropSituation(player_id, "", problem=f"{name} already dropped out.")
    plan = data.plan
    if not plan.valid:
        return DropSituation(
            player_id, "", problem="The bracket doesn't work yet; fix it first."
        )
    standings = data.standings()
    played = [
        index
        for index, standing in enumerate(standings)
        if player_id in standing.scores
    ]
    if not played:
        return _before_playing(data, player_id, name)
    last = played[-1]
    bracket_round = plan.rounds[last]
    standing = standings[last]
    by_game = results_by_game(data.results)
    if bracket_round.name == ROUND_FINAL:
        return DropSituation(
            player_id, "", problem=f"{name} has played the Final; it's over."
        )
    won = next(
        (
            game_key(bracket_round, game)
            for game in bracket_round.games
            if any(
                row.player_id == player_id and row.won
                for row in by_game.get(game_key(bracket_round, game), [])
            )
        ),
        None,
    )
    if bracket_round.name == ROUND_SEMIFINALS and won is not None:
        return _semifinal_winner(data, player_id, name, last, won)
    if player_id in standing.eliminated or (
        bracket_round.layout is None and standing.decided is False and won is None
    ):
        return DropSituation(player_id, "", problem=f"{name} is already out.")
    if player_id in standing.byes and _round_started(data, last + 1):
        return _bye_after_start(data, player_id, name, last)
    where = f"won {won.split(': ', 1)[-1]}" if won else "played"
    summary = f"{name} {where} in the {bracket_round.name}."
    dropout = Dropout(player_id, bracket_round.name, DROP_SLIDE, player_name=name)
    detail = (
        f"Everyone ranked beneath them in the {bracket_round.name} moves up a place."
    )
    if won:
        detail += (
            f" They won their game, so the {bracket_round.name} get one more wildcard."
        )
    return DropSituation(
        player_id,
        summary,
        (_option(data, dropout, "Move everyone up", detail),),
    )


def _before_playing(data: TournamentData, player_id: str, name: str) -> DropSituation:
    """Return the choices for a player who hasn't played a game."""
    plan = data.plan
    first = plan.rounds[0].name
    size = field_size(data.slots, data.dropouts)
    reduce = Dropout(player_id, first, DROP_REDUCE, player_name=name)
    problem = _reduce_problem(data, reduce)
    options = (
        _option(
            data,
            reduce,
            f"Reduce the field to {size - 1} players",
            f"The games not yet played are planned again for {size - 1} "
            "players. Games already played stay as played. Boards of games "
            "that go away go back to unassigned.",
            problem,
        ),
        DropOption(
            Dropout(player_id, first, DROP_REPLACE, player_name=name),
            "Replace them with a new player",
            f"A new player joins the roster and plays in the {first} instead.",
        ),
    )
    return DropSituation(player_id, f"{name} hasn't played yet.", options)


def _reduce_problem(data: TournamentData, dropout: Dropout) -> str:
    """Return why the field can't shrink by one, or ``""``."""
    after = replace(data, dropouts=(*data.dropouts, dropout))
    plan = after.plan
    if not plan.valid:
        return f"The bracket doesn't work with one fewer player: {plan.problems[0]}"
    before = {key: game.chase for key, _round, game in plan_games(data.plan)}
    now = {key: game.chase for key, _round, game in plan_games(plan)}
    lost = sorted(
        {
            row.game_key
            for row in data.results
            if now.get(row.game_key) != before.get(row.game_key)
        }
    )
    if lost:
        games = ", ".join(key.split(": ", 1)[-1] for key in lost)
        return f"The smaller bracket doesn't have the games already played ({games})."
    return ""


def _round_started(data: TournamentData, index: int) -> bool:
    """Return whether any game of round ``index`` has been played."""
    plan = data.plan
    if not 0 <= index < len(plan.rounds):
        return False
    bracket_round = plan.rounds[index]
    keys = {game_key(bracket_round, game) for game in bracket_round.games}
    return any(row.game_key in keys for row in data.results)


def _semifinal_winner(
    data: TournamentData, player_id: str, name: str, index: int, key: str
) -> DropSituation:
    """Return the choice for a player who won their Semifinal."""
    if _round_started(data, index + 1):
        return DropSituation(
            player_id,
            "",
            problem=f"{name} won a Semifinal, but the Final has been played.",
        )
    game = key.split(": ", 1)[-1]
    plan = data.plan
    if index > 0:
        who = f"The next-ranked {plan.rounds[index - 1].name} player"
    else:
        who = "The best non-winner from the other Semifinals"
    dropout = Dropout(
        player_id, plan.rounds[index].name, DROP_VOID, game_key=key, player_name=name
    )
    detail = (
        f"{game} is voided: its results are set aside, and it's played again "
        f"on a new board. {who} takes {name}'s seat. Set the new board on the "
        "Games tab."
    )
    return DropSituation(
        player_id,
        f"{name} won {game}.",
        (_option(data, dropout, f"Void and replay {game}", detail),),
    )


def _bye_after_start(
    data: TournamentData, player_id: str, name: str, index: int
) -> DropSituation:
    """Return the choices for a bye who drops out once the next round started."""
    plan = data.plan
    standings = data.standings()
    bye_round = plan.rounds[index]
    next_round = plan.rounds[index + 1]
    skipped_to = plan.rounds[index + 2].name
    number = next_play_in_number(data.dropouts)
    play_in_key = play_in_game_key(plan, number) or ""
    play_in = Dropout(
        player_id,
        bye_round.name,
        DROP_PLAY_IN,
        game_key=play_in_key,
        player_name=name,
    )
    entrants = round_entrants(
        plan, standings, index + 1, dropped=dropped_ids(data.dropouts)
    )
    waiting = [
        p
        for p in entrants.players or ()
        if p not in standings[index + 1].scores and p != player_id
    ]
    promote_problem = ""
    names = data.names()
    promoted, promote_ties = promotion_choice(standings[index], waiting, data.tiebreaks)
    if not waiting:
        promote_problem = f"Everyone in the {next_round.name} has played."
    promoted = promoted or ""
    promoted_name = names.get(promoted) or promoted
    if promote_ties:
        tie = promote_ties[0]
        tied = ", ".join(names.get(p) or p for p in tie.players)
        promote_detail = (
            f"{tied} are tied at ${tie.score:,} as the best-ranked "
            f"{next_round.name} players who haven't played yet. A tiebreaker "
            f"between them decides who gets the bye to the {skipped_to}; the "
            f"next {bye_round.name} player takes the winner's "
            f"{next_round.name} seat."
        )
    else:
        promote_detail = (
            f"{promoted_name}, the best-ranked {next_round.name} player who "
            f"hasn't played yet (winners first), gets the bye to the "
            f"{skipped_to}. The next {bye_round.name} player takes their "
            f"{next_round.name} seat."
        )
    promote = Dropout(
        player_id,
        bye_round.name,
        DROP_PROMOTE,
        other_id=promoted,
        player_name=name,
    )
    options = (
        _option(
            data,
            play_in,
            "Add a play-in game",
            f"The next three {bye_round.name} players play "
            f"{play_in_key.split(': ', 1)[-1]} in the {next_round.name}. Its "
            f"winner takes {name}'s seat in the {skipped_to}. Set its board on "
            "the Games tab.",
        ),
        _option(
            data,
            promote,
            "Promote a waiting player",
            promote_detail if waiting else "",
            promote_problem,
        ),
    )
    return DropSituation(
        player_id,
        f"{name} has a bye to the {skipped_to}, and the {next_round.name} has started.",
        options,
    )


def _option(
    data: TournamentData,
    dropout: Dropout,
    label: str,
    detail: str,
    problem: str = "",
) -> DropOption:
    """Return an option, warning about played games it would no longer match."""
    if not problem:
        new = conflicts_added(data, apply_drop(data, dropout))
        if new:
            detail += " Warning: " + " ".join(new)
    return DropOption(dropout, label, detail, problem)


def conflicts_added(before: TournamentData, after: TournamentData) -> list[str]:
    """Return played games that match ``after``'s advancers but not ``before``'s.

    Args:
        before: The tournament now.
        after: The tournament after a change.

    Returns:
        The new conflict messages.
    """

    def conflicts(data: TournamentData) -> list[str]:
        """Return a tournament's conflicts, or none if its bracket doesn't work."""
        plan = data.plan
        if not plan.valid:
            return []
        return advancement_conflicts(
            plan, data.standings(), data.results, data.names(), data.dropouts
        )

    old = set(conflicts(before))
    return [message for message in conflicts(after) if message not in old]


def apply_drop(
    data: TournamentData,
    dropout: Dropout,
    new_player: PlayerSlot | None = None,
) -> TournamentData:
    """Return the tournament with ``dropout`` added.

    - :data:`DROP_REPLACE` adds ``new_player`` to the roster.
    - :data:`DROP_VOID` sets the voided game's results aside and retires
      its board, so the replay gets a new one.
    - Boards are reconciled with the new bracket, so a game that goes away
      gives its board back to unassigned.

    Args:
        data: The tournament.
        dropout: The dropout, from a :class:`DropOption`.
        new_player: The new player, for :data:`DROP_REPLACE`.

    Returns:
        The changed tournament.
    """
    slots = data.slots
    if dropout.choice == DROP_REPLACE and new_player is not None:
        slots = (*slots, new_player)
        dropout = replace(dropout, other_id=new_player.player_id)
    results = data.results
    voided = data.voided
    boards = dict(data.boards)
    retired = data.retired
    if dropout.choice == DROP_VOID:
        voided = voided + tuple(r for r in results if r.game_key == dropout.game_key)
        results = tuple(r for r in results if r.game_key != dropout.game_key)
        board = boards.pop(dropout.game_key, None)
        if board is not None:
            retired = (*retired, replace(board, left_game_key=dropout.game_key))
    changed = replace(
        data,
        slots=slots,
        results=results,
        dropouts=(*data.dropouts, dropout),
        voided=voided,
        boards=boards,
        retired=retired,
    )
    return _reconciled(changed)


def undo_problem(data: TournamentData, dropout: Dropout) -> str:
    """Return why ``dropout`` can't be taken back, or ``""``.

    A voided game that has been replayed can't be restored, and taking
    back a reduced field must still fit the games already played.

    Args:
        data: The tournament.
        dropout: One of ``data.dropouts``.

    Returns:
        A message for the host, or ``""``.
    """
    if dropout.choice == DROP_VOID and any(
        row.game_key == dropout.game_key for row in data.results
    ):
        game = dropout.game_key.split(": ", 1)[-1]
        return f"{game} has been played again, so it can't be restored."
    if dropout.choice == DROP_PLAY_IN and any(
        row.game_key == dropout.game_key for row in data.results
    ):
        game = dropout.game_key.split(": ", 1)[-1]
        return f"{game} has been played."
    after = undo_drop(data, dropout)
    plan = after.plan
    if not plan.valid:
        return f"The bracket wouldn't work: {plan.problems[0]}"
    keys = {key for key, _round, _game in plan_games(plan)}
    missing = sorted({row.game_key for row in after.results} - keys)
    if missing:
        games = ", ".join(key.split(": ", 1)[-1] for key in missing)
        return f"The bracket wouldn't have the games already played ({games})."
    return ""


def undo_drop(data: TournamentData, dropout: Dropout) -> TournamentData:
    """Return the tournament with ``dropout`` taken back.

    A voided game gets its results back, and its board if it has no new
    one. A replacement player stays on the roster; remove them on the
    Players tab if they're not needed.

    Args:
        data: The tournament.
        dropout: One of ``data.dropouts``.

    Returns:
        The changed tournament. Check :func:`undo_problem` first.
    """
    dropouts = tuple(d for d in data.dropouts if d != dropout)
    results = data.results
    voided = data.voided
    boards = dict(data.boards)
    retired = data.retired
    if dropout.choice == DROP_VOID:
        key = dropout.game_key
        results = results + tuple(r for r in voided if r.game_key == key)
        voided = tuple(r for r in voided if r.game_key != key)
        board = next((b for b in retired if b.left_game_key == key), None)
        if board is not None:
            retired = tuple(b for b in retired if b is not board)
            if key not in boards:
                boards[key] = replace(board, left_game_key="")
    changed = replace(
        data,
        results=results,
        dropouts=dropouts,
        voided=voided,
        boards=boards,
        retired=retired,
    )
    return _reconciled(changed)


def _reconciled(data: TournamentData) -> TournamentData:
    """Return ``data`` with boards matched to its bracket's games."""
    plan = data.plan
    if not plan.valid:
        return data
    keys = [key for key, _round, _game in plan_games(plan)]
    boards, unassigned = reconcile_boards(keys, data.boards, data.unassigned)
    return replace(data, boards=boards, unassigned=tuple(unassigned))


def dropout_text(dropout: Dropout, names: dict[str, str]) -> str:
    """Return a short description of a dropout, for the host.

    Args:
        dropout: The dropout.
        names: Display names by player id.

    Returns:
        Text such as ``"Ann: dropped out after the Quarterfinals"``.
    """
    name = names.get(dropout.player_id) or dropout.player_name or dropout.player_id
    other = names.get(dropout.other_id) or dropout.other_id
    game = dropout.game_key.split(": ", 1)[-1]
    if dropout.choice == DROP_REDUCE:
        what = "dropped out before playing; the field was reduced"
    elif dropout.choice == DROP_REPLACE:
        what = f"dropped out before playing; replaced by {other}"
    elif dropout.choice == DROP_SLIDE:
        what = f"dropped out after the {dropout.round_name}"
    elif dropout.choice == DROP_VOID:
        what = f"dropped out after winning {game}, which was voided"
    elif dropout.choice == DROP_PLAY_IN:
        what = f"gave up their bye; {game} fills the seat"
    else:
        what = f"gave up their bye; {other} was promoted"
    return f"{name}: {what}"
