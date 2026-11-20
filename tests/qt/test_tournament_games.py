"""Qt tests for a tournament's Games and Bracket tabs and saving the setup."""

import pytest
from PyQt6.QtCore import QItemSelectionModel, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QDialog

from jparty.domain.tournament.bracket import TournamentOptions, plan_tournament
from jparty.domain.tournament.roster import PlayerSlot
from jparty.domain.tournament.setup import BracketSettings, TournamentBoard
from jparty.domain.tournament.store import (
    TournamentSettings,
    load_tournament,
    save_tournament,
)
from jparty.ui.widgets import tournament_editor
from jparty.ui.widgets.tournament_editor import TAB_BRACKET, TAB_GAMES
from jparty.ui.widgets.tournament_games import (
    COLUMN_BOARD,
    COLUMN_CANT_PLAY,
    COLUMN_GAME,
    COLUMN_MEDIA,
    NEW_POOL_BOARD_TARGET,
    NO_BOARD_TEXT,
    GamesEditor,
    PlayerChecklistDialog,
    choose_cant_play,
)
from jparty.ui.widgets.tournament_roster import COLUMN_ACTUAL_NAME
from tests.qt.test_tournament_roster import FakeFetcher, make_editor

pytestmark = pytest.mark.qt


def board(game_id: str) -> TournamentBoard:
    """Return a one-round board from ``game_id``."""
    return TournamentBoard(
        f"{game_id} (Jeopardy!)",
        (
            {
                "game_id": game_id,
                "source_round_index": 0,
                "source_round_label": "Jeopardy!",
                "board_type": "standard",
                "row_values": [200, 400, 600, 800, 1000],
            },
        ),
    )


def select_rows(table: object, *rows: int) -> None:
    """Select whole table rows."""
    table.clearSelection()
    model = table.selectionModel()
    for row in rows:
        model.select(
            table.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )


def cell(editor: GamesEditor, row: int, column: int) -> str:
    """Return a games-table cell's text."""
    return editor.table.item(row, column).text()


def make_games(qtbot: object, players: int = 9, **kwargs: object) -> GamesEditor:
    """Return a games editor showing the bracket for ``players`` players."""
    games = GamesEditor(**kwargs)
    qtbot.addWidget(games)
    games.set_plan(plan_tournament(TournamentOptions(players)))
    return games


def test_games_list_every_bracket_game(qtbot: object) -> None:
    """Each game is a row, unassigned to start."""
    games = make_games(qtbot, missing_media=lambda _board: [])
    assert games.table.rowCount() == 4
    assert cell(games, 0, COLUMN_GAME) == "Semifinals: SF 1"
    assert cell(games, 3, COLUMN_GAME) == "Final: Final"
    assert cell(games, 0, COLUMN_BOARD) == NO_BOARD_TEXT
    assert "0 of 4 games have a board" in games.summary_label.text()
    # With no game selected, Set Board adds a board to the pool.
    assert games.set_board_button.isEnabled()
    assert not games.cant_play_button.isEnabled()
    select_rows(games.table, 0, 1)
    assert not games.set_board_button.isEnabled()


class FakePicker:
    """Stand in for the board picker dialog."""

    def __init__(self, *boards: TournamentBoard | None) -> None:
        """Return ``boards`` from successive picks; ``None`` is a cancel."""
        self.boards = list(boards)
        self.calls = []

    def __call__(
        self, key: str, current: TournamentBoard | None, _parent: object
    ) -> TournamentBoard | None:
        """Record the game and its current board, and return the next pick."""
        self.calls.append((key, current))
        return self.boards.pop(0)


def test_set_board_and_media_column(qtbot: object) -> None:
    """Set Board stores the pick; missing media is listed; cancel changes nothing."""
    picker = FakePicker(board("8123"), board("7000"), None)
    games = make_games(
        qtbot,
        pick_board=picker,
        missing_media=lambda b: ["8123"] if "8123" in b.source_game_ids else [],
    )
    changes = []
    games.games_changed.connect(lambda: changes.append(1))
    select_rows(games.table, 0)
    games.set_board_button.click()
    games.on_cell_double_clicked(1, COLUMN_BOARD)
    assert picker.calls == [
        ("Semifinals: SF 1", None),
        ("Semifinals: SF 2", None),
    ]
    assert cell(games, 0, COLUMN_BOARD) == "8123 (Jeopardy!)"
    assert cell(games, 0, COLUMN_MEDIA) == "None for 8123"
    assert cell(games, 1, COLUMN_MEDIA) == "Yes"
    assert "No question media: Semifinals: SF 1." in games.summary_label.text()
    assert "2 of 4 games have a board" in games.summary_label.text()
    assert changes == [1, 1]

    # A cancelled pick changes nothing.
    games.on_cell_double_clicked(1, COLUMN_BOARD)
    assert picker.calls[-1] == ("Semifinals: SF 2", board("7000"))
    assert games.boards["Semifinals: SF 2"] == board("7000")
    assert changes == [1, 1]


