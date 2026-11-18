"""Tournament rosters built from a Google Form sign-up sheet.

A roster is a list of player slots. Each slot has an *Actual Name*, the name
the game shows, and may be linked to one sign-up row from the sheet. Players
sometimes enter silly names on the form, so the Actual Name starts as the
sign-up's Full Name and the host can change it.

The host can create more slots than the sheet has rows and type the missing
names by hand. When the sheet is refreshed later, new rows are matched to
those slots. Rows are identified by their Timestamp, so a row that is
already linked stays linked after a refresh.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

COLUMN_TIMESTAMP = "Timestamp"
COLUMN_FULL_NAME = "Full Name"
COLUMN_OCCUPATION = "Occupation"
COLUMN_HOMETOWN = "Hometown"
ANECDOTE_COLUMNS = ("Anecdote #1", "Anecdote #2", "Anecdote #3")
REQUIRED_SHEET_COLUMNS = (COLUMN_TIMESTAMP, COLUMN_FULL_NAME)

# Name similarity needed before a sign-up is suggested for a typed name.
MATCH_SUGGESTION_CUTOFF = 0.6

_NAME_PIECE = re.compile(r"[^\s\-']+|[\s\-']+")


class RosterError(ValueError):
    """Raised when a sign-up sheet cannot be read as a roster."""


@dataclass(frozen=True)
class SignUp:
    """One response row from the sign-up sheet.

    Attributes:
        timestamp: The form's Timestamp cell, used to recognize the row.
        full_name: The name the player entered on the form.
        occupation: The player's occupation.
        hometown: The player's hometown.
        anecdotes: The player's anecdotes, in sheet order, blanks included.
    """

    timestamp: str
    full_name: str
    occupation: str = ""
    hometown: str = ""
    anecdotes: tuple[str, ...] = ("", "", "")


@dataclass(frozen=True)
class PlayerSlot:
    """One player's place in the tournament.

    Attributes:
        actual_name: The name the game shows for this player.
        sign_up: The linked sign-up row, or ``None`` if none is linked yet.
    """

    actual_name: str = ""
    sign_up: SignUp | None = None

    @property
    def blank(self) -> bool:
        """Whether the slot has neither a name nor a linked sign-up."""
        return not self.actual_name.strip() and self.sign_up is None


@dataclass(frozen=True)
class SignUpMatch:
    """A sign-up row the host needs to place, with the app's best guess.

    Attributes:
        sign_up: The new sign-up row.
        suggested_slot: Index of the suggested slot, or ``None`` to suggest
            adding the player as a new slot.
    """

    sign_up: SignUp
    suggested_slot: int | None


# Choices for a sign-up besides linking it to an existing slot.
MATCH_ADD_PLAYER = "add"
MATCH_IGNORE = "ignore"


def title_case_name(name: str) -> str:
    """Return ``name`` with each word capitalized.

    Words the player already wrote in mixed case, such as ``McDonald``, are
    left alone. Only all-lowercase and all-uppercase words change. Hyphens and
    apostrophes start new words, so ``o'brien-smith`` becomes
    ``O'Brien-Smith``. Extra spaces are collapsed.

    Args:
        name: Name as typed on the form.

    Returns:
        The cleaned-up name.
    """
    words = []
    for piece in _NAME_PIECE.findall(" ".join(name.split())):
        if piece.isalpha() and (piece.islower() or piece.isupper()):
            piece = piece[0].upper() + piece[1:].lower()
        words.append(piece)
    return "".join(words)


def parse_sign_up_sheet(rows: Sequence[Sequence[str]]) -> list[SignUp]:
    """Read sign-up rows from a sheet's CSV rows.

    The first row must be the header. Column names are matched without regard
    to case or surrounding spaces, and columns can be in any order. Only
    Timestamp and Full Name are required. Rows without a Timestamp are
    skipped, because they cannot be recognized on a later refresh.

    Args:
        rows: The sheet as rows of cell strings, header first.

    Returns:
        One :class:`SignUp` per response, in sheet order.

    Raises:
        RosterError: If the sheet is empty, lacks a required column, or has
            two rows with the same Timestamp.
    """
    if not rows:
        raise RosterError("The sign-up sheet is empty.")
    header = {cell.strip().casefold(): index for index, cell in enumerate(rows[0])}
    missing = [name for name in REQUIRED_SHEET_COLUMNS if name.casefold() not in header]
    if missing:
        raise RosterError(
            "The sign-up sheet is missing the "
            + " and ".join(f'"{name}"' for name in missing)
            + (" column." if len(missing) == 1 else " columns.")
        )

    def cell(row: Sequence[str], column: str) -> str:
        """Return a row's trimmed cell for ``column``, or ``""``."""
        index = header.get(column.casefold())
        if index is None or index >= len(row):
            return ""
        return row[index].strip()

    sign_ups = []
    seen = set()
    for row in rows[1:]:
        timestamp = cell(row, COLUMN_TIMESTAMP)
        if not timestamp:
            continue
        if timestamp in seen:
            raise RosterError(f'Two sign-ups have the same Timestamp, "{timestamp}".')
        seen.add(timestamp)
        sign_ups.append(
            SignUp(
                timestamp=timestamp,
                full_name=cell(row, COLUMN_FULL_NAME),
                occupation=cell(row, COLUMN_OCCUPATION),
                hometown=cell(row, COLUMN_HOMETOWN),
                anecdotes=tuple(cell(row, column) for column in ANECDOTE_COLUMNS),
            )
        )
    return sign_ups


