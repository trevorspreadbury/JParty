"""Playing a tournament's games: who may play, results, and introductions.

A tournament's games come from its bracket (see
:mod:`jparty.domain.tournament.bracket`) and their boards from its setup (see
:mod:`jparty.domain.tournament.setup`). This module adds what playing needs:

- :class:`GameResult` rows, one per player per game, as saved in
  ``results.csv``.
- The host's introduction of the players before a game.

Who may sit in a game depends on who advanced, so it lives in
:mod:`jparty.domain.tournament.advancement`.

These are pure functions over plain data, so the welcome screen and the
results editor share one set of rules.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from jparty.domain.tournament.roster import PlayerSlot

RESULT_WIN = "win"
RESULT_LOSS = "loss"
RESULTS = (RESULT_WIN, RESULT_LOSS)

INTRO_HEADING = "Let's meet today's contestants:"


@dataclass(frozen=True)
class GameResult:
    """One player's result in one tournament game.

    Attributes:
        game_key: The bracket game, as :func:`game_key` names it.
        player_id: The player's :attr:`PlayerSlot.player_id`.
        player: The player's Actual Name when the game was played.
        score: Final score.
        coryat: Coryat score, or ``None`` if it couldn't be worked out.
        game: ``"<tournament name>-<game id>"``, where the game id is the
            played board's id (as in the saved game's folder name).
        result: :data:`RESULT_WIN` or :data:`RESULT_LOSS`.
        saved_game: Folder name of the saved game, so playing the same save
            again replaces its rows instead of adding more. ``""`` if unknown.
    """

    game_key: str
    player_id: str
    player: str
    score: int
    coryat: int | None
    game: str
    result: str
    saved_game: str = ""

    @property
    def won(self) -> bool:
        """Return whether the player won the game."""
        return self.result == RESULT_WIN


def game_label(tournament_name: str, game_id: str) -> str:
    """Return the ``game`` column's value for a results row.

    Args:
        tournament_name: The tournament's name.
        game_id: The played board's id, such as ``"4453"``.

    Returns:
        ``"<tournament name>-<game id>"``.
    """
    return f"{tournament_name}-{game_id}"


def record_results(
    results: Sequence[GameResult], new_results: Sequence[GameResult]
) -> list[GameResult]:
    """Return ``results`` with one game's new rows in place of its old ones.

    A game's rows are replaced when the same game is logged again, for
    example when it is replayed or resumed after its results were saved.

    Args:
        results: Every saved result, in file order.
        new_results: One game's rows. Empty leaves ``results`` unchanged.

    Returns:
        The updated results. The game's rows go where its old rows were, or
        at the end if it had none.
    """
    if not new_results:
        return list(results)
    keys = {result.game_key for result in new_results}
    updated: list[GameResult] = []
    inserted = False
    for result in results:
        if result.game_key not in keys:
            updated.append(result)
        elif not inserted:
            updated.extend(new_results)
            inserted = True
    if not inserted:
        updated.extend(new_results)
    return updated


def played_game_keys(results: Iterable[GameResult]) -> set[str]:
    """Return the keys of games with saved results."""
    return {result.game_key for result in results}


def played_player_ids(results: Iterable[GameResult]) -> set[str]:
    """Return the ids of players with at least one saved result."""
    return {result.player_id for result in results}


def results_by_game(results: Iterable[GameResult]) -> dict[str, list[GameResult]]:
    """Return results grouped by game key, keeping file order in each game."""
    grouped: dict[str, list[GameResult]] = {}
    for result in results:
        grouped.setdefault(result.game_key, []).append(result)
    return grouped


def _article(word: str) -> str:
    """Return ``"An"`` before a vowel sound's letter, else ``"A"``."""
    return "An" if word[:1].lower() in "aeiou" else "A"


def _same_name(first: str, second: str) -> bool:
    """Return whether two names match, ignoring case and spacing."""
    return " ".join(first.split()).casefold() == " ".join(second.split()).casefold()


def introduction_line(slot: PlayerSlot) -> str:
    """Return how the host introduces one player.

    The line reads ``"A {occupation} from {hometown}, {full name} ({actual
    name})"``. The name appears once when the Full Name and Actual Name
    match, and a blank occupation or hometown is left out. A player with no
    linked sign-up is introduced by their Actual Name alone.

    Args:
        slot: The player.

    Returns:
        The line to read out.
    """
    actual_name = slot.actual_name.strip()
    sign_up = slot.sign_up
    if sign_up is None:
        return actual_name
    full_name = sign_up.full_name.strip() or actual_name
    name = (
        full_name
        if _same_name(full_name, actual_name) or not actual_name
        else f"{full_name} ({actual_name})"
    )
    occupation = sign_up.occupation.strip()
    hometown = sign_up.hometown.strip()
    if occupation and hometown:
        description = f"{_article(occupation)} {occupation} from {hometown}"
    elif occupation:
        description = f"{_article(occupation)} {occupation}"
    elif hometown:
        description = f"From {hometown}"
    else:
        return name
    return f"{description}, {name}"


