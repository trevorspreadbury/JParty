"""Playing a tournament's games: who may play, results, and introductions.

A tournament's games come from its bracket (see
:mod:`jparty.domain.tournament`) and their boards from its setup (see
:mod:`jparty.domain.tournament_setup`). This module adds what playing needs:

- :class:`GameResult` rows, one per player per game, as saved in
  ``results.csv``.
- Which roster players may sit in a game. Advancement isn't tracked yet, so
  a later round is open to everyone who played a round that feeds it.
- The host's introduction of the players before a game.

These are pure functions over plain data, so the welcome screen and the
results editor share one set of rules.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament import PLAYERS_PER_GAME, TournamentPlan
from jparty.domain.tournament_setup import TournamentBoard, plan_games

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


@dataclass(frozen=True)
class Eligibility:
    """Who may sit in one tournament game.

    Attributes:
        entrants: Ids of players who may take a regular seat, in roster
            order.
        chasers: Ids of players who may take a chase game's chaser seat, in
            roster order. Empty for games that aren't chase games.
        chase: Whether the game is a chase game.
    """

    entrants: tuple[str, ...] = ()
    chasers: tuple[str, ...] = ()
    chase: bool = False

    @property
    def player_ids(self) -> tuple[str, ...]:
        """Return everyone who may sit in the game, entrants first."""
        return self.entrants + tuple(
            player_id for player_id in self.chasers if player_id not in self.entrants
        )


def _round_index_by_key(plan: TournamentPlan) -> dict[str, int]:
    """Return the index of each game's round, by game key."""
    round_indices = {
        id(bracket_round): index for index, bracket_round in enumerate(plan.rounds)
    }
    return {
        key: round_indices[id(bracket_round)]
        for key, bracket_round, _game in plan_games(plan)
    }


def _feeder_rounds(plan: TournamentPlan, round_index: int) -> set[int]:
    """Return the rounds whose players may move on to ``round_index``.

    That's the round before, plus the one before that if its top players
    get byes past the round in between.
    """
    if round_index <= 0:
        return set()
    feeders = {round_index - 1}
    skipped_from = round_index - 2
    if skipped_from >= 0 and plan.rounds[skipped_from].byes:
        feeders.add(skipped_from)
    return feeders


def eligible_players(
    plan: TournamentPlan,
    key: str,
    slots: Sequence[PlayerSlot],
    results: Sequence[GameResult],
    board: TournamentBoard | None = None,
) -> Eligibility:
    """Return who may sit in the game ``key``.

    - A first-round game is open to players who haven't played that round.
    - A later round is open to players who played a round that feeds it
      (the round before, or the one before that for players with byes) and
      haven't played this round yet. Advancement isn't tracked yet, so
      players who were knocked out are included.
    - A chase game's chaser seat is open to players who played and lost
      earlier in the same round.
    - Players on the board's Can't Play list, and players with no name, are
      never eligible.

    Args:
        plan: The tournament's bracket.
        key: The game, as :func:`jparty.domain.tournament_setup.game_key`
            names it.
        slots: The roster.
        results: Every saved result.
        board: The game's board, for its Can't Play list.

    Returns:
        The eligible players. Empty if ``key`` isn't a game in ``plan``.
    """
    games = {game_key: game for game_key, _round, game in plan_games(plan)}
    if key not in games:
        return Eligibility()
    round_of = _round_index_by_key(plan)
    round_index = round_of[key]
    excluded = set(board.cant_play) if board is not None else set()
    named = [
        slot.player_id
        for slot in slots
        if slot.actual_name.strip() and slot.player_id not in excluded
    ]
    in_round = [
        result for result in results if round_of.get(result.game_key) == round_index
    ]
    played_round = {result.player_id for result in in_round}
    feeders = _feeder_rounds(plan, round_index)
    if feeders:
        fed = {
            result.player_id
            for result in results
            if round_of.get(result.game_key) in feeders
        }
        entrants = [
            player_id
            for player_id in named
            if player_id in fed and player_id not in played_round
        ]
    else:
        entrants = [player_id for player_id in named if player_id not in played_round]
    game = games[key]
    chasers: list[str] = []
    if game.chase:
        losers = {result.player_id for result in in_round if not result.won}
        chasers = [player_id for player_id in named if player_id in losers]
    return Eligibility(tuple(entrants), tuple(chasers), chase=game.chase)


def seating_problem(
    eligibility: Eligibility, chosen: Sequence[str | None]
) -> str | None:
    """Return why ``chosen`` can't play a game, or ``None`` if they can.

    Args:
        eligibility: Who may sit in the game.
        chosen: The player id picked for each podium, or ``None`` for an
            empty podium.

    Returns:
        A message for the host, or ``None``.
    """
    picked = [player_id for player_id in chosen if player_id]
    if len(picked) < PLAYERS_PER_GAME:
        return f"Choose a player for each of the {PLAYERS_PER_GAME} podiums."
    if len(set(picked)) != len(picked):
        return "Choose a different player for each podium."
    if any(player_id not in eligibility.player_ids for player_id in picked):
        return "One of the chosen players can't play this game."
    if eligibility.chase:
        chasers = [
            player_id for player_id in picked if player_id not in eligibility.entrants
        ]
        if len(chasers) != 1:
            return (
                "A chase game has two new players and one chaser, a player who "
                "already lost a game this round."
            )
    return None


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