def test_editing_a_board_replaces_it(qtbot: object) -> None:
    """The picker gets the current board, and the edit replaces it in place."""
    picker = FakePicker(board("8124"))
    games = make_games(qtbot, pick_board=picker, missing_media=lambda _board: [])
    games.set_boards({"Final: Final": board("8123")}, [])
    games.table.cellDoubleClicked.emit(3, 0)
    assert picker.calls == [("Final: Final", board("8123"))]
    assert games.boards == {"Final: Final": board("8124")}
    assert games.unassigned == []


def test_swap_unassign_and_assign_from_pool(qtbot: object) -> None:
    """Boards can be swapped, unassigned, reassigned, and deleted."""
    games = make_games(qtbot, missing_media=lambda _board: [])
    games.set_boards({"Semifinals: SF 1": board("1")}, [board("2")])
    select_rows(games.table, 0, 1)
    assert games.swap_button.isEnabled()
    games.swap_button.click()
    assert games.boards == {"Semifinals: SF 2": board("1")}

    select_rows(games.table, 1)
    games.unassign_button.click()
    assert games.boards == {}
    assert games.unassigned == [board("2"), board("1")]
    assert games.pool_label.text() == "Unassigned boards (2):"

    select_rows(games.table, 3)
    games.pool_list.setCurrentRow(1)
    assert games.assign_pool_button.isEnabled()
    games.assign_pool_button.click()
    assert games.boards == {"Final: Final": board("1")}

    games.pool_list.setCurrentRow(0)
    games.delete_pool_button.click()
    assert games.unassigned == []


def test_shrinking_bracket_moves_boards_to_the_pool(qtbot: object) -> None:
    """Dropped games' boards are unassigned; an invalid plan keeps them."""
    games = make_games(qtbot, players=12, missing_media=lambda _board: [])
    games.set_boards(
        {"Quarterfinals: QF 4": board("4"), "Final: Final": board("9")}, []
    )
    games.set_plan(plan_tournament(TournamentOptions(10)))
    assert set(games.boards) == {"Quarterfinals: QF 4", "Final: Final"}
    assert "Fix the bracket" in games.summary_label.text()
    assert games.table.rowCount() == 0

    games.set_plan(plan_tournament(TournamentOptions(11)))
    assert games.boards == {"Final: Final": board("9")}
    assert games.unassigned == [board("4")]


def test_boards_come_back_when_the_player_count_does(qtbot: object) -> None:
    """15 -> 16 -> 15 players puts QF 5's board back on QF 5."""
    games = make_games(qtbot, players=15, missing_media=lambda _board: [])
    assigned = {key: board(str(index)) for index, key in enumerate(games._game_keys)}
    assert "Quarterfinals: QF 5" in assigned
    games.set_boards(assigned, [])
    changes = []
    games.games_changed.connect(lambda: changes.append(1))

    games.set_plan(plan_tournament(TournamentOptions(16)))
    assert "Quarterfinals: QF 5" not in games.boards
    assert games.unassigned == [assigned["Quarterfinals: QF 5"]]
    games.set_plan(plan_tournament(TournamentOptions(15)))
    assert games.boards == assigned
    assert games.unassigned == []
    assert len(changes) == 2


def test_second_round_and_boards_survive_a_small_field(
    qtbot: object, temp_dir: object
) -> None:
    """23 -> 9 -> 23 players brings back the second round and every board."""
    editor = make_editor(qtbot, temp_dir, FakeFetcher())
    editor.roster.player_spinbox.setValue(23)
    editor.bracket.second_round_checkbox.setChecked(True)
    editor.bracket.byes_spinbox.setValue(3)
    assert editor.bracket.plan.valid
    keys = editor.games._game_keys
    assigned = {key: board(str(index)) for index, key in enumerate(keys)}
    editor.games.set_boards(assigned, [])

    editor.roster.player_spinbox.setValue(9)
    assert not editor.bracket.second_round_checkbox.isChecked()
    editor.roster.player_spinbox.setValue(23)
    assert editor.bracket.second_round_checkbox.isChecked()
    assert editor.bracket.byes_spinbox.value() == 3
    assert editor.games.boards == assigned
    assert editor.games.unassigned == []