def introduction_lines(slots: Sequence[PlayerSlot]) -> list[str]:
    """Return the host's introduction for a game's players, in podium order.

    Args:
        slots: The game's players, in podium order.

    Returns:
        :data:`INTRO_HEADING`, then one line per player.
    """
    return [INTRO_HEADING, *(introduction_line(slot) for slot in slots)]


def slots_by_id(slots: Iterable[PlayerSlot]) -> Mapping[str, PlayerSlot]:
    """Return roster slots by player id."""
    return {slot.player_id: slot for slot in slots}


# Keys added to a player's entry in a saved game's ``general.json`` players
# list when the game is a tournament game.
SAVED_PLAYER_ID = "tournament_player_id"
SAVED_PLAYER_NAME = "tournament_player_name"


@dataclass(frozen=True)
class TournamentGameRef:
    """Which tournament game a saved game is, as saved in ``general.json``.

    Attributes:
        tournament: The tournament's name, which is also its folder name.
        game_key: The bracket game.
    """

    tournament: str
    game_key: str

    def to_json(self) -> dict:
        """Return the reference as a JSON-ready dictionary."""
        return {"name": self.tournament, "game_key": self.game_key}

    @classmethod
    def from_json(cls, payload: object) -> TournamentGameRef | None:
        """Read a reference saved by :meth:`to_json`.

        Args:
            payload: The decoded ``tournament`` value, or anything else.

        Returns:
            The reference, or ``None`` if ``payload`` isn't one.
        """
        if not isinstance(payload, Mapping):
            return None
        name = str(payload.get("name") or "").strip()
        key = str(payload.get("game_key") or "").strip()
        if not name or not key:
            return None
        return cls(name, key)


@dataclass(frozen=True)
class PlayerOutcome:
    """One player's end-of-game numbers, by their current player number.

    Attributes:
        player_number: The player's seat in the game.
        score: Final score.
        coryat: Coryat score.
    """

    player_number: int
    score: int
    coryat: int | None


def game_results(
    ref: TournamentGameRef,
    saved_players: Sequence[Mapping],
    outcomes: Sequence[PlayerOutcome],
    winner_numbers: Iterable[int],
    game_id: str,
    saved_game: str,
) -> list[GameResult]:
    """Return a finished game's results rows.

    Args:
        ref: Which tournament game was played.
        saved_players: The saved game's players, with every seat change
            applied (see :func:`jparty.domain.state.current_saved_players`),
            so each ``player_number`` is the player's current seat. Entries
            without :data:`SAVED_PLAYER_ID` are skipped.
        outcomes: Each player's score and Coryat.
        winner_numbers: Seats of the winners. A tiebreaker leaves one.
        game_id: The played board's id.
        saved_game: The saved game's folder name.

    Returns:
        One row per tournament player, in seat order.
    """
    by_number = {outcome.player_number: outcome for outcome in outcomes}
    winners = set(winner_numbers)
    results = []
    for player in sorted(
        saved_players, key=lambda entry: _int_or_none(entry.get("player_number")) or 0
    ):
        player_id = str(player.get(SAVED_PLAYER_ID) or "")
        number = _int_or_none(player.get("player_number"))
        if not player_id or number is None or number not in by_number:
            continue
        outcome = by_number[number]
        results.append(
            GameResult(
                game_key=ref.game_key,
                player_id=player_id,
                player=str(player.get(SAVED_PLAYER_NAME) or ""),
                score=outcome.score,
                coryat=outcome.coryat,
                game=game_label(ref.tournament, game_id),
                result=RESULT_WIN if number in winners else RESULT_LOSS,
                saved_game=saved_game,
            )
        )
    return results


def already_recorded(
    results: Iterable[GameResult], game_key: str, saved_game: str
) -> bool:
    """Return whether this saved game's results are already in ``results``.

    Resuming a finished game ends it again. Its rows are kept as they are
    then, since the host may have fixed them.

    Args:
        results: Every saved result.
        game_key: The bracket game.
        saved_game: The saved game's folder name.

    Returns:
        Whether ``game_key`` has rows from ``saved_game``.
    """
    return any(
        result.game_key == game_key and result.saved_game == saved_game
        for result in results
    )


def _int_or_none(value: object) -> int | None:
    """Return ``value`` as an integer, or ``None``."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
