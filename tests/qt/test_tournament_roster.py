"""Qt tests for the tournament roster dialogs."""

import pytest
from PyQt6.QtWidgets import QDialog, QInputDialog

from jparty.domain.roster import (
    MATCH_ADD_PLAYER,
    MATCH_IGNORE,
    PlayerSlot,
    SignUp,
    SignUpMatch,
)
from jparty.domain.tournament_store import (
    TournamentSettings,
    load_tournament,
    save_tournament,
)
from jparty.services.game_sources import SheetAccessError
from jparty.ui.widgets import welcome
from jparty.ui.widgets.tournament_roster import (
    COLUMN_ACTUAL_NAME,
    SignUpMatchDialog,
    TournamentRosterDialog,
)
from jparty.ui.widgets.welcome import Welcome
from tests.qt.test_welcome_widget import StubGame

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


def make_dialog(
    qtbot: object, root: object, fetcher: FakeFetcher, **kwargs: object
) -> TournamentRosterDialog:
    """Return a roster dialog that fetches from ``fetcher``."""
    dialog = TournamentRosterDialog(
        root, fetcher=fetcher, run_async=run_inline, **kwargs
    )
    qtbot.addWidget(dialog)
    return dialog


def actual_names(dialog: TournamentRosterDialog) -> list[str]:
    """Return the Actual Name column as shown."""
    return [
        dialog.table.item(row, COLUMN_ACTUAL_NAME).text()
        for row in range(dialog.table.rowCount())
    ]


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
    dialog = make_dialog(qtbot, temp_dir, fetcher)
    dialog.name_edit.setText("Family Fun")
    dialog.sheet_edit.setText(SHEET_LINK)
    dialog.player_spinbox.setValue(5)
    dialog.refresh_button.click()

    assert fetcher.links == [SHEET_LINK]
    assert actual_names(dialog) == ["Jane Doe", "Bob", "", "", ""]
    assert "Found 2 sign-ups" in dialog.status_label.text()

    dialog.buttons.button(dialog.buttons.StandardButton.Save).click()
    settings, slots = load_tournament(temp_dir / "Family Fun")
    assert settings.sheet_url == SHEET_LINK
    assert len(slots) == 5
    assert slots[0].sign_up.occupation == "Pilot"
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_typed_names_are_kept_and_count_cannot_drop_below_them(
    qtbot: object, temp_dir: object
) -> None:
    """Typed names are saved, and filled slots can't be removed."""
    dialog = make_dialog(qtbot, temp_dir, FakeFetcher())
    dialog.player_spinbox.setValue(4)
    dialog.table.item(2, COLUMN_ACTUAL_NAME).setText("Carol")
    assert dialog.slots[2].actual_name == "Carol"
    assert dialog.player_spinbox.minimum() == 3
    dialog.player_spinbox.setValue(10)
    assert len(dialog.slots) == 10
    dialog.player_spinbox.setValue(3)
    assert actual_names(dialog) == ["", "", "Carol"]


def test_refresh_after_typing_names_asks_to_match(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """New sign-ups are matched to typed names through the match dialog."""
    fetcher = FakeFetcher([HEADER, ["t1", "Jane Q Doe", "", "", ""], ["t2", "lol"]])
    slots = [PlayerSlot("Jane Doe"), PlayerSlot("Bob"), PlayerSlot("Carol")]
    dialog = make_dialog(
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
    dialog.refresh_button.click()

    assert shown == [[0, None]]
    assert dialog.slots[0].sign_up.timestamp == "t1"
    assert actual_names(dialog) == ["Jane Doe", "Bob", "Carol"]
    assert dialog.settings.ignored_sign_ups == ["t2"]

    # The ignored response isn't asked about again.
    shown.clear()
    dialog.refresh_button.click()
    assert shown == []


def test_cancelled_match_leaves_sign_ups_for_next_time(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """Cancelling the match dialog places nothing and says so."""
    fetcher = FakeFetcher([HEADER, ["t1", "Jane"]])
    dialog = make_dialog(
        qtbot,
        temp_dir,
        fetcher,
        settings=TournamentSettings("Fun", SHEET_LINK),
        slots=[PlayerSlot("Jane"), PlayerSlot(), PlayerSlot()],
    )
    monkeypatch.setattr(
        SignUpMatchDialog, "exec", lambda _self: QDialog.DialogCode.Rejected
    )
    dialog.refresh_button.click()
    assert dialog.slots[0].sign_up is None
    assert "1 not placed yet" in dialog.status_label.text()


def test_sheet_errors_are_shown(qtbot: object, temp_dir: object) -> None:
    """Fetch problems are shown, and the button works again afterwards."""
    fetcher = FakeFetcher(error=SheetAccessError("Share the sheet"))
    dialog = make_dialog(qtbot, temp_dir, fetcher)
    dialog.refresh_button.click()
    assert "Paste the link" in dialog.status_label.text()
    dialog.sheet_edit.setText(SHEET_LINK)
    dialog.refresh_button.click()
    assert dialog.status_label.text() == "Share the sheet"
    assert dialog.refresh_button.isEnabled()


def test_save_rejects_duplicate_and_existing_names(
    qtbot: object, temp_dir: object
) -> None:
    """Players need different names, and a new tournament a new folder."""
    save_tournament(temp_dir, TournamentSettings("Taken"), [])
    dialog = make_dialog(qtbot, temp_dir, FakeFetcher())
    save = dialog.buttons.button(dialog.buttons.StandardButton.Save)
    save.click()
    assert "Enter a tournament name" in dialog.status_label.text()
    dialog.name_edit.setText("Taken")
    save.click()
    assert "already exists" in dialog.status_label.text()
    dialog.name_edit.setText("New")
    dialog.table.item(0, COLUMN_ACTUAL_NAME).setText("Ann")
    dialog.table.item(1, COLUMN_ACTUAL_NAME).setText("ann")
    save.click()
    assert "both named" in dialog.status_label.text()
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


def test_welcome_create_and_load_tournament(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """The welcome buttons open the roster for a new or saved tournament."""
    monkeypatch.setattr(welcome, "TOURNAMENTS_DIR", temp_dir)
    widget = Welcome(StubGame())
    qtbot.addWidget(widget)

    widget.create_tournament_button.click()
    created = widget.tournament_roster_dialog
    assert isinstance(created, TournamentRosterDialog)
    assert created.creating
    created.close()

    save_tournament(temp_dir, TournamentSettings("Fun"), [PlayerSlot("Jane")])
    monkeypatch.setattr(
        QInputDialog, "getItem", lambda *_args: ("Fun", True), raising=True
    )
    widget.load_tournament_button.click()
    loaded = widget.tournament_roster_dialog
    assert not loaded.creating
    assert loaded.name_edit.isReadOnly()
    assert loaded.slots[0].actual_name == "Jane"
    loaded.close()
