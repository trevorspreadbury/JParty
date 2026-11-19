"""Tournament folders on disk.

Each tournament lives in its own folder, ``<data dir>/tournaments/<name>/``,
outside git:

- ``tournament.json``: settings written by the app: the sign-up sheet link,
  the sign-ups the host chose to ignore, the bracket format, each game's
  board, boards not assigned to a game, and the logo's file name.
- ``players.csv``: one row per player slot, in roster order, with the slot's
  Actual Name, its linked sign-up answers, and a stable player id.
- ``logo.<ext>``: the tournament logo, if the host chose one. It lives here,
  not in git.

Format version 1 files (from before the setup screen) load with the default
bracket and no boards.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from jparty.domain.roster import ANECDOTE_COLUMNS, PlayerSlot, SignUp, new_player_id
from jparty.domain.tournament_setup import BracketSettings, TournamentBoard
from jparty.services.game_cache import write_text_atomic

TOURNAMENT_FILE = "tournament.json"
PLAYERS_FILE = "players.csv"
TOURNAMENT_FORMAT_VERSION = 2
LOGO_STEM = "logo"
LOGO_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")

PLAYERS_COLUMNS = (
    "actual_name",
    "timestamp",
    "full_name",
    "occupation",
    "hometown",
    *(f"anecdote_{number}" for number in range(1, len(ANECDOTE_COLUMNS) + 1)),
    "player_id",
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
        bracket: Bracket format options; the roster sets the player count.
        boards: Board for each game, keyed by
            :func:`jparty.domain.tournament_setup.game_key`.
        unassigned_boards: Boards not assigned to any game.
        logo_file: File name of the logo in the tournament folder, or ``""``.
    """

    name: str
    sheet_url: str = ""
    ignored_sign_ups: list[str] = field(default_factory=list)
    bracket: BracketSettings = field(default_factory=BracketSettings)
    boards: dict[str, TournamentBoard] = field(default_factory=dict)
    unassigned_boards: list[TournamentBoard] = field(default_factory=list)
    logo_file: str = ""


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


def logo_problem(path: Path) -> str | None:
    """Return why ``path`` can't be used as a logo, or ``None``.

    Args:
        path: Image file the host picked.

    Returns:
        A message for the host, or ``None`` if the file works.
    """
    path = Path(path)
    if path.suffix.lower() not in LOGO_SUFFIXES:
        return "Choose a PNG, JPEG, GIF, BMP, or WebP image for the logo."
    if not path.is_file():
        return f"Couldn't find {path.name}."
    return None


def save_tournament(
    root: Path,
    settings: TournamentSettings,
    slots: Sequence[PlayerSlot],
    logo_source: Path | None = None,
) -> Path:
    """Write a tournament's settings, roster, and logo to its folder.

    Args:
        root: The tournaments folder.
        settings: Settings to save; ``settings.name`` names the folder.
            When ``logo_source`` is given, ``settings.logo_file`` is set to
            the copied logo's name. Logo files other than
            ``settings.logo_file`` are removed, so clearing ``logo_file``
            removes the logo.
        slots: Roster, in slot order.
        logo_source: A new logo image to copy into the folder, or ``None``.

    Returns:
        The tournament folder.

    Raises:
        TournamentFileError: If the name can't be used as a folder name, or
            ``logo_source`` isn't a usable image.
    """
    problem = tournament_name_problem(settings.name)
    if problem is None and logo_source is not None:
        problem = logo_problem(logo_source)
    if problem:
        raise TournamentFileError(problem)
    folder = root / settings.name
    folder.mkdir(parents=True, exist_ok=True)
    if logo_source is not None:
        logo_name = LOGO_STEM + Path(logo_source).suffix.lower()
        _copy_file_atomic(Path(logo_source), folder / logo_name)
        settings.logo_file = logo_name
    write_text_atomic(folder / PLAYERS_FILE, players_csv_text(slots))
    payload = {
        "format_version": TOURNAMENT_FORMAT_VERSION,
        "name": settings.name,
        "sheet_url": settings.sheet_url,
        "ignored_sign_ups": list(settings.ignored_sign_ups),
        "bracket": settings.bracket.to_json(),
        "boards": {key: board.to_json() for key, board in settings.boards.items()},
        "unassigned_boards": [board.to_json() for board in settings.unassigned_boards],
        "logo_file": settings.logo_file,
    }
    write_text_atomic(folder / TOURNAMENT_FILE, json.dumps(payload, indent=2) + "\n")
    _remove_other_logos(folder, settings.logo_file)
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
    boards = {}
    boards_payload = payload.get("boards")
    if isinstance(boards_payload, dict):
        for key, board_payload in boards_payload.items():
            board = TournamentBoard.from_json(board_payload)
            if board is not None:
                boards[str(key)] = board
    unassigned_payload = payload.get("unassigned_boards")
    if not isinstance(unassigned_payload, list):
        unassigned_payload = []
    unassigned = [
        board
        for board in map(TournamentBoard.from_json, unassigned_payload)
        if board is not None
    ]
    logo_file = str(payload.get("logo_file") or "")
    if logo_file and not (folder / logo_file).is_file():
        # A missing logo shouldn't stop the tournament from loading.
        logo_file = ""
    settings = TournamentSettings(
        name=folder.name,
        sheet_url=str(payload.get("sheet_url") or ""),
        ignored_sign_ups=[str(item) for item in payload.get("ignored_sign_ups", [])],
        bracket=BracketSettings.from_json(payload.get("bracket")),
        boards=boards,
        unassigned_boards=unassigned,
        logo_file=logo_file,
    )
    return settings, parse_players_csv(players_text)


def _copy_file_atomic(source: Path, destination: Path) -> None:
    """Copy ``source`` over ``destination`` so readers never see a partial file."""
    fd, temp_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    os.close(fd)
    try:
        shutil.copyfile(source, temp_name)
        Path(temp_name).replace(destination)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _remove_other_logos(folder: Path, keep: str) -> None:
    """Delete logo files in ``folder`` other than ``keep``."""
    for suffix in LOGO_SUFFIXES:
        path = folder / f"{LOGO_STEM}{suffix}"
        if path.name != keep and path.is_file():
            path.unlink()


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
            sign_up_cells = [""] * (len(PLAYERS_COLUMNS) - 2)
        else:
            anecdotes = list(sign_up.anecdotes) + [""] * len(ANECDOTE_COLUMNS)
            sign_up_cells = [
                sign_up.timestamp,
                sign_up.full_name,
                sign_up.occupation,
                sign_up.hometown,
                *anecdotes[: len(ANECDOTE_COLUMNS)],
            ]
        writer.writerow([slot.actual_name, *sign_up_cells, slot.player_id])
    return buffer.getvalue()


def parse_players_csv(text: str) -> list[PlayerSlot]:
    """Read a roster from ``players.csv`` contents.

    A row with a timestamp is linked to a sign-up. Missing columns read as
    blank, so a hand-made file with only ``actual_name`` works. A row with no
    ``player_id`` (or one already used above it, as in a copied row) gets a
    new id, which is saved on the next save.

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
    seen_ids: set[str] = set()
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
        player_id = value("player_id")
        if not player_id or player_id in seen_ids:
            player_id = new_player_id()
        seen_ids.add(player_id)
        slots.append(
            PlayerSlot(
                actual_name=value("actual_name"),
                sign_up=sign_up,
                player_id=player_id,
            )
        )
    return slots
