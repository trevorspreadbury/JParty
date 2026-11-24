"""Who has control of the board, and so picks the next clue.

The rules, as on the show:

- At the start of each round the player with the lowest score picks first.
  Ties go to the earliest seat, so the first round starts at seat 1.
- A correct response gives that player control.
- A clue nobody gets, or a wrong response, leaves control where it was.

The functions here are pure. ``Game`` keeps the current holder and calls them.
A host who clicks the board is never stopped; control only decides whose
phone offers the board.
"""

from collections.abc import Iterable


def control_at_round_start(players: Iterable[object]) -> object | None:
    """Return who picks first in a round: the lowest score, earliest seat.

    Args:
        players: Players with ``score`` and ``player_number``.

    Returns:
        The player, or ``None`` when there are none.
    """
    players = list(players)
    if not players:
        return None
    return min(players, key=lambda player: (player.score, player.player_number))


def control_after_ruling(
    in_control: object | None, player: object, correct: bool
) -> object | None:
    """Return who has control after ``player`` is ruled on.

    Args:
        in_control: Who had control before the ruling.
        player: The player just ruled on.
        correct: Whether their response was ruled correct.

    Returns:
        ``player`` after a correct response; otherwise ``in_control``.
    """
    return player if correct else in_control


def control_from_history(
    history: Iterable[dict], round_index: int | None, players: Iterable[object]
) -> object | None:
    """Return who has control when a saved game resumes mid-round.

    It is the last player ruled correct on a clue in the current round. If
    nobody has been yet, or that player is no longer seated, it is the
    round's first picker by current scores.

    Args:
        history: ``question_history.jsonl`` entries, oldest first.
        round_index: The round being resumed.
        players: The seated players.

    Returns:
        The player in control, or ``None`` when there are no players.
    """
    players = list(players)
    by_number = {player.player_number: player for player in players}
    last_correct = None
    for entry in history:
        if entry.get("round_index") != round_index or "question_index" not in entry:
            continue
        for attempt in entry.get("answer_attempts") or []:
            if attempt.get("answer_correct"):
                last_correct = attempt.get("player_index")
    if last_correct in by_number:
        return by_number[last_correct]
    return control_at_round_start(players)


def board_for_phone(board: object) -> dict:
    """Describe the clues left on a board for the picking player's phone.

    Args:
        board: A ``Board`` with ``categories``, ``size`` and ``get_question``.

    Returns:
        ``{"categories": [...], "rows": [[value or None, ...], ...]}`` with
        one row per clue row and one entry per category. ``None`` marks a
        clue already played or missing.
    """
    columns, rows = board.size
    grid = []
    for row in range(rows):
        values = []
        for column in range(columns):
            question = board.get_question(column, row)
            playable = question is not None and not question.complete
            values.append(question.value if playable else None)
        grid.append(values)
    return {"categories": list(board.categories), "rows": grid}
