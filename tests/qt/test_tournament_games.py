"""Qt tests for a tournament's Games and Bracket tabs and saving the setup."""

import pytest
from PyQt6.QtCore import QItemSelectionModel
from PyQt6.QtGui import QImage

from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament import TournamentOptions, plan_tournament
from jparty.domain.tournament_setup import BracketSettings, TournamentBoard
from jparty.domain.tournament_store import (
    TournamentSettings,
    load_tournament,
    save_tournament,
)
from jparty.ui.widgets import tournament_editor
from jparty.ui.widgets.tournament_editor import TAB_BRACKET, TAB_GAMES
from jparty.ui.widgets.tournament_games import (
    COLUMN_BOARD,
    COLUMN_GAME,
    COLUMN_MEDIA,
    NO_BOARD_TEXT,
    GamesEditor,
)
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
    games.set_board_for_row(1)
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
    games.set_board_for_row(1)
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
    assert editor.tabs.tabText(TAB_GAMES) == "Games (0/20 boards)"

    editor.games.set_board_for_row(19)
    assert editor.tabs.tabText(TAB_GAMES) == "Games (1/20 boards)"
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
