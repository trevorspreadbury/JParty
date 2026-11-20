"""Qt tests for the tournament roster (Players tab) and its save flow."""

import pytest
import requests
from PyQt6.QtCore import QPoint, QSize
from PyQt6.QtWidgets import QDialog, QMessageBox

from jparty.domain.tournament.roster import (
    MATCH_ADD_PLAYER,
    MATCH_IGNORE,
    PlayerSlot,
    SignUp,
    SignUpMatch,
)
from jparty.domain.tournament.store import (
    TournamentSettings,
    load_tournament,
    save_tournament,
)
from jparty.services.game_sources import SheetAccessError
from jparty.ui.widgets.tournament_editor import TournamentEditor
from jparty.ui.widgets.tournament_roster import COLUMN_ACTUAL_NAME, SignUpMatchDialog
from jparty.ui.widgets.tournament_window import TournamentWindow

pytestmark = pytest.mark.qt

HEADER = ["Timestamp", "Full Name", "Occupation", "Hometown", "Anecdote #1"]
SHEET_LINK = "https://docs.google.com/spreadsheets/d/abc/edit"


class FakeFetcher:
    """Return canned sheet rows, or raise a canned error."""

    def __init__(
        self, rows: list | None = None, error: Exception | None = None
    ) -> None:
        """Store what each fetch returns."""
        self.rows = rows or [HEADER]
        self.error = error
        self.links = []

    def get_sheet_rows_from_link(self, link: str) -> list:
        """Record the link and return the rows."""
        self.links.append(link)
        if self.error is not None:
            raise self.error
        return self.rows


def run_inline(target: object) -> None:
    """Run background work immediately, so results arrive synchronously."""
    target()


def no_missing_media(_board: object) -> list[str]:
    """Pretend every board has question media."""
    return []


def make_editor(
    qtbot: object, root: object, fetcher: FakeFetcher, **kwargs: object
) -> TournamentEditor:
    """Return a tournament editor whose roster fetches from ``fetcher``."""
    editor = TournamentEditor(
        root,
        fetcher=fetcher,
        run_async=run_inline,
        missing_media=no_missing_media,
        **kwargs,
    )
    qtbot.addWidget(editor)
    return editor


def actual_names(editor: TournamentEditor) -> list[str]:
    """Return the Actual Name column as shown."""
    table = editor.roster.table
    return [
        table.item(row, COLUMN_ACTUAL_NAME).text() for row in range(table.rowCount())
    ]


def click_save(editor: TournamentEditor) -> None:
    """Click the editor's Save button."""
    editor.buttons.button(editor.buttons.StandardButton.Save).click()


def test_create_from_sheet_fills_slots_and_saves(
    qtbot: object, temp_dir: object
) -> None:
    """A first refresh fills the slots; Save writes the tournament folder."""
    fetcher = FakeFetcher(
        [
            HEADER,
            ["t1", "jane doe", "Pilot", "Boise", "Flew"],
            ["t2", "BOB", "", "", ""],
        ]
    )
    editor = make_editor(qtbot, temp_dir, fetcher)
    editor.name_edit.setText("Family Fun")
    editor.roster.sheet_edit.setText(SHEET_LINK)
    editor.roster.player_spinbox.setValue(5)
    editor.roster.refresh_button.click()

    assert fetcher.links == [SHEET_LINK]
    assert actual_names(editor) == ["Jane Doe", "Bob", "", "", ""]
    assert "Found 2 sign-ups" in editor.roster.status_label.text()

    click_save(editor)
    settings, slots = load_tournament(temp_dir / "Family Fun")
    assert settings.sheet_url == SHEET_LINK
    assert len(slots) == 5
    assert slots[0].sign_up.occupation == "Pilot"
    assert editor.saved_folder == temp_dir / "Family Fun"
    assert not editor.creating
    assert editor.name_edit.isReadOnly()
    assert not editor.has_unsaved_changes()


