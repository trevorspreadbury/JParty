"""Finding the saved games of a tournament's half-played games.

Every game saves itself to its own folder in the saved games folder, named
``<game id>-<YYYYMMDDTHHMM>`` (with ``-2``, ``-3``, ... for a second start
in the same minute). A tournament game's ``general.json`` also names its
tournament and bracket game (see
:class:`jparty.domain.tournament.play.TournamentGameRef`), so a game that
stopped part way, for example because the app closed, can be resumed from
the tournament.

Only folders named for a board's game id are read, so looking is quick even
with many saved games.

:func:`resume_problem` says whether a save can still be resumed as a
tournament game, whether it is resumed from the tournament or with the
regular Load Saved button.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from jparty.domain.tournament.advancement import Eligibility, eligible_players
from jparty.domain.tournament.dropouts import Dropout, dropped_ids
from jparty.domain.tournament.play import (
    SAVED_PLAYER_ID,
    SAVED_PLAYER_NAME,
    GameResult,
    TournamentGameRef,
)
from jparty.domain.tournament.store import TournamentFileError, load_tournament_data

GENERAL_FILE = "general.json"
# A saved game's folder name: its game id, then when it started.
_SAVE_FOLDER = re.compile(r"(?P<game_id>.+)-\d{8}T\d{4}(?:-\d+)?")


@dataclass(frozen=True)
class TournamentSave:
    """A saved game of one tournament game.

    Attributes:
        game_key: The bracket game.
        path: The saved game's folder.
        last_updated: When the save last changed, in seconds since the epoch.
        players: The saved players' names, in podium order.
        player_ids: The saved players' tournament player ids, in podium
            order; ``""`` for a player saved without one.
    """

    game_key: str
    path: Path
    last_updated: float
    players: tuple[str, ...] = ()
    player_ids: tuple[str, ...] = ()


def _read_save(folder: Path) -> dict | None:
    """Return a saved game's ``general.json``, or ``None`` if unreadable."""
    try:
        with (folder / GENERAL_FILE).open(encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, ValueError) as exc:
        logging.debug("Skipping saved game %s: %s", folder, exc)
        return None
    return state if isinstance(state, dict) else None


def _saved_players(state: Mapping) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the saved players' names (tournament names first) and ids."""
    names, ids = [], []
    for player in state.get("players") or []:
        if not isinstance(player, Mapping):
            continue
        name = player.get(SAVED_PLAYER_NAME) or player.get("name") or ""
        names.append(str(name))
        ids.append(str(player.get(SAVED_PLAYER_ID) or ""))
    return tuple(names), tuple(ids)


def find_tournament_saves(
    states_dir: Path, tournament: str, game_ids: Mapping[str, str]
) -> dict[str, TournamentSave]:
    """Return the newest save of each tournament game that has one.

    Args:
        states_dir: The saved games folder.
        tournament: The tournament's name.
        game_ids: Each game's board's game id (the saved folder's prefix),
            by game key. Games left out aren't looked for.

    Returns:
        The newest save with players, by game key.
    """
    wanted = {game_id: [] for game_id in game_ids.values() if game_id}
    for game_key, game_id in game_ids.items():
        if game_id:
            wanted[game_id].append(game_key)
    if not wanted:
        return {}
    try:
        folders = [path for path in Path(states_dir).iterdir() if path.is_dir()]
    except OSError:
        return {}
    saves: dict[str, TournamentSave] = {}
    for folder in folders:
        match = _SAVE_FOLDER.fullmatch(folder.name)
        game_id = match["game_id"] if match else ""
        if game_id not in wanted:
            continue
        state = _read_save(folder)
        if state is None or str(state.get("game_id", "")).strip() != game_id:
            continue
        ref = TournamentGameRef.from_json(state.get("tournament"))
        if ref is None or ref.tournament != tournament:
            continue
        if ref.game_key not in wanted[game_id]:
            continue
        save = tournament_save(folder, state)
        if save is None or not save.players:
            continue
        current = saves.get(ref.game_key)
        if current is None or (save.last_updated, save.path.name) > (
            current.last_updated,
            current.path.name,
        ):
            saves[ref.game_key] = save
    return saves


def tournament_save(folder: Path, state: Mapping) -> TournamentSave | None:
    """Return the save in ``folder`` as a :class:`TournamentSave`.

    Args:
        folder: The saved game's folder.
        state: Its decoded ``general.json``.

    Returns:
        The save, or ``None`` if it isn't a tournament game.
    """
    ref = TournamentGameRef.from_json(state.get("tournament"))
    if ref is None:
        return None
    players, player_ids = _saved_players(state)
    try:
        last_updated = float(state.get("last_updated") or 0)
    except (TypeError, ValueError):
        last_updated = 0.0
    return TournamentSave(ref.game_key, Path(folder), last_updated, players, player_ids)


def resume_problem(
    save: TournamentSave,
    eligibility: Eligibility,
    dropouts: Sequence[Dropout],
    names: Mapping[str, str],
    results: Sequence[GameResult] = (),
) -> str | None:
    """Return why ``save`` can't be resumed as a tournament game, or ``None``.

    A save can't be resumed once one of its players has dropped out or can
    no longer play the game, or once the game has results from a different
    save, since resuming would log results over them. A save whose own
    results are already logged can be resumed: it ends again and leaves
    them alone.

    Args:
        save: The save.
        eligibility: Who may sit in the save's game now.
        dropouts: Every dropout.
        names: Display names by player id.
        results: Every saved result.

    Returns:
        A message for the host, or ``None``.
    """
    sources = {r.saved_game for r in results if r.game_key == save.game_key}
    if save.path.name in sources:
        return None
    if sources:
        return (
            f"{save.game_key} already has results from another saved game "
            f"({', '.join(sorted(sources))}), so this save can't be resumed. "
            "Delete those results with Fix Results first to replay it."
        )
    players = [
        (player_id, names.get(player_id) or name)
        for player_id, name in zip(save.player_ids, save.players, strict=False)
    ]
    if len(players) != len(save.players) or not all(p for p, _ in players):
        return "This save doesn't say which tournament players it has."
    dropped = dropped_ids(dropouts)
    gone = [name for player_id, name in players if player_id in dropped]
    if gone:
        return (
            f"{', '.join(gone)} dropped out, so this game can't be resumed. "
            "Start it again with new players, or undo the drop."
        )
    if eligibility.waiting:
        return eligibility.waiting
    allowed = set(eligibility.player_ids)
    barred = [name for player_id, name in players if player_id not in allowed]
    if barred:
        return (
            f"{', '.join(barred)} can no longer play {save.game_key}, so this "
            "game can't be resumed. Start it again with new players."
        )
    return None


def saved_game_problem(folder: Path, save: TournamentSave) -> str | None:
    """Check ``save`` against its tournament's files, as :func:`resume_problem`.

    This is for the regular Load Saved button, which doesn't have the
    tournament open. A tournament whose files can't be read isn't checked:
    logging its results fails later with a warning anyway.

    Args:
        folder: The save's tournament's folder.
        save: The save.

    Returns:
        A message for the host, or ``None``.
    """
    try:
        settings, data = load_tournament_data(Path(folder))
    except TournamentFileError as exc:
        logging.warning("Couldn't check %s against its tournament: %s", save.path, exc)
        return None
    eligibility = eligible_players(
        data.plan,
        save.game_key,
        data.slots,
        data.results,
        settings.boards.get(save.game_key),
        data.tiebreaks,
        data.dropouts,
    )
    return resume_problem(save, eligibility, data.dropouts, data.names(), data.results)
