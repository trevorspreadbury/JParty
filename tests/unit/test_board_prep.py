"""Tests for getting boards ready before they are played."""

from pathlib import Path

from jparty.domain.models import Board, GameData, Question
from jparty.services import board_prep

SHEET_ID = "1AbCdEfGhIjKlMnOp"


def selection(game_id: str, round_index: int = 0) -> dict:
    """Return a board selection for one round of ``game_id``."""
    return {"game_id": game_id, "source_round_index": round_index}


def game_with_image(image: Path | None) -> GameData:
    """Return a one-round game whose first clue shows ``image``."""
    questions = [
        Question((0, row), f"Q{row}", f"A{row}", "Cat", 200 * (row + 1))
        for row in range(5)
    ]
    if image is not None:
        questions[0].image_url = str(image)
    return GameData([Board(["Cat"], questions)], "today", "")


def test_prepare_boards_builds_caches_and_finds_media(
    monkeypatch: object, temp_dir: Path
) -> None:
    """Each source game loads once, J-Archive games are cached, media found."""
    image = temp_dir / "clue.png"
    image.write_bytes(b"png")
    built = []
    saved = []

    def build(selections: list, games: dict) -> GameData:
        """Load each source game once into the shared cache."""
        for item in selections:
            if item["game_id"] not in games:
                built.append(item["game_id"])
                games[item["game_id"]] = object()
        return game_with_image(image if selections[0]["game_id"] == "1111" else None)

    monkeypatch.setattr(board_prep, "build_game_from_board_selection_configs", build)
    monkeypatch.setattr(board_prep, "save_game_html", saved.append)
    progress = []
    prepared = board_prep.prepare_boards(
        [
            ("SF 1", "1111", [selection("1111"), selection("1111", 1)]),
            ("SF 2", "2222 + sheet", [selection("2222"), selection(SHEET_ID)]),
            ("SF 3", "1111 again", [selection("1111")]),
        ],
        on_progress=lambda done, total: progress.append((done, total)),
    )
    assert [board.key for board in prepared] == ["SF 1", "SF 2", "SF 3"]
    assert all(board.ready for board in prepared)
    assert built == ["1111", "2222", SHEET_ID]
    # Google Sheets games aren't cached.
    assert saved == ["1111", "2222", "1111"]
    assert [len(board.media) for board in prepared] == [1, 0, 1]
    assert prepared[0].media[0][1].answer == "A0"
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_a_board_that_wont_load_names_its_missing_games(monkeypatch: object) -> None:
    """A source game that can't be loaded is named in the error."""

    def build(selections: list, games: dict) -> None:
        """Fail to load the second game."""
        games["1111"] = object()
        games["2222"] = None

    monkeypatch.setattr(board_prep, "build_game_from_board_selection_configs", build)
    monkeypatch.setattr(board_prep, "save_game_html", lambda game_id: None)
    board = board_prep.prepare_board(
        "SF 1", "label", [selection("1111"), selection("2222")]
    )
    assert not board.ready
    assert board.error == "Couldn't load the board (couldn't load 2222)."


def test_a_build_error_and_a_cache_error_are_reported(monkeypatch: object) -> None:
    """Exceptions while building or caching become the board's error."""

    def explode(selections: list, games: dict) -> None:
        """Raise like a network failure."""
        raise OSError("offline")

    monkeypatch.setattr(board_prep, "build_game_from_board_selection_configs", explode)
    assert board_prep.prepare_board("k", "l", [selection("1")]).error == (
        "Couldn't load the board: offline"
    )

    def refuse(game_id: str) -> None:
        """Fail to write the cache."""
        raise OSError("disk full")

    monkeypatch.setattr(
        board_prep,
        "build_game_from_board_selection_configs",
        lambda selections, games: game_with_image(None),
    )
    monkeypatch.setattr(board_prep, "save_game_html", refuse)
    board = board_prep.prepare_board("k", "l", [selection("1")])
    assert board.data is not None
    assert not board.ready
    assert board.error == "Couldn't save 1 to the cache."


def test_cancelling_stops_before_the_next_board(monkeypatch: object) -> None:
    """A cancelled run returns the boards prepared so far."""
    monkeypatch.setattr(
        board_prep,
        "build_game_from_board_selection_configs",
        lambda selections, games: game_with_image(None),
    )
    monkeypatch.setattr(board_prep, "save_game_html", lambda game_id: None)
    calls = iter([False, True])
    prepared = board_prep.prepare_boards(
        [("a", "a", [selection("1")]), ("b", "b", [selection("2")])],
        is_cancelled=lambda: next(calls),
    )
    assert [board.key for board in prepared] == ["a"]


def test_build_game_shares_loaded_games(monkeypatch: object) -> None:
    """Building with a shared cache loads each source game once."""
    from jparty.services import game_loader

    loads = []

    def get_game(game_id: str) -> GameData:
        """Count loads."""
        loads.append(game_id)
        return game_with_image(None)

    monkeypatch.setattr(game_loader, "get_game", get_game)
    games: dict = {}
    for _ in range(2):
        data = game_loader.build_game_from_board_selection_configs(
            [{**selection("1111"), "board_type": "jeopardy"}], games
        )
        assert data is not None
    assert loads == ["1111"]
