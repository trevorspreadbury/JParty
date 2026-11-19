"""What the host's phone page shows about a tournament's players.

The ``/host`` page (see :class:`jparty.web.handlers.HostHandler`) lets the
host pick a player on their phone, read their sign-up prompts, and see how
to introduce them. :func:`host_page` builds what it shows from the
tournament folder, so the page is always as fresh as the saved files.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from jparty.domain.tournament_advancement import player_statuses
from jparty.domain.tournament_play import introduction_line
from jparty.domain.tournament_store import TournamentFileError, load_tournament_data


@dataclass(frozen=True)
class HostPlayer:
    """One player, as the host's page shows them.

    Attributes:
        player_id: The player's id.
        name: Their Actual Name.
        introduction: How to introduce them, as the host screen does.
        status: Where they stand, such as ``"won, in the Semifinals"``, or
            ``""`` before they've played.
        prompts: Their sign-up anecdotes, without blank ones.
        on_stage: Whether they're playing the game in progress.
    """

    player_id: str
    name: str
    introduction: str
    status: str = ""
    prompts: tuple[str, ...] = ()
    on_stage: bool = False


@dataclass(frozen=True)
class HostPage:
    """Everything the host's page shows.

    Attributes:
        tournament: The tournament's name, or ``""`` if none is being played.
        players: Players on stage first, in podium order, then everyone
            else in roster order.
        problem: Why the tournament couldn't be shown, or ``""``.
    """

    tournament: str = ""
    players: tuple[HostPlayer, ...] = field(default_factory=tuple)
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
        _settings, data = load_tournament_data(folder)
    except TournamentFileError as exc:
        return HostPage(folder.name, problem=f"Couldn't read the tournament: {exc}")
    statuses = {}
    plan = data.plan
    if plan.valid:
        statuses = player_statuses(plan, data.standings(), data.dropouts)
    stage = [player_id for player_id in on_stage if player_id]
    players = []
    for slot in data.slots:
        name = slot.actual_name.strip()
        if not name:
            continue
        prompts = ()
        if slot.sign_up is not None:
            prompts = tuple(text for text in slot.sign_up.anecdotes if text.strip())
        players.append(
            HostPlayer(
                slot.player_id,
                name,
                introduction_line(slot),
                statuses.get(slot.player_id, ("", False))[0],
                prompts,
                slot.player_id in stage,
            )
        )
    players.sort(
        key=lambda player: (
            stage.index(player.player_id) if player.on_stage else len(stage)
        )
    )
    return HostPage(folder.name, tuple(players))
