"""Unit tests for tournament setup: bracket settings, boards, and saving them."""

import json

import pytest

from jparty.domain.roster import PlayerSlot, SignUp, link_sign_up, unlink_sign_up
from jparty.domain.tournament import TournamentOptions, plan_tournament
from jparty.domain.tournament_setup import (
    BracketSettings,
    TournamentBoard,
    assign_board,
    assign_from_pool,
    board_from_selections,
    edited_board,
    forget_removed_players,
    plan_games,
    reconcile_boards,
    shared_board_warnings,
    swap_boards,
    unassign_board,
    with_cant_play,
)
from jparty.domain.tournament_store import (
    PLAYERS_FILE,
    TournamentFileError,
    TournamentSettings,
    load_tournament,
    parse_players_csv,
    players_csv_text,
    save_tournament,
)

pytestmark = pytest.mark.unit


def selection(game_id: str, round_index: int, label: str) -> dict:
    """Return a minimal ``board_selections`` entry."""
    return {
        "game_id": game_id,
        "source_round_index": round_index,
        "source_round_label": label,
        "board_type": "final" if label.startswith("Final") else "standard",
        "row_values": [],
    }


def board(game_id: str, *round_indices: int) -> TournamentBoard:
    """Return a board playing ``round_indices`` of one source game."""
    return TournamentBoard(
        game_id,
        tuple(selection(game_id, index, f"Round {index}") for index in round_indices),
    )


def test_board_labels_name_the_game_or_each_source_round() -> None:
    """A one-game board shows its rounds; a Frankenstein board shows sources."""
    regular = board_from_selections(
        "8123",
        [
            selection("8123", 0, "Jeopardy!"),
            selection("8123", 2, "Final Jeopardy!"),
        ],
    )
    assert regular.label == "8123 (Jeopardy!, Final Jeopardy!)"
    assert regular.source_game_ids == ("8123",)

    mixed = board_from_selections(
        "frankenstein-1-2",
        [selection("1", 0, "Jeopardy!"), selection("2", 2, "Final Jeopardy!")],
    )
    assert mixed.label == "1 Jeopardy! + 2 Final Jeopardy!"
    assert mixed.source_game_ids == ("1", "2")
    assert board_from_selections("8123", []) is None


def test_board_keeps_its_own_copy_of_the_selections() -> None:
    """Later edits to the welcome screen's selections don't change a board."""
    selections = [selection("8123", 0, "Jeopardy!")]
    saved = board_from_selections("8123", selections)
    selections[0]["game_id"] = "changed"
    assert saved.source_game_ids == ("8123",)


def test_game_keys_include_the_round() -> None:
    """Chase games in different rounds get different keys."""
    plan = plan_tournament(
        TournamentOptions(
            14, use_second_round=True, semifinal_byes=6, second_round_players=5
        )
    )
    keys = [key for key, _, _ in plan_games(plan)]
    assert "Preliminaries: Chase 1" in keys
    assert "Second Round: Chase 1" in keys
    assert keys[-1] == "Final: Final"
    assert len(keys) == len(set(keys)) == plan.total_games
    assert plan_games(plan_tournament(TournamentOptions(10))) == []


def test_reconcile_moves_dropped_games_to_the_pool() -> None:
    """Boards for games no longer in the bracket wait in the pool, in order."""
    boards = {"QF 1": board("1", 0), "QF 6": board("6", 0), "Final": board("9", 0)}
    pool = [board("0", 0)]
    kept, new_pool = reconcile_boards(["QF 1", "Final"], boards, pool)
    assert kept == {"QF 1": boards["QF 1"], "Final": boards["Final"]}
    assert new_pool == [pool[0], boards["QF 6"]]


def test_dropped_boards_go_back_when_their_game_returns() -> None:
    """A board returns to its game if it comes back empty, and only then."""
    boards = {"QF 5": board("5", 0), "QF 6": board("6", 0)}
    kept, pool = reconcile_boards(["QF 1"], boards, [])
    assert kept == {}
    assert pool == [boards["QF 5"], boards["QF 6"]]
    assert [item.left_game_key for item in pool] == ["QF 5", "QF 6"]

    # QF 5 comes back empty and gets its board back. QF 6 got a new board
    # while it was out, so it keeps that one, and its old board stops waiting.
    kept, pool = reconcile_boards(
        ["QF 1", "QF 5", "QF 6"], {"QF 6": board("7", 0)}, pool
    )
    assert kept == {"QF 5": boards["QF 5"], "QF 6": board("7", 0)}
    assert kept["QF 5"].left_game_key == ""
    assert pool == [boards["QF 6"]]
    assert pool[0].left_game_key == ""
    kept, pool = reconcile_boards(["QF 1", "QF 5", "QF 6"], {}, pool)
    assert kept == {}


