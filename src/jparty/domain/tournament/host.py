"""What the host's phone page shows about a tournament's players.

The ``/host`` page (see :class:`jparty.web.handlers.HostHandler`) shows the
host one player at a time: their name, how to introduce them, and their
sign-up prompts. During a game it steps through that game's players in
reverse seat order (the last podium first, the order a host introduces
them); otherwise it steps through the roster. The host ticks a prompt once
they've used it, and it stays ticked for the rest of the tournament
(``used_prompts.csv``).

:func:`host_page` builds the page from the tournament folder, so it's always
as fresh as the saved files.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from jparty.domain.tournament.play import introduction_line
from jparty.domain.tournament.store import (
    TournamentFileError,
    load_tournament,
    load_used_prompts,
    set_prompt_used,
)


@dataclass(frozen=True)
class HostPrompt:
    """One of a player's sign-up prompts.

    Attributes:
        number: Which anecdote it is, from 1.
        text: The prompt.
        used: Whether the host has ticked it as used.
    """

    number: int
    text: str
    used: bool = False


@dataclass(frozen=True)
class HostPlayer:
    """One player, as the host's page shows them.

    Attributes:
        player_id: The player's id.
        name: Their Actual Name.
        introduction: How to introduce them, as the host screen does.
        prompts: Their sign-up prompts, without blank ones.
        seat: Their podium, from 1, if they're in the game in progress.
    """

    player_id: str
    name: str
    introduction: str
    prompts: tuple[HostPrompt, ...] = ()
    seat: int | None = None


@dataclass(frozen=True)
class HostPage:
    """Everything the host's page shows.

    Attributes:
        tournament: The tournament's name, or ``""`` if none is being played.
        players: The players to step through: the game in progress's
            players in reverse seat order, or else everyone in roster order.
        in_game: Whether :attr:`players` are a game's players.
        problem: Why the tournament couldn't be shown, or ``""``.
    """

    tournament: str = ""
    players: tuple[HostPlayer, ...] = field(default_factory=tuple)
    in_game: bool = False
    problem: str = ""


def host_page(folder: Path | None, on_stage: Sequence[str] = ()) -> HostPage:
    """Return what the host's page shows for the tournament in ``folder``.

    Args:
        folder: The tournament's folder, or ``None`` when no tournament is
            being played.
        on_stage: Ids of the players in the game in progress, in podium
            order.

    Returns:
        The page. Players with no name are left out.
    """
    if folder is None:
        return HostPage()
    folder = Path(folder)
    try:
        _settings, slots = load_tournament(folder)
        used = {
            (player_id, number)
            for player_id, number, _text in load_used_prompts(folder)
        }
    except TournamentFileError as exc:
        return HostPage(folder.name, problem=f"Couldn't read the tournament: {exc}")
    seats = {player_id: seat for seat, player_id in enumerate(on_stage, 1) if player_id}
    players = []
    for slot in slots:
        name = slot.actual_name.strip()
        if not name:
            continue
        prompts = ()
        if slot.sign_up is not None:
            prompts = tuple(
                HostPrompt(number, text.strip(), (slot.player_id, number) in used)
                for number, text in enumerate(slot.sign_up.anecdotes, 1)
                if text.strip()
            )
        players.append(
            HostPlayer(
                slot.player_id,
                name,
                introduction_line(slot),
                prompts,
                seats.get(slot.player_id),
            )
        )
    stage = [player for player in players if player.seat is not None]
    if stage:
        stage.sort(key=lambda player: -player.seat)
        return HostPage(folder.name, tuple(stage), in_game=True)
    return HostPage(folder.name, tuple(players))


def mark_prompt(folder: Path | None, player_id: str, number: int, used: bool) -> str:
    """Tick or untick one of a player's prompts as used, and save it.

    Args:
        folder: The tournament's folder, or ``None``.
        player_id: The player.
        number: The prompt's number, from 1.
        used: Whether it's used.

    Returns:
        Why it couldn't be saved, or ``""``.
    """
    if folder is None:
        return "No tournament is being played."
    try:
        _settings, slots = load_tournament(Path(folder))
        slot = next((s for s in slots if s.player_id == player_id), None)
        anecdotes = slot.sign_up.anecdotes if slot and slot.sign_up else ()
        if not 1 <= number <= len(anecdotes) or not anecdotes[number - 1].strip():
            return "That player has no such prompt."
        set_prompt_used(
            Path(folder), player_id, number, anecdotes[number - 1].strip(), used
        )
    except TournamentFileError as exc:
        return str(exc)
    return ""
