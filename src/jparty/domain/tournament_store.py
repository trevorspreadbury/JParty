"""Tournament folders on disk.

Each tournament lives in its own folder, ``<data dir>/tournaments/<name>/``,
outside git:

- ``tournament.json``: settings written by the app: the sign-up sheet link,
  the sign-ups the host chose to ignore, the bracket format, each game's
  board, boards not assigned to a game, boards of voided games (retired,
  so they aren't played again), and the logo's file name.
- ``players.csv``: one row per player slot, in roster order, with the slot's
  Actual Name, its linked sign-up answers, and a stable player id.
- ``logo.<ext>``: the tournament logo, if the host chose one. It lives here,
  not in git.
- ``results.csv``: one row per player per played game (see
  :class:`jparty.domain.tournament_play.GameResult`). Games write it when
  they end, and the host can fix it afterwards. It is separate from
  ``tournament.json``, so saving the setup never touches results.
- ``tiebreaks.csv``: one row per tiebreaker played to settle a tie for a
  wildcard, chaser, or bye (see
  :class:`jparty.domain.tournament_advancement.Tiebreak`).
- ``dropouts.csv``: one row per player who dropped out, and what the host
  chose to do (see :class:`jparty.domain.tournament_dropouts.Dropout`).
- ``voided_results.csv``: results of Semifinals voided because their
  winner dropped out, in the same columns as ``results.csv``. They're kept
  for the record and never counted.
- ``used_prompts.csv``: the sign-up prompts the host has used, ticked on
  the ``/host`` phone page, so they stay marked for the rest of the
  tournament.

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
from dataclasses import dataclass, field, replace
from pathlib import Path

from jparty.domain.roster import ANECDOTE_COLUMNS, PlayerSlot, SignUp, new_player_id
from jparty.domain.tournament_advancement import Tiebreak
from jparty.domain.tournament_drop_choices import TournamentData
from jparty.domain.tournament_dropouts import DROP_CHOICES, Dropout
from jparty.domain.tournament_play import RESULTS, GameResult, record_results
from jparty.domain.tournament_setup import BracketSettings, TournamentBoard
from jparty.services.game_cache import write_text_atomic

TOURNAMENT_FILE = "tournament.json"
PLAYERS_FILE = "players.csv"
RESULTS_FILE = "results.csv"
TIEBREAKS_FILE = "tiebreaks.csv"
DROPOUTS_FILE = "dropouts.csv"
VOIDED_RESULTS_FILE = "voided_results.csv"
USED_PROMPTS_FILE = "used_prompts.csv"
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

# The issue's columns come first, so the file reads well in a spreadsheet;
# the ids after them are what the app matches on.
RESULTS_COLUMNS = (
    "player",
    "score",
    "coryat",
    "game",
    "result",
    "player_id",
    "game_key",
    "saved_game",
)
# Columns a results row can't be matched or read without.
RESULTS_REQUIRED_COLUMNS = ("player_id", "game_key", "score", "result")
# The winner's name comes first, so the file reads well in a spreadsheet.
# ``players`` holds the tied players' ids, separated by spaces.
TIEBREAK_COLUMNS = ("round", "winner_name", "winner", "players")
TIEBREAK_REQUIRED_COLUMNS = ("round", "winner", "players")
DROPOUT_COLUMNS = (
    "player_name",
    "round",
    "choice",
    "player_id",
    "game_key",
    "other_id",
)
DROPOUT_REQUIRED_COLUMNS = ("round", "choice", "player_id")
USED_PROMPT_COLUMNS = ("player_id", "prompt", "text")

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
        retired_boards: Boards of voided games, each remembering its game
            in ``left_game_key``. They're kept so they aren't played again.
    """

    name: str
    sheet_url: str = ""
    ignored_sign_ups: list[str] = field(default_factory=list)
    bracket: BracketSettings = field(default_factory=BracketSettings)
    boards: dict[str, TournamentBoard] = field(default_factory=dict)
    unassigned_boards: list[TournamentBoard] = field(default_factory=list)
    logo_file: str = ""
    retired_boards: list[TournamentBoard] = field(default_factory=list)


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
        "retired_boards": [
            {**board.to_json(), "game_key": board.left_game_key}
            for board in settings.retired_boards
        ],
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
    retired = []
    retired_payload = payload.get("retired_boards")
    for board_payload in retired_payload if isinstance(retired_payload, list) else []:
        board = TournamentBoard.from_json(board_payload)
        if board is not None:
            retired.append(
                replace(board, left_game_key=str(board_payload.get("game_key") or ""))
            )
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
        retired_boards=retired,
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