def test_editor_saves_bracket_and_boards(qtbot: object, temp_dir: object) -> None:
    """The Bracket tab follows the roster, and Save writes the whole setup."""
    editor = make_editor(
        qtbot,
        temp_dir,
        FakeFetcher(),
        pick_board=FakePicker(board("8123")),
    )
    editor.name_edit.setText("Fun")
    editor.roster.player_spinbox.setValue(30)
    assert editor.bracket.player_spinbox.value() == 30
    assert editor.tabs.tabText(TAB_BRACKET) == "Bracket (!)"
    editor.bracket.second_round_checkbox.setChecked(True)
    editor.bracket.byes_spinbox.setValue(3)
    assert editor.tabs.tabText(TAB_BRACKET) == "Bracket"
    assert editor.tabs.tabText(TAB_GAMES) == "Games (0/20 boards, 0 unassigned)"

    editor.games.on_cell_double_clicked(19, COLUMN_BOARD)
    assert editor.tabs.tabText(TAB_GAMES) == "Games (1/20 boards, 0 unassigned)"
    for row in range(30):
        editor.roster.table.item(row, 1).setText(f"Player {row}")
    editor.buttons.button(editor.buttons.StandardButton.Save).click()
    assert editor.status_label.text() == "Saved."

    settings, slots = load_tournament(temp_dir / "Fun")
    assert len(slots) == 30
    assert settings.bracket == BracketSettings(True, 3, 18)
    assert settings.boards == {"Final: Final": board("8123")}


def test_loaded_setup_is_shown_and_tracked(qtbot: object, temp_dir: object) -> None:
    """A saved setup opens as saved, and changing it counts as unsaved."""
    settings = TournamentSettings(
        "Fun",
        bracket=BracketSettings(True, 3, 18),
        boards={"Final: Final": board("1")},
    )
    slots = [PlayerSlot(f"P{index}") for index in range(30)]
    save_tournament(temp_dir, settings, slots)
    loaded, loaded_slots = load_tournament(temp_dir / "Fun")
    editor = make_editor(
        qtbot, temp_dir, FakeFetcher(), settings=loaded, slots=loaded_slots
    )
    assert editor.bracket.byes_spinbox.value() == 3
    assert editor.games.boards == {"Final: Final": board("1")}
    assert not editor.has_unsaved_changes()
    # A swap changes only the assignments, not the unassigned pool.
    select_rows(editor.games.table, 0, editor.games.table.rowCount() - 1)
    editor.games.swap_button.click()
    assert editor.has_unsaved_changes()
    editor.games.swap_button.click()
    assert not editor.has_unsaved_changes()
    editor.bracket.byes_spinbox.setValue(2)
    assert editor.has_unsaved_changes()


def test_saving_an_unworkable_bracket_warns(qtbot: object, temp_dir: object) -> None:
    """A roster that can't make a bracket yet still saves, with a warning."""
    editor = make_editor(qtbot, temp_dir, FakeFetcher())
    editor.name_edit.setText("Fun")
    editor.roster.player_spinbox.setValue(10)
    editor.buttons.button(editor.buttons.StandardButton.Save).click()
    assert "won't work yet" in editor.status_label.text()
    assert (temp_dir / "Fun" / "tournament.json").is_file()