def update_linked_sign_ups(
    slots: Sequence[PlayerSlot], sign_ups: Iterable[SignUp]
) -> list[PlayerSlot]:
    """Refresh each linked slot with its row's latest answers.

    A player may edit their form response after signing up. Slots whose row
    is no longer in the sheet keep the answers they had.

    Args:
        slots: Current roster.
        sign_ups: Rows from the latest fetch.

    Returns:
        The roster with linked sign-ups replaced by their latest versions.
    """
    latest = {sign_up.timestamp: sign_up for sign_up in sign_ups}
    return [
        replace(slot, sign_up=latest[slot.sign_up.timestamp])
        if slot.sign_up is not None and slot.sign_up.timestamp in latest
        else slot
        for slot in slots
    ]


def new_sign_ups(
    slots: Sequence[PlayerSlot],
    sign_ups: Iterable[SignUp],
    ignored: Iterable[str] = (),
) -> list[SignUp]:
    """Return sign-ups not linked to any slot and not ignored by the host.

    Args:
        slots: Current roster.
        sign_ups: Rows from the latest fetch.
        ignored: Timestamps of rows the host chose to ignore.

    Returns:
        The unplaced sign-ups, in sheet order.
    """
    taken = {slot.sign_up.timestamp for slot in slots if slot.sign_up is not None}
    taken.update(ignored)
    return [sign_up for sign_up in sign_ups if sign_up.timestamp not in taken]


def open_slots(
    slots: Sequence[PlayerSlot], sign_ups: Iterable[SignUp] | None = None
) -> list[int]:
    """Return indices of slots a new sign-up can be linked to.

    A slot is open if it has no linked sign-up. When ``sign_ups`` is given, a
    slot whose linked row is no longer in the sheet is open too, since the
    player may have deleted and resubmitted their response.

    Args:
        slots: Current roster.
        sign_ups: Rows from the latest fetch, if known.

    Returns:
        Open slot indices in roster order.
    """
    present = None if sign_ups is None else {sign_up.timestamp for sign_up in sign_ups}
    return [
        index
        for index, slot in enumerate(slots)
        if slot.sign_up is None
        or (present is not None and slot.sign_up.timestamp not in present)
    ]


def fill_blank_slots(
    slots: Sequence[PlayerSlot], sign_ups: Sequence[SignUp]
) -> tuple[list[PlayerSlot], list[SignUp]]:
    """Link sign-ups to blank slots in order, when no slot needs matching.

    If every open slot is blank, there is nothing to match against, so rows
    simply fill those slots in sheet order. If any open slot already has a
    typed name, nothing is filled, and every row goes to the host to match.

    Args:
        slots: Current roster.
        sign_ups: Unplaced sign-ups, in sheet order.

    Returns:
        The updated roster and the sign-ups still left to place.
    """
    candidates = open_slots(slots)
    if any(not slots[index].blank for index in candidates):
        return list(slots), list(sign_ups)
    filled = list(slots)
    remaining = list(sign_ups)
    for index in candidates:
        if not remaining:
            break
        filled[index] = link_sign_up(filled[index], remaining.pop(0))
    return filled, remaining