def results_csv_text(results: Sequence[GameResult]) -> str:
    """Return ``results.csv`` contents.

    Args:
        results: Results, in file order.

    Returns:
        CSV text with a header row and one row per result.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(RESULTS_COLUMNS)
    for result in results:
        writer.writerow(
            [
                result.player,
                result.score,
                "" if result.coryat is None else result.coryat,
                result.game,
                result.result,
                result.player_id,
                result.game_key,
                result.saved_game,
            ]
        )
    return buffer.getvalue()


def _int_cell(text: str, column: str, line: int) -> int:
    """Return ``text`` as an integer, or raise naming the bad cell."""
    try:
        return int(text)
    except ValueError:
        raise TournamentFileError(
            f"{RESULTS_FILE} line {line}: {column} {text!r} isn't a whole number."
        ) from None


def parse_results_csv(text: str) -> list[GameResult]:
    """Read results from ``results.csv`` contents.

    Args:
        text: CSV text.

    Returns:
        The results, in file order. Rows without a game key or player id
        are skipped, since nothing can match them.

    Raises:
        TournamentFileError: If the header lacks a column JParty needs, a
            score isn't a whole number, a result isn't ``win`` or ``loss``,
            or the file isn't valid CSV.
    """
    try:
        return _parse_results_rows(csv.DictReader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        raise TournamentFileError(f"Couldn't read {RESULTS_FILE}: {exc}") from exc


def _parse_results_rows(reader: csv.DictReader) -> list[GameResult]:
    """Read results from a ``results.csv`` reader; see parse_results_csv."""
    if reader.fieldnames is None:
        return []
    # A file whose header JParty can't read would otherwise look empty, and
    # the next game would replace every row in it. A spreadsheet that saves
    # with ";" between cells, or a renamed column, is the usual cause.
    # Rows are keyed by these names, so trim them here, not only for the
    # check: "game_key" and " game_key" must be the same column.
    reader.fieldnames = [(name or "").strip() for name in reader.fieldnames]
    header = set(reader.fieldnames)
    missing = [column for column in RESULTS_REQUIRED_COLUMNS if column not in header]
    if missing:
        raise TournamentFileError(
            f"{RESULTS_FILE} has no {', '.join(missing)} column. Save it as "
            "comma-separated values with the header row JParty wrote."
        )
    results = []
    for line, row in enumerate(reader, start=2):

        def value(column: str, row: dict = row) -> str:
            """Return a row's cell for ``column``, or ``""``."""
            return (row.get(column) or "").strip()

        if not value("game_key") or not value("player_id"):
            continue
        result = value("result").lower()
        if result not in RESULTS:
            raise TournamentFileError(
                f"{RESULTS_FILE} line {line}: result {result!r} should be win or loss."
            )
        coryat = value("coryat")
        results.append(
            GameResult(
                game_key=value("game_key"),
                player_id=value("player_id"),
                player=value("player"),
                score=_int_cell(value("score"), "score", line),
                coryat=_int_cell(coryat, "coryat", line) if coryat else None,
                game=value("game"),
                result=result,
                saved_game=value("saved_game"),
            )
        )
    return results


def load_results(folder: Path) -> list[GameResult]:
    """Read a tournament's results.

    Args:
        folder: The tournament's folder.

    Returns:
        The results, or an empty list if no game has been played.

    Raises:
        TournamentFileError: If ``results.csv`` can't be read.
    """
    text = _read_csv(Path(folder) / RESULTS_FILE)
    return parse_results_csv(text) if text is not None else []