def test_logo_preview_and_save(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """A chosen logo is copied on save; removing it deletes the file."""
    png = temp_dir / "pick.png"
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(0)
    image.save(str(png))
    monkeypatch.setattr(
        tournament_editor.QFileDialog,
        "getOpenFileName",
        lambda *_args: (str(png), ""),
    )
    editor = make_editor(qtbot, temp_dir / "tournaments", FakeFetcher())
    editor.name_edit.setText("Fun")
    assert editor.logo_preview.text() == "No logo"
    editor.choose_logo_button.click()
    assert not editor.logo_preview.pixmap().isNull()
    assert editor.has_unsaved_changes()
    editor.buttons.button(editor.buttons.StandardButton.Save).click()
    folder = temp_dir / "tournaments" / "Fun"
    assert (folder / "logo.png").is_file()
    assert load_tournament(folder)[0].logo_file == "logo.png"

    editor.remove_logo_button.click()
    editor.buttons.button(editor.buttons.StandardButton.Save).click()
    assert not (folder / "logo.png").exists()


class FakeChooser:
    """Stand in for the Can't Play checklist."""

    def __init__(self, *answers: list[str] | None) -> None:
        """Return ``answers`` from successive asks; ``None`` is a cancel."""
        self.answers = list(answers)
        self.calls = []

    def __call__(
        self, title: str, players: list, checked: tuple, _parent: object
    ) -> list[str] | None:
        """Record what the checklist would show, and return the next answer."""
        self.calls.append((title, list(players), tuple(checked)))
        return self.answers.pop(0)


PLAYERS = [("ann-id", "Ann"), ("bob-id", "Bob"), ("cy-id", "Cy")]


def test_cant_play_checklist_ticks_and_reports_players(qtbot: object) -> None:
    """The checklist starts with the board's players ticked and reports ticks."""
    dialog = PlayerChecklistDialog("Can't Play: Final", PLAYERS, ["cy-id"])
    qtbot.addWidget(dialog)
    items = [dialog.player_list.item(row) for row in range(dialog.player_list.count())]
    assert [item.text() for item in items] == ["Ann", "Bob", "Cy"]
    assert [item.checkState() for item in items] == [
        Qt.CheckState.Unchecked,
        Qt.CheckState.Unchecked,
        Qt.CheckState.Checked,
    ]
    assert dialog.checked_ids() == ["cy-id"]
    items[0].setCheckState(Qt.CheckState.Checked)
    assert dialog.checked_ids() == ["ann-id", "cy-id"]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [(QDialog.DialogCode.Accepted, ["bob-id"]), (QDialog.DialogCode.Rejected, None)],
)
def test_choose_cant_play_returns_ticks_or_none(
    monkeypatch: object, answer: object, expected: list[str] | None
) -> None:
    """OK returns the ticked ids; Cancel returns ``None``."""
    monkeypatch.setattr(PlayerChecklistDialog, "exec", lambda _self: answer)
    assert choose_cant_play("Can't Play", PLAYERS, ["bob-id"]) == expected


def test_set_board_with_no_game_selected_adds_to_the_pool(qtbot: object) -> None:
    """A board set up with no game selected goes to Unassigned."""
    picker = FakePicker(board("7000"), None)
    games = make_games(qtbot, pick_board=picker, missing_media=lambda _board: [])
    games.set_board_button.click()
    assert picker.calls == [(NEW_POOL_BOARD_TARGET, None)]
    assert games.boards == {}
    assert games.unassigned == [board("7000")]
    assert games.pool_label.text() == "Unassigned boards (1):"
    games.set_board_button.click()
    assert games.unassigned == [board("7000")]


def test_cant_play_follows_its_board(qtbot: object) -> None:
    """Exclusions show by name and move with the board."""
    chooser = FakeChooser(["bob-id", "ann-id"], None)
    picker = FakePicker(board("8124"))
    games = make_games(
        qtbot,
        pick_board=picker,
        choose_cant_play=chooser,
        missing_media=lambda _board: [],
    )
    games.set_players(PLAYERS)
    games.set_boards({"Semifinals: SF 1": board("1")}, [])
    select_rows(games.table, 0)
    games.cant_play_button.click()
    assert chooser.calls == [("Can't Play: Semifinals: SF 1", PLAYERS, ())]
    assert cell(games, 0, COLUMN_CANT_PLAY) == "Bob, Ann"

    # Cancel keeps them.
    games.on_cell_double_clicked(0, COLUMN_CANT_PLAY)
    assert chooser.calls[-1][2] == ("bob-id", "ann-id")
    assert cell(games, 0, COLUMN_CANT_PLAY) == "Bob, Ann"

    # Editing the board keeps who can't play it.
    games.on_cell_double_clicked(0, COLUMN_BOARD)
    assert games.boards["Semifinals: SF 1"].source_game_ids == ("8124",)
    assert games.boards["Semifinals: SF 1"].cant_play == ("bob-id", "ann-id")

    # Swapping and unassigning carry them along.
    select_rows(games.table, 0, 1)
    games.swap_button.click()
    assert cell(games, 1, COLUMN_CANT_PLAY) == "Bob, Ann"
    assert cell(games, 0, COLUMN_CANT_PLAY) == ""
    select_rows(games.table, 1)
    games.unassign_button.click()
    assert games.pool_list.item(0).text() == "8124 (Jeopardy!) (can't play: Bob, Ann)"

    # Names follow the roster.
    games.set_players([("ann-id", "Annie"), ("bob-id", "Bob")])
    assert games.pool_list.item(0).text() == "8124 (Jeopardy!) (can't play: Bob, Annie)"