def test_assigning_a_waiting_board_stops_it_waiting() -> None:
    """A pool board the host assigns no longer goes back to its old game."""
    _, pool = reconcile_boards([], {"QF 5": board("5", 0)}, [])
    boards, pool = assign_from_pool({}, pool, 0, "QF 1")
    assert boards["QF 1"].left_game_key == ""
    boards, pool = unassign_board(boards, pool, "QF 1")
    assert reconcile_boards(["QF 5"], {}, pool) == ({}, [board("5", 0)])


def test_assign_unassign_and_pool() -> None:
    """Replaced and removed boards go to the pool; pool boards can come back."""
    first, second = board("1", 0), board("2", 0)
    boards, pool = assign_board({}, [], "QF 1", first)
    boards, pool = assign_board(boards, pool, "QF 1", second)
    assert boards == {"QF 1": second}
    assert pool == [first]

    boards, pool = assign_from_pool(boards, pool, 0, "QF 1")
    assert boards == {"QF 1": first}
    assert pool == [second]

    boards, pool = unassign_board(boards, pool, "QF 1")
    assert boards == {}
    assert pool == [second, first]
    assert unassign_board(boards, pool, "QF 1") == ({}, pool)


def test_swap_boards_handles_a_game_without_a_board() -> None:
    """Swapping with an empty game moves the board over."""
    first, second = board("1", 0), board("2", 0)
    assert swap_boards({"A": first, "B": second}, "A", "B") == {
        "A": second,
        "B": first,
    }
    assert swap_boards({"A": first}, "A", "B") == {"B": first}


def test_shared_board_warnings_compare_source_rounds() -> None:
    """Games warn when they play the same round, not just the same game."""
    boards = {
        "QF 1": board("1", 0, 1),
        "QF 2": board("1", 2),
        "QF 3": board("2", 0),
        "SF 1": board("2", 0, 2),
    }
    keys = ["QF 1", "QF 2", "QF 3", "SF 1"]
    assert shared_board_warnings(keys, boards) == ["QF 3 and SF 1 share a round."]


def test_bracket_settings_json_round_trip_and_bad_values() -> None:
    """Saved bracket options read back; junk falls back to defaults."""
    settings = BracketSettings(True, 3, 18)
    assert BracketSettings.from_json(settings.to_json()) == settings
    assert BracketSettings.from_json(None) == BracketSettings()
    assert BracketSettings.from_json(
        {"use_second_round": 1, "semifinal_byes": "x", "second_round_players": "y"}
    ) == BracketSettings(True, 0, None)
    assert settings.options(30) == TournamentOptions(30, True, 3, 18)


def test_board_from_json_skips_unusable_entries() -> None:
    """Boards without selections can't be played, so they aren't loaded."""
    assert TournamentBoard.from_json({"label": "x"}) is None
    assert TournamentBoard.from_json({"board_selections": ["junk"]}) is None
    assert TournamentBoard.from_json("junk") is None
    saved = board("1", 0, 2)
    assert TournamentBoard.from_json(saved.to_json()) == saved


def test_save_and_load_setup(temp_dir: object) -> None:
    """Bracket options, boards, and the pool survive a save and load."""
    settings = TournamentSettings(
        "Fun",
        bracket=BracketSettings(True, 3, 18),
        boards={"Quarterfinals: QF 1": board("1", 0, 1, 2)},
        unassigned_boards=[board("2", 0)],
    )
    save_tournament(temp_dir, settings, [PlayerSlot("Jane")])
    loaded, _slots = load_tournament(temp_dir / "Fun")
    assert loaded.bracket == settings.bracket
    assert loaded.boards == settings.boards
    assert loaded.unassigned_boards == settings.unassigned_boards
    payload = json.loads((temp_dir / "Fun" / "tournament.json").read_text("utf-8"))
    assert payload["format_version"] == 2


def test_version_one_files_load_with_an_empty_setup(temp_dir: object) -> None:
    """Tournaments saved before the setup screen still load."""
    folder = temp_dir / "Old"
    folder.mkdir()
    (folder / "players.csv").write_text("actual_name\nJane\n", encoding="utf-8")
    (folder / "tournament.json").write_text(
        json.dumps({"format_version": 1, "name": "Old", "sheet_url": "s"}),
        encoding="utf-8",
    )
    settings, slots = load_tournament(folder)
    assert settings.sheet_url == "s"
    assert settings.bracket == BracketSettings()
    assert settings.boards == {}
    assert settings.unassigned_boards == []
    assert settings.logo_file == ""
    assert slots == [PlayerSlot("Jane")]