def load_voided_results(folder: Path) -> list[GameResult]:
    """Read the results of a tournament's voided games.

    Args:
        folder: The tournament's folder.

    Returns:
        The voided results, or an empty list if no game was voided.

    Raises:
        TournamentFileError: If ``voided_results.csv`` can't be read.
    """
    text = _read_csv(Path(folder) / VOIDED_RESULTS_FILE)
    return parse_results_csv(text) if text is not None else []


def _read_csv(path: Path) -> str | None:
    """Return a CSV file's text, or ``None`` if there's no such file.

    Raises:
        TournamentFileError: If the file can't be read, or isn't UTF-8.
    """
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        # Excel's plain "CSV" format isn't UTF-8.
        raise TournamentFileError(
            f'{path.name} isn\'t saved as UTF-8. In Excel, save it as "CSV UTF-8".'
        ) from exc
    except OSError as exc:
        raise TournamentFileError(f"Couldn't read {path.name}: {exc}") from exc


def save_results(folder: Path, results: Sequence[GameResult]) -> None:
    """Write a tournament's results, replacing the file.

    Args:
        folder: The tournament's folder.
        results: Every result, in file order.

    Raises:
        TournamentFileError: If the file can't be written.
    """
    try:
        write_text_atomic(Path(folder) / RESULTS_FILE, results_csv_text(results))
    except OSError as exc:
        raise TournamentFileError(f"Couldn't save {RESULTS_FILE}: {exc}") from exc


def record_game_results(folder: Path, new_results: Sequence[GameResult]) -> None:
    """Save one game's results, replacing any rows that game already had.

    Args:
        folder: The tournament's folder.
        new_results: The game's rows.

    Raises:
        TournamentFileError: If ``results.csv`` can't be read or written.
    """
    save_results(folder, record_results(load_results(folder), new_results))


def tiebreaks_csv_text(tiebreaks: Sequence[Tiebreak]) -> str:
    """Return ``tiebreaks.csv`` contents.

    Args:
        tiebreaks: Tiebreakers, in the order they were played.

    Returns:
        CSV text with a header row and one row per tiebreaker.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TIEBREAK_COLUMNS)
    for tiebreak in tiebreaks:
        writer.writerow(
            [
                tiebreak.round_name,
                tiebreak.winner_name,
                tiebreak.winner,
                " ".join(sorted(tiebreak.contenders)),
            ]
        )
    return buffer.getvalue()


def parse_tiebreaks_csv(text: str) -> list[Tiebreak]:
    """Read tiebreakers from ``tiebreaks.csv`` contents.

    Args:
        text: CSV text.

    Returns:
        The tiebreakers, in file order. Blank rows are skipped.

    Raises:
        TournamentFileError: If a column is missing, a row has no round, or
            its winner isn't one of its players.
    """
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames is None:
            return []
        reader.fieldnames = [(name or "").strip() for name in reader.fieldnames]
        missing = [
            column
            for column in TIEBREAK_REQUIRED_COLUMNS
            if column not in reader.fieldnames
        ]
        if missing:
            raise TournamentFileError(
                f"{TIEBREAKS_FILE} has no {', '.join(missing)} column."
            )
        tiebreaks = []
        for line, row in enumerate(reader, start=2):
            cells = {key: (value or "").strip() for key, value in row.items() if key}
            if not any(cells.values()):
                continue
            players = frozenset(cells.get("players", "").split())
            if not cells.get("round") or cells.get("winner") not in players:
                raise TournamentFileError(
                    f"{TIEBREAKS_FILE} line {line}: a tiebreaker needs its round, "
                    "and a winner who is one of its players."
                )
            tiebreaks.append(
                Tiebreak(
                    cells["round"],
                    players,
                    cells["winner"],
                    cells.get("winner_name", ""),
                )
            )
        return tiebreaks
    except csv.Error as exc:
        raise TournamentFileError(f"Couldn't read {TIEBREAKS_FILE}: {exc}") from exc


def load_tiebreaks(folder: Path) -> list[Tiebreak]:
    """Read a tournament's tiebreakers.

    Args:
        folder: The tournament's folder.

    Returns:
        The tiebreakers, or an empty list if none have been played.

    Raises:
        TournamentFileError: If ``tiebreaks.csv`` can't be read.
    """
    path = Path(folder) / TIEBREAKS_FILE
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TournamentFileError(
            f'{TIEBREAKS_FILE} isn\'t saved as UTF-8. In Excel, save it as "CSV UTF-8".'
        ) from exc
    except OSError as exc:
        raise TournamentFileError(f"Couldn't read {TIEBREAKS_FILE}: {exc}") from exc
    return parse_tiebreaks_csv(text)


def record_tiebreak(folder: Path, tiebreak: Tiebreak) -> None:
    """Save a tiebreaker, replacing an earlier one between the same players.

    Playing the same tie again replaces its winner instead of adding a
    second row that might disagree.

    Args:
        folder: The tournament's folder.
        tiebreak: The tiebreaker just played.

    Raises:
        TournamentFileError: If ``tiebreaks.csv`` can't be read or written.
    """
    tiebreaks = [
        earlier
        for earlier in load_tiebreaks(folder)
        if (earlier.round_name, earlier.contenders)
        != (tiebreak.round_name, tiebreak.contenders)
    ]
    try:
        write_text_atomic(
            Path(folder) / TIEBREAKS_FILE, tiebreaks_csv_text([*tiebreaks, tiebreak])
        )
    except OSError as exc:
        raise TournamentFileError(f"Couldn't save {TIEBREAKS_FILE}: {exc}") from exc


def dropouts_csv_text(dropouts: Sequence[Dropout]) -> str:
    """Return ``dropouts.csv`` contents.

    Args:
        dropouts: Dropouts, in the order they happened.

    Returns:
        CSV text with a header row and one row per dropout.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(DROPOUT_COLUMNS)
    for dropout in dropouts:
        writer.writerow(
            [
                dropout.player_name,
                dropout.round_name,
                dropout.choice,
                dropout.player_id,
                dropout.game_key,
                dropout.other_id,
            ]
        )
    return buffer.getvalue()