def test_cant_play_needs_a_board(qtbot: object) -> None:
    """A game without a board has no one to exclude."""
    chooser = FakeChooser()
    picker = FakePicker(None)
    games = make_games(
        qtbot, pick_board=picker, choose_cant_play=chooser, missing_media=lambda _b: []
    )
    select_rows(games.table, 0)
    assert not games.cant_play_button.isEnabled()
    # Double-clicking an empty Can't Play cell sets the board instead.
    games.on_cell_double_clicked(0, COLUMN_CANT_PLAY)
    assert chooser.calls == []
    assert picker.calls == [("Semifinals: SF 1", None)]


def test_cant_play_is_saved_and_forgets_removed_players(
    qtbot: object, temp_dir: object
) -> None:
    """Exclusions survive save and load, and drop players who left the roster."""
    slots = [PlayerSlot(f"P{index}") for index in range(9)]
    keep, gone = slots[0].player_id, slots[8].player_id
    save_tournament(
        temp_dir,
        TournamentSettings(
            "Fun",
            boards={
                "Final: Final": TournamentBoard(
                    "b", board("1").board_selections, (keep, gone)
                )
            },
            unassigned_boards=[
                TournamentBoard("u", board("2").board_selections, (gone,))
            ],
        ),
        slots,
    )
    loaded, loaded_slots = load_tournament(temp_dir / "Fun")
    assert [slot.player_id for slot in loaded_slots] == [
        slot.player_id for slot in slots
    ]
    editor = make_editor(
        qtbot, temp_dir, FakeFetcher(), settings=loaded, slots=loaded_slots
    )
    assert cell(editor.games, 3, COLUMN_CANT_PLAY) == "P0, P8"
    assert editor.tabs.tabText(TAB_GAMES) == "Games (1/4 boards, 1 unassigned)"

    # Renaming a player keeps their exclusions.
    editor.roster.table.item(0, COLUMN_ACTUAL_NAME).setText("Zed")
    assert cell(editor.games, 3, COLUMN_CANT_PLAY) == "Zed, P8"

    editor.roster.table.selectRow(8)
    editor.roster.remove_button.click()
    assert cell(editor.games, 3, COLUMN_CANT_PLAY) == "Zed"
    editor.buttons.button(editor.buttons.StandardButton.Save).click()
    saved, _slots = load_tournament(temp_dir / "Fun")
    assert saved.boards["Final: Final"].cant_play == (keep,)
    assert saved.unassigned_boards[0].cant_play == ()


def test_cant_play_on_an_unassigned_board(qtbot: object) -> None:
    """Unassigned boards take exclusions too, and keep them when assigned."""
    chooser = FakeChooser(["cy-id"], None, ["ann-id", "cy-id"])
    games = make_games(qtbot, choose_cant_play=chooser, missing_media=lambda _b: [])
    games.set_players(PLAYERS)
    games.set_boards({}, [board("1"), board("2")])
    assert not games.pool_cant_play_button.isEnabled()

    games.pool_list.setCurrentRow(1)
    games.pool_cant_play_button.click()
    assert chooser.calls[-1] == ("Can't Play: 2 (Jeopardy!)", PLAYERS, ())
    assert games.unassigned[1].cant_play == ("cy-id",)
    assert games.unassigned[0].cant_play == ()
    assert games.pool_list.item(1).text() == "2 (Jeopardy!) (can't play: Cy)"
    assert games.pool_list.currentRow() == 1

    # A cancelled checklist changes nothing; double-click opens it too.
    games.pool_list.itemDoubleClicked.emit(games.pool_list.item(1))
    assert chooser.calls[-1][2] == ("cy-id",)
    assert games.unassigned[1].cant_play == ("cy-id",)
    games.pool_list.itemDoubleClicked.emit(games.pool_list.item(1))
    assert games.unassigned[1].cant_play == ("ann-id", "cy-id")

    select_rows(games.table, 0)
    games.pool_list.setCurrentRow(1)
    games.assign_pool_button.click()
    assert cell(games, 0, COLUMN_CANT_PLAY) == "Ann, Cy"
    assert games.unassigned == [board("1")]