def test_typed_names_are_kept_and_count_cannot_drop_below_them(
    qtbot: object, temp_dir: object
) -> None:
    """Typed names are saved, and filled slots can't be removed."""
    editor = make_editor(qtbot, temp_dir, FakeFetcher())
    editor.roster.player_spinbox.setValue(4)
    editor.roster.table.item(2, COLUMN_ACTUAL_NAME).setText("Carol")
    assert editor.roster.slots[2].actual_name == "Carol"
    assert editor.roster.player_spinbox.minimum() == 3
    editor.roster.player_spinbox.setValue(10)
    assert len(editor.roster.slots) == 10
    editor.roster.player_spinbox.setValue(3)
    assert actual_names(editor) == ["", "", "Carol"]


def test_refresh_after_typing_names_asks_to_match(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """New sign-ups are matched to typed names through the match dialog."""
    fetcher = FakeFetcher([HEADER, ["t1", "Jane Q Doe", "", "", ""], ["t2", "lol"]])
    slots = [PlayerSlot("Jane Doe"), PlayerSlot("Bob"), PlayerSlot("Carol")]
    editor = make_editor(
        qtbot,
        temp_dir,
        fetcher,
        settings=TournamentSettings("Fun", SHEET_LINK),
        slots=slots,
    )
    shown = []

    def accept_with_last_ignored(match_dialog: SignUpMatchDialog) -> int:
        """Keep the suggestions, but ignore the joke response."""
        shown.append([match.suggested_slot for match in match_dialog.matches])
        match_dialog.selected[1] = MATCH_IGNORE
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SignUpMatchDialog, "exec", accept_with_last_ignored)
    editor.roster.refresh_button.click()

    assert shown == [[0, None]]
    assert editor.roster.slots[0].sign_up.timestamp == "t1"
    assert actual_names(editor) == ["Jane Doe", "Bob", "Carol"]
    assert editor.roster.settings.ignored_sign_ups == ["t2"]

    # The ignored response isn't asked about again.
    shown.clear()
    editor.roster.refresh_button.click()
    assert shown == []


