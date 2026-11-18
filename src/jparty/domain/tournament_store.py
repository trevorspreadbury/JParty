"""Tournament folders on disk.

Each tournament lives in its own folder, ``<data dir>/tournaments/<name>/``,
outside git:

- ``tournament.json``: settings written by the app, such as the sign-up sheet
  link and the sign-ups the host chose to ignore.
- ``players.csv``: one row per player slot, in roster order, with the slot's
  Actual Name and its linked sign-up answers.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from jparty.domain.roster import ANECDOTE_COLUMNS, PlayerSlot, SignUp
from jparty.services.game_cache import write_text_atomic

TOURNAMENT_FILE = "tournament.json"
PLAYERS_FILE = "players.csv"
TOURNAMENT_FORMAT_VERSION = 1

PLAYERS_COLUMNS = (
    "actual_name",
    "timestamp",
    "full_name",
    "occupation",
    "hometown",
    *(f"anecdote_{number}" for number in range(1, len(ANECDOTE_COLUMNS) + 1)),
)

_FORBIDDEN_NAME_CHARACTERS = set('<>:"/\\|?*')
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
}


class TournamentFileError(ValueError):
    """Raised when a tournament folder is missing files or cannot be read."""


@dataclass
class TournamentSettings:
    """Settings saved in ``tournament.json``.

    Attributes:
        name: Tournament name, which is also its folder name.
        sheet_url: Link to the Google Form response sheet, or ``""``.
        ignored_sign_ups: Timestamps of sign-ups the host chose to ignore,
            so a refresh doesn't ask about them again.
    """

    name: str
    sheet_url: str = ""
    ignored_sign_ups: list[str] = field(default_factory=list)


def tournament_name_problem(name: str) -> str | None:
    """Return why ``name`` can't be a tournament folder name, or ``None``.

    Args:
        name: Proposed tournament name.

    Returns:
        A message for the host, or ``None`` if the name works.
    """
    if not name.strip():
        return "Enter a tournament name."
    if name != name.strip() or name.endswith("."):
        return "A tournament name can't start or end with a space or end with a dot."
    bad = sorted(_FORBIDDEN_NAME_CHARACTERS.intersection(name))
    if bad or not name.isprintable():
        shown = " ".join(bad) if bad else "control characters"
        return f"A tournament name can't contain {shown}."
    if name.split(".")[0].upper() in _RESERVED_WINDOWS_NAMES:
        return f'"{name}" is reserved by Windows. Choose another name.'
    return None


def list_tournaments(root: Path) -> list[str]:
    """Return the names of saved tournaments under ``root``, sorted.

    Only folders that have both ``tournament.json`` and ``players.csv`` count.

    Args:
        root: The tournaments folder.

    Returns:
        Tournament names.
    """
    if not root.is_dir():
        return []
    return sorted(
        (
            folder.name
            for folder in root.iterdir()
            if (folder / TOURNAMENT_FILE).is_file()
            and (folder / PLAYERS_FILE).is_file()
        ),
        key=str.casefold,
    )


def save_tournament(
    root: Path, settings: TournamentSettings, slots: Sequence[PlayerSlot]
) -> Path:
    """Write a tournament's settings and roster to its folder.

    Args:
        root: The tournaments folder.
        settings: Settings to save; ``settings.name`` names the folder.
        slots: Roster, in slot order.

    Returns:
        The tournament folder.

    Raises:
        TournamentFileError: If the name can't be used as a folder name.
    """
    problem = tournament_name_problem(settings.name)
    if problem:
        raise TournamentFileError(problem)
    folder = root / settings.name
    write_text_atomic(folder / PLAYERS_FILE, players_csv_text(slots))
    payload = {
        "format_version": TOURNAMENT_FORMAT_VERSION,
        "name": settings.name,
        "sheet_url": settings.sheet_url,
        "ignored_sign_ups": list(settings.ignored_sign_ups),
    }
    write_text_atomic(folder / TOURNAMENT_FILE, json.dumps(payload, indent=2) + "\n")
    return folder


def load_tournament(folder: Path) -> tuple[TournamentSettings, list[PlayerSlot]]:
    """Read a tournament's settings and roster from its folder.

    Args:
        folder: The tournament's folder.

    Returns:
        The settings and the roster.

    Raises:
        TournamentFileError: If a file is missing or can't be read.
    """
    settings_path = folder / TOURNAMENT_FILE
    players_path = folder / PLAYERS_FILE
    for path in (settings_path, players_path):
        if not path.is_file():
            raise TournamentFileError(f"{folder.name} has no {path.name}.")
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        players_text = players_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TournamentFileError(f"Couldn't read {folder.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TournamentFileError(f"{settings_path.name} is not a JSON object.")
    # The folder name wins over the saved "name". A copied or renamed folder
    # must save back into itself, not into the folder it was copied from.
    settings = TournamentSettings(
        name=folder.name,
        sheet_url=str(payload.get("sheet_url") or ""),
        ignored_sign_ups=[str(item) for item in payload.get("ignored_sign_ups", [])],
    )
    return settings, parse_players_csv(players_text)


def players_csv_text(slots: Sequence[PlayerSlot]) -> str:
    """Return ``players.csv`` contents for a roster.

    Args:
        slots: Roster, in slot order.

    Returns:
        CSV text with a header row and one row per slot.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(PLAYERS_COLUMNS)
    for slot in slots:
        sign_up = slot.sign_up
        if sign_up is None:
            writer.writerow([slot.actual_name] + [""] * (len(PLAYERS_COLUMNS) - 1))
            continue
        anecdotes = list(sign_up.anecdotes) + [""] * len(ANECDOTE_COLUMNS)
        writer.writerow(
            [
                slot.actual_name,
                sign_up.timestamp,
                sign_up.full_name,
                sign_up.occupation,
                sign_up.hometown,
                *anecdotes[: len(ANECDOTE_COLUMNS)],
            ]
        )
    return buffer.getvalue()


def parse_players_csv(text: str) -> list[PlayerSlot]:
    """Read a roster from ``players.csv`` contents.

    A row with a timestamp is linked to a sign-up. Missing columns read as
    blank, so a hand-made file with only ``actual_name`` works.

    Args:
        text: CSV text.

    Returns:
        The roster, in file order.

    Raises:
        TournamentFileError: If the file has no ``actual_name`` column.
    """
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        return []
    if "actual_name" not in reader.fieldnames:
        raise TournamentFileError(f"{PLAYERS_FILE} has no actual_name column.")
    slots = []
    for row in reader:

        def value(column: str, row: dict = row) -> str:
            """Return a row's cell for ``column``, or ``""``."""
            return (row.get(column) or "").strip()

        timestamp = value("timestamp")
        sign_up = None
        if timestamp:
            sign_up = SignUp(
                timestamp=timestamp,
                full_name=value("full_name"),
                occupation=value("occupation"),
                hometown=value("hometown"),
                anecdotes=tuple(
                    value(f"anecdote_{number}")
                    for number in range(1, len(ANECDOTE_COLUMNS) + 1)
                ),
            )
        slots.append(PlayerSlot(actual_name=value("actual_name"), sign_up=sign_up))
    return slots
