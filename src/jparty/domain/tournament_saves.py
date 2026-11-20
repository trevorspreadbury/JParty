"""Finding the saved games of a tournament's half-played games.

Every game saves itself to its own folder in the saved games folder, named
``<game id>-<YYYYMMDDTHHMM>`` (with ``-2``, ``-3``, ... for a second start
in the same minute). A tournament game's ``general.json`` also names its
tournament and bracket game (see
:class:`jparty.domain.tournament_play.TournamentGameRef`), so a game that
stopped part way, for example because the app closed, can be resumed from
the tournament.

Only folders named for a board's game id are read, so looking is quick even
with many saved games.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jparty.domain.tournament_play import (
    SAVED_PLAYER_ID,
    SAVED_PLAYER_NAME,
    TournamentGameRef,
)

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
        players, player_ids = _saved_players(state)
        if not players:
            continue
        try:
            last_updated = float(state.get("last_updated") or 0)
        except (TypeError, ValueError):
            last_updated = 0.0
        save = TournamentSave(ref.game_key, folder, last_updated, players, player_ids)
        current = saves.get(ref.game_key)
        if current is None or (save.last_updated, save.path.name) > (
            current.last_updated,
            current.path.name,
        ):
            saves[ref.game_key] = save
    return saves