def test_logo_is_copied_replaced_and_removed(temp_dir: object) -> None:
    """The logo lives in the folder; a new one replaces it; clearing removes it."""
    png = temp_dir / "pick.png"
    png.write_bytes(b"png bytes")
    jpg = temp_dir / "pick.JPG"
    jpg.write_bytes(b"jpg bytes")
    root = temp_dir / "tournaments"
    settings = TournamentSettings("Fun")
    save_tournament(root, settings, [], logo_source=png)
    folder = root / "Fun"
    assert settings.logo_file == "logo.png"
    assert (folder / "logo.png").read_bytes() == b"png bytes"
    assert load_tournament(folder)[0].logo_file == "logo.png"

    save_tournament(root, settings, [], logo_source=jpg)
    assert settings.logo_file == "logo.jpg"
    assert not (folder / "logo.png").exists()
    assert (folder / "logo.jpg").read_bytes() == b"jpg bytes"

    settings.logo_file = ""
    save_tournament(root, settings, [])
    assert not (folder / "logo.jpg").exists()
    assert load_tournament(folder)[0].logo_file == ""


def test_bad_or_missing_logos(temp_dir: object) -> None:
    """A non-image logo is refused; a logo deleted by hand loads as none."""
    text = temp_dir / "notes.txt"
    text.write_text("hi", encoding="utf-8")
    with pytest.raises(TournamentFileError, match="image"):
        save_tournament(temp_dir, TournamentSettings("Fun"), [], logo_source=text)
    assert not (temp_dir / "Fun").exists()

    png = temp_dir / "pick.png"
    png.write_bytes(b"png")
    save_tournament(temp_dir, TournamentSettings("Fun"), [], logo_source=png)
    (temp_dir / "Fun" / "logo.png").unlink()
    assert load_tournament(temp_dir / "Fun")[0].logo_file == ""


def test_player_ids_survive_renames_links_and_unlinks() -> None:
    """Every roster change keeps a player's id; ids don't affect equality."""
    slot = PlayerSlot("Jane")
    linked = link_sign_up(slot, SignUp("t1", "jane doe"))
    assert linked.player_id == slot.player_id
    assert unlink_sign_up(linked).player_id == slot.player_id
    assert PlayerSlot("Jane") == slot
    assert PlayerSlot().player_id != PlayerSlot().player_id


def test_players_csv_keeps_ids_and_fills_missing_ones() -> None:
    """Saved ids read back; old files and copied rows get new ones."""
    slots = [PlayerSlot("Ann"), PlayerSlot("Bob", SignUp("t1", "Bob"))]
    reread = parse_players_csv(players_csv_text(slots))
    assert [slot.player_id for slot in reread] == [slot.player_id for slot in slots]

    old = parse_players_csv("actual_name\nAnn\nBob\n")
    assert all(slot.player_id for slot in old)
    assert old[0].player_id != old[1].player_id

    copied = parse_players_csv("actual_name,player_id\nAnn,abc\nAnnie,abc\n")
    assert copied[0].player_id == "abc"
    assert copied[1].player_id != "abc"


def test_cant_play_round_trips_and_ignores_junk() -> None:
    """Exclusions save with the board; repeats and bad values are cleaned up."""
    saved = TournamentBoard("b", board("1", 0).board_selections, ("a", "b"))
    assert TournamentBoard.from_json(saved.to_json()) == saved
    payload = saved.to_json()
    payload["cant_play"] = ["a", "a", 3]
    assert TournamentBoard.from_json(payload).cant_play == ("a", "3")
    payload["cant_play"] = "a"
    assert TournamentBoard.from_json(payload).cant_play == ()


def test_cant_play_helpers() -> None:
    """Set, carry over on edit, and forget removed players."""
    first = with_cant_play(board("1", 0), ["b", "a", "b"])
    assert first.cant_play == ("b", "a")
    edited = edited_board(first, board("2", 0))
    assert edited.source_game_ids == ("2",)
    assert edited.cant_play == ("b", "a")
    assert edited_board(None, board("2", 0)).cant_play == ()

    boards, pool = forget_removed_players(
        {"Final": first}, [with_cant_play(board("3", 0), ["a"])], ["a"]
    )
    assert boards["Final"].cant_play == ("a",)
    assert pool[0].cant_play == ("a",)
    _boards, pool = forget_removed_players({}, pool, [])
    assert pool[0].cant_play == ()


def test_players_file_has_player_ids(temp_dir: object) -> None:
    """players.csv gains a player_id column."""
    save_tournament(temp_dir, TournamentSettings("Fun"), [PlayerSlot("Ann")])
    header = (temp_dir / "Fun" / PLAYERS_FILE).read_text("utf-8").splitlines()[0]
    assert header.endswith(",player_id")