def test_cancelled_match_leaves_sign_ups_for_next_time(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """Cancelling the match dialog places nothing and says so."""
    fetcher = FakeFetcher([HEADER, ["t1", "Jane"]])
    editor = make_editor(
        qtbot,
        temp_dir,
        fetcher,
        settings=TournamentSettings("Fun", SHEET_LINK),
        slots=[PlayerSlot("Jane"), PlayerSlot(), PlayerSlot()],
    )
    monkeypatch.setattr(
        SignUpMatchDialog, "exec", lambda _self: QDialog.DialogCode.Rejected
    )
    editor.roster.refresh_button.click()
    assert editor.roster.slots[0].sign_up is None
    assert "1 not placed yet" in editor.roster.status_label.text()


def test_sheet_errors_are_shown(qtbot: object, temp_dir: object) -> None:
    """Fetch problems are shown, and the button works again afterwards."""
    fetcher = FakeFetcher(error=SheetAccessError("Share the sheet"))
    editor = make_editor(qtbot, temp_dir, fetcher)
    editor.roster.refresh_button.click()
    assert "Paste the link" in editor.roster.status_label.text()
    editor.roster.sheet_edit.setText(SHEET_LINK)
    editor.roster.refresh_button.click()
    assert editor.roster.status_label.text() == "Share the sheet"
    assert editor.roster.refresh_button.isEnabled()


def test_save_rejects_duplicate_and_existing_names(
    qtbot: object, temp_dir: object
) -> None:
    """Players need different names, and a new tournament a new folder."""
    save_tournament(temp_dir, TournamentSettings("Taken"), [])
    editor = make_editor(qtbot, temp_dir, FakeFetcher())
    save = editor.buttons.button(editor.buttons.StandardButton.Save)
    save.click()
    assert "Enter a tournament name" in editor.status_label.text()
    editor.name_edit.setText("Taken")
    save.click()
    assert "already exists" in editor.status_label.text()
    editor.name_edit.setText("New")
    editor.roster.table.item(0, COLUMN_ACTUAL_NAME).setText("Ann")
    editor.roster.table.item(1, COLUMN_ACTUAL_NAME).setText("ann")
    save.click()
    assert "both named" in editor.status_label.text()
    assert not (temp_dir / "New").exists()


def test_match_dialog_steps_through_and_blocks_reused_slots(qtbot: object) -> None:
    """A slot chosen for one sign-up isn't offered for the next."""
    slots = [PlayerSlot("Jane"), PlayerSlot()]
    matches = [
        SignUpMatch(SignUp("t1", "Jane"), 0),
        SignUpMatch(SignUp("t2", "Someone"), 0),
    ]
    dialog = SignUpMatchDialog(slots, matches, [0, 1])
    qtbot.addWidget(dialog)
    assert dialog.choice_combo.currentData() == 0
    assert not dialog.back_button.isEnabled()
    dialog.next_button.click()
    offered = [
        dialog.choice_combo.itemData(i) for i in range(dialog.choice_combo.count())
    ]
    assert offered == [1, MATCH_ADD_PLAYER, MATCH_IGNORE]
    assert dialog.choice_combo.currentData() == MATCH_ADD_PLAYER
    assert dialog.next_button.text() == "Finish"
    dialog.next_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert [choice for _, choice in dialog.choices()] == [0, MATCH_ADD_PLAYER]


def test_resubmitted_sign_up_is_relinked_to_its_player(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """A row replacing one that left the sheet is offered for the old slot."""
    old = SignUp("old", "Jane Doe", "Pilot")
    fetcher = FakeFetcher([HEADER, ["new", "Jane Doe", "Chef", "", ""]])
    editor = make_editor(
        qtbot,
        temp_dir,
        fetcher,
        settings=TournamentSettings("Fun", SHEET_LINK),
        slots=[PlayerSlot("Jane Doe", old), PlayerSlot(), PlayerSlot()],
    )
    shown = []

    def accept_suggestions(match_dialog: SignUpMatchDialog) -> int:
        """Record the suggestion and the text the host sees, then accept."""
        combo = match_dialog.choice_combo
        shown.append((list(match_dialog.selected), combo.currentText()))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SignUpMatchDialog, "exec", accept_suggestions)
    editor.roster.refresh_button.click()

    assert shown[0][0] == [0]
    assert "no longer in the sheet" in shown[0][1]
    assert actual_names(editor) == ["Jane Doe", "", ""]
    assert editor.roster.slots[0].sign_up.timestamp == "new"
    assert editor.roster.slots[0].sign_up.occupation == "Chef"


def test_stale_sheet_result_is_dropped(qtbot: object, temp_dir: object) -> None:
    """Only the newest fetch's result is applied."""
    pending = []
    fetcher = FakeFetcher([HEADER, ["t1", "Ann"]])
    editor = TournamentEditor(temp_dir, fetcher=fetcher, run_async=pending.append)
    qtbot.addWidget(editor)
    editor.roster.sheet_edit.setText(SHEET_LINK)
    editor.roster.refresh_sheet()
    editor.roster.refresh_sheet()

    pending[0]()
    assert editor.roster.slots[0].blank
    assert not editor.roster.refresh_button.isEnabled()

    pending[1]()
    assert editor.roster.slots[0].actual_name == "Ann"
    assert editor.roster.refresh_button.isEnabled()


def test_network_errors_are_shown(qtbot: object, temp_dir: object) -> None:
    """A failed request says so, and Refresh works again afterwards."""
    fetcher = FakeFetcher(error=requests.ConnectionError("offline"))
    editor = make_editor(qtbot, temp_dir, fetcher)
    editor.roster.sheet_edit.setText(SHEET_LINK)
    editor.roster.refresh_button.click()
    assert "Couldn't reach the sign-up sheet" in editor.roster.status_label.text()
    assert editor.roster.refresh_button.isEnabled()


def test_unlink_remove_and_restore_ignored(qtbot: object, temp_dir: object) -> None:
    """The host can undo a wrong link, an extra player, and an ignore."""
    slots = [
        PlayerSlot("Jane", SignUp("t1", "Jane")),
        PlayerSlot("Bob"),
        PlayerSlot("Cy"),
    ]
    editor = make_editor(
        qtbot,
        temp_dir,
        FakeFetcher(),
        settings=TournamentSettings("Fun", SHEET_LINK, ["t9"]),
        slots=slots,
    )
    assert not editor.roster.unlink_button.isEnabled()
    assert not editor.roster.remove_button.isEnabled()

    editor.roster.table.selectRow(0)
    assert editor.roster.unlink_button.isEnabled()
    editor.roster.unlink_button.click()
    assert editor.roster.slots[0] == PlayerSlot("Jane")
    assert not editor.roster.unlink_button.isEnabled()

    editor.roster.table.selectRow(1)
    editor.roster.remove_button.click()
    assert actual_names(editor) == ["Jane", "Cy", ""]

    assert editor.roster.restore_ignored_button.text() == "Restore Ignored (1)"
    editor.roster.restore_ignored_button.click()
    assert editor.roster.settings.ignored_sign_ups == []
    assert not editor.roster.restore_ignored_button.isEnabled()


def test_save_rejects_a_linked_player_without_a_name(
    qtbot: object, temp_dir: object
) -> None:
    """Clearing a linked player's name blocks Save."""
    editor = make_editor(
        qtbot,
        temp_dir,
        FakeFetcher(),
        settings=TournamentSettings("Fun"),
        slots=[PlayerSlot("Jane", SignUp("t1", "Jane")), PlayerSlot(), PlayerSlot()],
    )
    editor.roster.table.item(0, COLUMN_ACTUAL_NAME).setText("")
    click_save(editor)
    assert "no Actual Name" in editor.status_label.text()
    assert not (temp_dir / "Fun").exists()


def make_window(qtbot: object, root: object, **kwargs: object) -> TournamentWindow:
    """Return a Tournament window that saves under ``root``."""
    window = TournamentWindow(
        root,
        fetcher=FakeFetcher(),
        run_async=run_inline,
        missing_media=no_missing_media,
        **kwargs,
    )
    qtbot.addWidget(window)
    return window


def test_window_creates_and_loads_tournaments(qtbot: object, temp_dir: object) -> None:
    """The home page creates a new tournament or loads a saved one."""
    window = make_window(qtbot, temp_dir)
    assert "No saved tournaments" in window.home_status.text()
    assert not window.load_button.isEnabled()

    window.create_button.click()
    created = window.editor
    assert created.creating
    assert window.stack.currentWidget() is created
    created.buttons.button(created.buttons.StandardButton.Close).click()
    assert window.editor is None
    assert window.stack.currentWidget() is window.home_page

    save_tournament(temp_dir, TournamentSettings("Fun"), [PlayerSlot("Jane")])
    window.refresh_saved_list()
    assert window.saved_list.currentItem().text() == "Fun"
    window.load_button.click()
    loaded = window.editor
    assert not loaded.creating
    assert loaded.name_edit.isReadOnly()
    assert loaded.roster.slots[0].actual_name == "Jane"
    assert window.windowTitle() == "Tournament: Fun"


def test_window_bracket_designer_page(qtbot: object, temp_dir: object) -> None:
    """The bracket designer opens from the home page and goes back."""
    window = make_window(qtbot, temp_dir)
    window.designer_button.click()
    assert window.stack.currentWidget() is window.designer_page
    assert not window.designer.player_spinbox.isReadOnly()
    window.show_home()
    assert window.stack.currentWidget() is window.home_page


def test_window_shows_load_problems(qtbot: object, temp_dir: object) -> None:
    """A broken tournament file is reported and opens nothing."""
    save_tournament(temp_dir, TournamentSettings("Fun"), [PlayerSlot("Jane")])
    (temp_dir / "Fun" / "tournament.json").write_text("not json", encoding="utf-8")
    window = make_window(qtbot, temp_dir)
    window.load_button.click()
    assert "Couldn't load Fun" in window.home_status.text()
    assert window.editor is None


def test_closing_asks_before_discarding_changes(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """Unsaved changes need a Discard; an unchanged tournament stays open."""
    answers = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: answers.pop(0))
    window = make_window(qtbot, temp_dir)
    window.show()
    window.create_button.click()
    editor = window.editor
    window.reject()
    assert not window.isVisible()
    assert window.editor is editor

    window.show()
    editor.roster.table.item(0, COLUMN_ACTUAL_NAME).setText("Ann")
    answers.append(QMessageBox.StandardButton.Cancel)
    window.reject()
    assert window.isVisible()
    assert window.editor is editor
    answers.append(QMessageBox.StandardButton.Discard)
    window.reject()
    assert not window.isVisible()
    assert window.editor is None
    assert answers == []


def test_opening_another_tournament_keeps_unsaved_changes(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """Going back home doesn't silently discard an open tournament."""
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Cancel
    )
    window = make_window(qtbot, temp_dir)
    window.create_button.click()
    first = window.editor
    first.roster.table.item(0, COLUMN_ACTUAL_NAME).setText("Ann")
    assert not window.show_home()
    assert window.editor is first
    assert window.stack.currentWidget() is first


def test_fetch_finishing_after_close_is_dropped(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """A result that arrives after the tournament closes doesn't open a dialog."""
    pending = []
    fetcher = FakeFetcher([HEADER, ["t1", "Ann"]])
    editor = TournamentEditor(
        temp_dir,
        settings=TournamentSettings("Fun", SHEET_LINK),
        slots=[PlayerSlot("Ann"), PlayerSlot(), PlayerSlot()],
        fetcher=fetcher,
        run_async=pending.append,
    )
    qtbot.addWidget(editor)
    opened = []
    monkeypatch.setattr(SignUpMatchDialog, "exec", lambda self: opened.append(self))
    editor.roster.refresh_button.click()
    assert editor.confirm_discard()
    pending[0]()
    assert opened == []
    assert editor.roster.slots[0].sign_up is None


def test_tournament_window_fits_on_its_screen(qtbot: object, temp_dir: object) -> None:
    """A window bigger than the screen shrinks and moves so all of it shows."""
    window = make_window(qtbot, temp_dir)
    area = window.screen().availableGeometry()
    window.resize(area.width() + 300, area.height() + 300)
    window.move(area.left() + 200, area.top() + 200)
    window.show()
    qtbot.waitExposed(window)

    # Leave room for a title bar the offscreen platform doesn't draw.
    assert window.width() <= area.width() - 16
    assert window.height() <= area.height() - 40
    assert window.x() >= area.left()
    assert window.y() >= area.top()
    assert window.y() + window.height() + 40 <= area.bottom() + 1
    assert window.x() + window.width() + 16 <= area.right() + 1


def test_tournament_window_that_fits_is_left_alone(
    qtbot: object, temp_dir: object
) -> None:
    """A window that already fits keeps the size and place the host gave it."""
    window = make_window(qtbot, temp_dir)
    area = window.screen().availableGeometry()
    # Qt enforces the window's own minimum size on show, so start from it.
    size = window.minimumSizeHint().expandedTo(window.minimumSize()) + QSize(0, 40)
    window.resize(size)
    window.move(area.left(), area.top() + 60)
    window.show()
    qtbot.waitExposed(window)
    assert window.size() == size
    assert window.pos() == area.topLeft() + QPoint(0, 60)