def parse_dropouts_csv(text: str) -> list[Dropout]:
    """Read dropouts from ``dropouts.csv`` contents.

    Args:
        text: CSV text.

    Returns:
        The dropouts, in file order. Blank rows are skipped.

    Raises:
        TournamentFileError: If a column is missing, or a row has no round,
            no player, or an unknown choice.
    """
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames is None:
            return []
        reader.fieldnames = [(name or "").strip() for name in reader.fieldnames]
        missing = [
            column
            for column in DROPOUT_REQUIRED_COLUMNS
            if column not in reader.fieldnames
        ]
        if missing:
            raise TournamentFileError(
                f"{DROPOUTS_FILE} has no {', '.join(missing)} column."
            )
        dropouts = []
        for line, row in enumerate(reader, start=2):
            cells = {key: (value or "").strip() for key, value in row.items() if key}
            if not any(cells.values()):
                continue
            if (
                not cells.get("round")
                or not cells.get("player_id")
                or cells.get("choice") not in DROP_CHOICES
            ):
                raise TournamentFileError(
                    f"{DROPOUTS_FILE} line {line}: a dropout needs its round, its "
                    f"player, and a choice of {', '.join(DROP_CHOICES)}."
                )
            dropouts.append(
                Dropout(
                    cells["player_id"],
                    cells["round"],
                    cells["choice"],
                    game_key=cells.get("game_key", ""),
                    other_id=cells.get("other_id", ""),
                    player_name=cells.get("player_name", ""),
                )
            )
        return dropouts
    except csv.Error as exc:
        raise TournamentFileError(f"Couldn't read {DROPOUTS_FILE}: {exc}") from exc


def load_dropouts(folder: Path) -> list[Dropout]:
    """Read a tournament's dropouts.

    Args:
        folder: The tournament's folder.

    Returns:
        The dropouts, or an empty list if no one has dropped out.

    Raises:
        TournamentFileError: If ``dropouts.csv`` can't be read.
    """
    text = _read_csv(Path(folder) / DROPOUTS_FILE)
    return parse_dropouts_csv(text) if text is not None else []


