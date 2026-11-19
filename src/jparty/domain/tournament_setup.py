"""Tournament setup: the bracket format and which board each game plays.

The roster sets the player count. :class:`BracketSettings` holds the rest of
the bracket designer's options. Each bracket game gets a
:class:`TournamentBoard`, which is the same list of ``board_selections`` the
welcome screen builds for a regular or Frankenstein game. Boards whose game
leaves the bracket (for example when the field shrinks) go to an unassigned
pool instead of being lost.

These are pure functions over plain data, so the setup screen and later
tournament steps share one set of rules.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace

from jparty.domain.tournament import (
    BracketGame,
    BracketRound,
    TournamentOptions,
    TournamentPlan,
)


@dataclass(frozen=True)
class BracketSettings:
    """Bracket options saved with a tournament, apart from the player count.

    Attributes:
        use_second_round: Whether to add a round before the Semifinals.
        semifinal_byes: Top preliminary players who skip the second round.
        second_round_players: Second-round field size, or ``None`` for the
            designer's default.
    """

    use_second_round: bool = False
    semifinal_byes: int = 0
    second_round_players: int | None = None

    def options(self, player_count: int) -> TournamentOptions:
        """Return planner options for a roster of ``player_count`` players.

        Args:
            player_count: Players on the roster.

        Returns:
            Options for :func:`jparty.domain.tournament.plan_tournament`.
        """
        return TournamentOptions(
            player_count=player_count,
            use_second_round=self.use_second_round,
            semifinal_byes=self.semifinal_byes,
            second_round_players=self.second_round_players,
        )

    def to_json(self) -> dict:
        """Return the settings as a JSON-ready dictionary."""
        return {
            "use_second_round": self.use_second_round,
            "semifinal_byes": self.semifinal_byes,
            "second_round_players": self.second_round_players,
        }

    @classmethod
    def from_json(cls, payload: object) -> BracketSettings:
        """Read settings saved by :meth:`to_json`; bad values use defaults.

        Args:
            payload: The saved dictionary, or anything else for defaults.

        Returns:
            The settings.
        """
        if not isinstance(payload, Mapping):
            return cls()
        second_round_players = payload.get("second_round_players")
        return cls(
            use_second_round=bool(payload.get("use_second_round", False)),
            semifinal_byes=_int_or(payload.get("semifinal_byes"), 0),
            second_round_players=(
                None
                if second_round_players is None
                else _int_or(second_round_players, None)
            ),
        )


@dataclass(frozen=True)
class TournamentBoard:
    """The board one tournament game plays.

    Attributes:
        label: Short description shown to the host.
        board_selections: ``board_selections`` entries, as saved in a game's
            ``general.json``. Each names its source game id and round.
        cant_play: Player ids of players who must not play this board, for
            example because they have seen it. They stay with the board when
            it is swapped, unassigned, or edited.
    """

    label: str
    board_selections: tuple[dict, ...] = field(default_factory=tuple)
    cant_play: tuple[str, ...] = ()

    @property
    def source_game_ids(self) -> tuple[str, ...]:
        """Return the source game ids this board uses, in order, once each."""
        ids: list[str] = []
        for selection in self.board_selections:
            game_id = str(selection.get("game_id", "")).strip()
            if game_id and game_id not in ids:
                ids.append(game_id)
        return tuple(ids)

    @property
    def source_rounds(self) -> frozenset[tuple[str, int]]:
        """Return the ``(game id, round index)`` pairs this board plays."""
        return frozenset(
            (
                str(selection.get("game_id", "")).strip(),
                _int_or(selection.get("source_round_index"), -1),
            )
            for selection in self.board_selections
        )

    def to_json(self) -> dict:
        """Return the board as a JSON-ready dictionary."""
        return {
            "label": self.label,
            "board_selections": deepcopy(list(self.board_selections)),
            "cant_play": list(self.cant_play),
        }

    @classmethod
    def from_json(cls, payload: object) -> TournamentBoard | None:
        """Read a board saved by :meth:`to_json`.

        Args:
            payload: The saved dictionary.

        Returns:
            The board, or ``None`` if ``payload`` has no usable selections.
        """
        if not isinstance(payload, Mapping):
            return None
        selections = payload.get("board_selections")
        if not isinstance(selections, list):
            return None
        selections = [dict(item) for item in selections if isinstance(item, Mapping)]
        if not selections:
            return None
        cant_play = payload.get("cant_play")
        if not isinstance(cant_play, list):
            cant_play = []
        return cls(
            str(payload.get("label") or ""),
            tuple(selections),
            tuple(dict.fromkeys(str(player_id) for player_id in cant_play)),
        )


def board_from_selections(
    session_game_id: str, board_selections: Sequence[Mapping]
) -> TournamentBoard | None:
    """Return a tournament board for a welcome-screen board setup.

    Args:
        session_game_id: The game's id, or ``frankenstein-...`` for a board
            built from several games.
        board_selections: The welcome screen's ``board_selections``.

    Returns:
        The board, or ``None`` when no board is set up.
    """
    selections = tuple(deepcopy(dict(item)) for item in board_selections)
    if not selections:
        return None
    ids = {str(selection.get("game_id", "")).strip() for selection in selections}
    if len(ids) == 1:
        rounds = ", ".join(
            str(selection.get("source_round_label", "")) for selection in selections
        )
        label = f"{session_game_id} ({rounds})"
    else:
        label = " + ".join(
            f"{selection.get('game_id', '')} {selection.get('source_round_label', '')}"
            for selection in selections
        )
    return TournamentBoard(label, selections)


def game_key(bracket_round: BracketRound, game: BracketGame) -> str:
    """Return the id a game's board is saved under, such as ``"Final: Final"``.

    Game names repeat across rounds (each round can have a ``"Chase 1"``), so
    the key includes the round.

    Args:
        bracket_round: The round the game is in.
        game: The game.

    Returns:
        ``"<round name>: <game name>"``.
    """
    return f"{bracket_round.name}: {game.name}"


def plan_games(plan: TournamentPlan) -> list[tuple[str, BracketRound, BracketGame]]:
    """Return every game in a plan with its key, in playing order.

    Args:
        plan: A planned bracket.

    Returns:
        ``(key, round, game)`` for each game; empty for an invalid plan.
    """
    return [
        (game_key(bracket_round, game), bracket_round, game)
        for bracket_round in plan.rounds
        for game in bracket_round.games
    ]


def reconcile_boards(
    game_keys: Sequence[str],
    boards: Mapping[str, TournamentBoard],
    unassigned: Sequence[TournamentBoard],
) -> tuple[dict[str, TournamentBoard], list[TournamentBoard]]:
    """Move boards whose game is no longer in the bracket to the pool.

    Args:
        game_keys: Keys of the games in the current bracket.
        boards: Boards by game key.
        unassigned: Boards not assigned to any game.

    Returns:
        The boards still assigned, and the pool with dropped boards appended
        in playing order.
    """
    keys = set(game_keys)
    kept = {key: board for key, board in boards.items() if key in keys}
    dropped = [board for key, board in boards.items() if key not in keys]
    return kept, list(unassigned) + dropped


def assign_board(
    boards: Mapping[str, TournamentBoard],
    unassigned: Sequence[TournamentBoard],
    key: str,
    board: TournamentBoard,
) -> tuple[dict[str, TournamentBoard], list[TournamentBoard]]:
    """Give ``board`` to a game; the game's previous board goes to the pool.

    Args:
        boards: Boards by game key.
        unassigned: Boards not assigned to any game.
        key: Game to assign to.
        board: Board to assign.

    Returns:
        The new assignments and pool.
    """
    new_boards = dict(boards)
    pool = list(unassigned)
    previous = new_boards.get(key)
    if previous is not None:
        pool.append(previous)
    new_boards[key] = board
    return new_boards, pool


def assign_from_pool(
    boards: Mapping[str, TournamentBoard],
    unassigned: Sequence[TournamentBoard],
    pool_index: int,
    key: str,
) -> tuple[dict[str, TournamentBoard], list[TournamentBoard]]:
    """Move a board from the pool to a game, swapping out any board it had.

    Args:
        boards: Boards by game key.
        unassigned: Boards not assigned to any game.
        pool_index: Index of the board in ``unassigned``.
        key: Game to assign to.

    Returns:
        The new assignments and pool.
    """
    pool = list(unassigned)
    board = pool.pop(pool_index)
    return assign_board(boards, pool, key, board)


def unassign_board(
    boards: Mapping[str, TournamentBoard],
    unassigned: Sequence[TournamentBoard],
    key: str,
) -> tuple[dict[str, TournamentBoard], list[TournamentBoard]]:
    """Move a game's board to the pool.

    Args:
        boards: Boards by game key.
        unassigned: Boards not assigned to any game.
        key: Game whose board to remove.

    Returns:
        The new assignments and pool. Unchanged if the game had no board.
    """
    new_boards = dict(boards)
    pool = list(unassigned)
    board = new_boards.pop(key, None)
    if board is not None:
        pool.append(board)
    return new_boards, pool


def swap_boards(
    boards: Mapping[str, TournamentBoard], first: str, second: str
) -> dict[str, TournamentBoard]:
    """Swap two games' boards. A game without a board takes the other's.

    Args:
        boards: Boards by game key.
        first: One game's key.
        second: The other game's key.

    Returns:
        The new assignments.
    """
    new_boards = dict(boards)
    first_board = new_boards.pop(first, None)
    second_board = new_boards.pop(second, None)
    if second_board is not None:
        new_boards[first] = second_board
    if first_board is not None:
        new_boards[second] = first_board
    return new_boards


def with_cant_play(
    board: TournamentBoard, player_ids: Sequence[str]
) -> TournamentBoard:
    """Return ``board`` with ``player_ids`` as the players who can't play it.

    Args:
        board: A tournament board.
        player_ids: Player ids, in the order to keep; repeats are dropped.

    Returns:
        The updated board.
    """
    return replace(board, cant_play=tuple(dict.fromkeys(player_ids)))


def edited_board(
    previous: TournamentBoard | None, edited: TournamentBoard
) -> TournamentBoard:
    """Return an edited board that keeps who can't play the previous one.

    Editing a board's rounds doesn't change who has seen or written it, so
    the exclusions carry over.

    Args:
        previous: The board before editing, or ``None`` for a new board.
        edited: The board as the host set it up.

    Returns:
        ``edited`` with the previous board's exclusions.
    """
    if previous is None:
        return edited
    return with_cant_play(edited, previous.cant_play)


def forget_removed_players(
    boards: Mapping[str, TournamentBoard],
    unassigned: Sequence[TournamentBoard],
    player_ids: Iterable[str],
) -> tuple[dict[str, TournamentBoard], list[TournamentBoard]]:
    """Drop exclusions for players no longer on the roster.

    Args:
        boards: Boards by game key.
        unassigned: Boards not assigned to any game.
        player_ids: Ids of the players on the roster.

    Returns:
        The boards and pool, with only current players in ``cant_play``.
    """
    current = set(player_ids)

    def keep_current(board: TournamentBoard) -> TournamentBoard:
        """Return ``board`` without exclusions for removed players."""
        kept = [player_id for player_id in board.cant_play if player_id in current]
        return (
            board if len(kept) == len(board.cant_play) else with_cant_play(board, kept)
        )

    return (
        {key: keep_current(board) for key, board in boards.items()},
        [keep_current(board) for board in unassigned],
    )


def shared_board_warnings(
    game_keys: Sequence[str], boards: Mapping[str, TournamentBoard]
) -> list[str]:
    """Return a warning for each pair of games that play the same round.

    Players who meet a round twice would already know its answers.

    Args:
        game_keys: Keys of the games in the current bracket, in order.
        boards: Boards by game key.

    Returns:
        One message per pair, in playing order.
    """
    assigned = [(key, boards[key]) for key in game_keys if key in boards]
    warnings = []
    for index, (key, board) in enumerate(assigned):
        for other_key, other in assigned[index + 1 :]:
            if board.source_rounds & other.source_rounds:
                warnings.append(f"{key} and {other_key} share a round.")
    return warnings


def _int_or(value: object, default: int | None) -> int | None:
    """Return ``value`` as an int, or ``default`` if it isn't one."""
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