def suggest_matches(
    slots: Sequence[PlayerSlot],
    sign_ups: Sequence[SignUp],
    all_sign_ups: Iterable[SignUp] | None = None,
) -> list[SignUpMatch]:
    """Suggest a slot for each unplaced sign-up.

    Each sign-up is suggested for the open slot whose Actual Name is most like
    its Full Name. A sign-up with no close name goes to the next blank slot,
    or to a new slot if none is left. No slot is suggested twice.

    Args:
        slots: Current roster.
        sign_ups: Unplaced sign-ups, in sheet order.
        all_sign_ups: Every row from the latest fetch, used to find slots
            whose linked row has left the sheet.

    Returns:
        One :class:`SignUpMatch` per sign-up, in the same order.
    """
    available = open_slots(slots, all_sign_ups)
    named = {
        index: _name_key(slots[index].actual_name)
        for index in available
        if slots[index].actual_name.strip()
    }
    matches: list[SignUpMatch | None] = [None] * len(sign_ups)
    # Pair the closest names first, so a weaker match can't take a slot that
    # another sign-up matches better.
    scored = sorted(
        (
            (
                difflib.SequenceMatcher(
                    None, _name_key(sign_up.full_name), name
                ).ratio(),
                position,
                index,
            )
            for position, sign_up in enumerate(sign_ups)
            for index, name in named.items()
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    used = set()
    for score, position, index in scored:
        if score < MATCH_SUGGESTION_CUTOFF:
            break
        if matches[position] is None and index not in used:
            matches[position] = SignUpMatch(sign_ups[position], index)
            used.add(index)
    blanks = [index for index in available if slots[index].blank]
    for position, sign_up in enumerate(sign_ups):
        if matches[position] is not None:
            continue
        free = next((index for index in blanks if index not in used), None)
        if free is not None:
            used.add(free)
        matches[position] = SignUpMatch(sign_up, free)
    return [match for match in matches if match is not None]


def apply_matches(
    slots: Sequence[PlayerSlot],
    choices: Sequence[tuple[SignUp, int | str]],
) -> tuple[list[PlayerSlot], list[str]]:
    """Apply the host's choice for each new sign-up.

    Args:
        slots: Current roster.
        choices: Pairs of a sign-up and either a slot index,
            :data:`MATCH_ADD_PLAYER`, or :data:`MATCH_IGNORE`.

    Returns:
        The updated roster and the timestamps the host chose to ignore.

    Raises:
        ValueError: If two sign-ups are linked to the same slot, or a choice
            is not recognized.
    """
    updated = list(slots)
    ignored = []
    linked = set()
    for sign_up, choice in choices:
        if choice == MATCH_IGNORE:
            ignored.append(sign_up.timestamp)
        elif choice == MATCH_ADD_PLAYER:
            updated.append(link_sign_up(PlayerSlot(), sign_up))
        elif isinstance(choice, int) and 0 <= choice < len(slots):
            if choice in linked:
                raise ValueError(f"Slot {choice + 1} was chosen twice.")
            linked.add(choice)
            updated[choice] = link_sign_up(updated[choice], sign_up)
        else:
            raise ValueError(f"Unknown match choice: {choice!r}")
    return updated, ignored


def link_sign_up(slot: PlayerSlot, sign_up: SignUp) -> PlayerSlot:
    """Link ``sign_up`` to ``slot``, naming the slot if it has no name yet.

    Args:
        slot: Slot to link.
        sign_up: Sign-up row to link to it.

    Returns:
        The linked slot. A typed Actual Name is kept; a blank one becomes the
        title-cased Full Name.
    """
    name = slot.actual_name.strip() or title_case_name(sign_up.full_name)
    return PlayerSlot(actual_name=name, sign_up=sign_up)


def _name_key(name: str) -> str:
    """Return a name lowercased with spacing and punctuation removed."""
    return "".join(ch for ch in name.casefold() if ch.isalnum())