def load_tournament_data(
    folder: Path,
) -> tuple[TournamentSettings, TournamentData]:
    """Read everything a dropout can change.

    Args:
        folder: The tournament's folder.

    Returns:
        The settings, and the tournament's data.

    Raises:
        TournamentFileError: If a file is missing or can't be read.
    """
    folder = Path(folder)
    settings, slots = load_tournament(folder)
    data = TournamentData(
        bracket=settings.bracket,
        slots=tuple(slots),
        results=tuple(load_results(folder)),
        tiebreaks=tuple(load_tiebreaks(folder)),
        dropouts=tuple(load_dropouts(folder)),
        voided=tuple(load_voided_results(folder)),
        boards=dict(settings.boards),
        unassigned=tuple(settings.unassigned_boards),
        retired=tuple(settings.retired_boards),
    )
    return settings, data


def save_tournament_data(
    folder: Path, settings: TournamentSettings, data: TournamentData
) -> None:
    """Write a dropout's changes: voided results, dropouts, results, and setup.

    Voided results are written first, so a game's results are never lost if
    a later write fails.

    Args:
        folder: The tournament's folder.
        settings: The tournament's settings; its boards are updated from
            ``data``.
        data: The changed tournament.

    Raises:
        TournamentFileError: If a file can't be written.
    """
    folder = Path(folder)
    try:
        write_text_atomic(folder / VOIDED_RESULTS_FILE, results_csv_text(data.voided))
        write_text_atomic(folder / DROPOUTS_FILE, dropouts_csv_text(data.dropouts))
    except OSError as exc:
        raise TournamentFileError(f"Couldn't save the dropout: {exc}") from exc
    save_results(folder, data.results)
    settings.boards = dict(data.boards)
    settings.unassigned_boards = list(data.unassigned)
    settings.retired_boards = list(data.retired)
    try:
        save_tournament(folder.parent, settings, data.slots)
    except OSError as exc:
        raise TournamentFileError(f"Couldn't save the tournament: {exc}") from exc


def used_prompts_csv_text(used: Sequence[tuple[str, int, str]]) -> str:
    """Return ``used_prompts.csv`` contents.

    Args:
        used: ``(player_id, prompt number, prompt text)`` for each prompt the
            host has used, in the order they were marked.

    Returns:
        CSV text with a header row and one row per used prompt.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(USED_PROMPT_COLUMNS)
    for player_id, number, text in used:
        writer.writerow([player_id, number, text])
    return buffer.getvalue()


def load_used_prompts(folder: Path) -> list[tuple[str, int, str]]:
    """Read the prompts the host has marked as used.

    Rows that can't be read are skipped: this file only greys out prompts
    on the host's phone, so it never stops the tournament.

    Args:
        folder: The tournament's folder.

    Returns:
        ``(player_id, prompt number, prompt text)`` for each used prompt.

    Raises:
        TournamentFileError: If ``used_prompts.csv`` can't be read.
    """
    text = _read_csv(Path(folder) / USED_PROMPTS_FILE)
    if text is None:
        return []
    used = []
    try:
        for row in csv.DictReader(io.StringIO(text, newline="")):
            player_id = (row.get("player_id") or "").strip()
            number = (row.get("prompt") or "").strip()
            if player_id and number.isdigit():
                used.append((player_id, int(number), (row.get("text") or "").strip()))
    except csv.Error as exc:
        raise TournamentFileError(f"Couldn't read {USED_PROMPTS_FILE}: {exc}") from exc
    return used


def set_prompt_used(
    folder: Path, player_id: str, number: int, text: str, used: bool
) -> None:
    """Mark one of a player's prompts as used, or not used, and save it.

    Args:
        folder: The tournament's folder.
        player_id: The player.
        number: The prompt's number, from 1 (Anecdote #1).
        text: The prompt's text, so the saved file reads well.
        used: Whether it's used.

    Raises:
        TournamentFileError: If ``used_prompts.csv`` can't be read or written.
    """
    rows = [
        row
        for row in load_used_prompts(folder)
        if (row[0], row[1]) != (player_id, number)
    ]
    if used:
        rows.append((player_id, number, text))
    try:
        write_text_atomic(Path(folder) / USED_PROMPTS_FILE, used_prompts_csv_text(rows))
    except OSError as exc:
        raise TournamentFileError(f"Couldn't save {USED_PROMPTS_FILE}: {exc}") from exc
