"""Qt tests for dropping tournament players out from the play panel."""

from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QMessageBox

from jparty.domain.tournament.drop_choices import DropOption, DropSituation
from jparty.domain.tournament.dropouts import (
    DROP_REDUCE,
    DROP_REPLACE,
    DROP_VOID,
    Dropout,
)
from jparty.domain.tournament.store import (
    load_dropouts,
    load_results,
    load_tournament,
    load_voided_results,
)
from jparty.ui.widgets.tournament.dropouts import DropPlayerDialog
from jparty.ui.widgets.tournament.play import PLAYED_COLOR
from tests.qt.test_tournament_roster import FakeFetcher, make_editor
from tests.qt.test_welcome_tournament import (
    SF1,
    all_semifinal_results,
    list_texts,
    make_panel,
    sf1_results,
    tournament_welcome,  # noqa: F401
    write_tournament,
)

pytestmark = pytest.mark.qt


@pytest.fixture()
def messages(monkeypatch: object) -> list[str]:
    """Collect message boxes instead of showing them."""
    shown: list[str] = []

    def record(_parent: object, _title: str, text: str, *_args: object) -> None:
        shown.append(text)

    monkeypatch.setattr(QMessageBox, "warning", record)
    monkeypatch.setattr(QMessageBox, "information", record)
    return shown


def select_player(panel: object, player_id: str) -> None:
    """Select ``player_id`` in the panel's players list."""
    for row in range(panel.players_list.count()):
        if panel.players_list.item(row).data(0x0100) == player_id:
            panel.players_list.setCurrentRow(row)
            return
    raise AssertionError(player_id)


def choosing(choice: str, name: str = "") -> object:
    """Return an ``ask_drop`` that picks the option ``choice``."""

    def ask(situation: DropSituation, _parent: object) -> tuple[DropOption, str]:
        (found,) = [o for o in situation.options if o.dropout.choice == choice]
        return found, name

    return ask


def test_reduce_replans_the_bracket_and_greys_the_player(
    qtbot: object, temp_dir: object, messages: list[str]
) -> None:
    """P4 hasn't played: reducing to 8 players turns SF 3 into Chase 1."""
    folder = write_tournament(temp_dir, sf1_results())
    panel = make_panel(qtbot, folder)
    assert not panel.drop_button.isEnabled()
    assert not panel.undo_drop_button.isEnabled()
    select_player(panel, "p4")
    assert panel.drop_button.isEnabled()
    panel.ask_drop = choosing(DROP_REDUCE)
    with qtbot.waitSignal(panel.results_changed):
        panel.drop_selected_player()
    assert messages == []
    assert load_dropouts(folder) == [Dropout("p4", "Semifinals", DROP_REDUCE)]
    assert "Semifinals: Chase 1: no board" in list_texts(panel.games_list)
    row = list_texts(panel.players_list).index("P4 (dropped out)")
    assert panel.players_list.item(row).foreground().color() == PLAYED_COLOR
    assert not panel.drop_button.isEnabled()  # P4 is still selected
    assert panel.undo_drop_button.isEnabled()
    panel.select_game("Semifinals: SF 2")
    combo = panel.podium_combos[0]
    offered = [combo.itemData(index) for index in range(1, combo.count())]
    assert "p4" not in offered


def test_replace_adds_the_new_player_to_the_roster(
    qtbot: object, temp_dir: object, messages: list[str]
) -> None:
    """The new player is saved in players.csv and can be picked."""
    folder = write_tournament(temp_dir, sf1_results())
    panel = make_panel(qtbot, folder)
    select_player(panel, "p4")
    panel.ask_drop = choosing(DROP_REPLACE, "Newbie")
    panel.drop_selected_player()
    _settings, slots = load_tournament(folder)
    assert [slot.actual_name for slot in slots][-1] == "Newbie"
    assert "Newbie" in list_texts(panel.players_list)
    assert "Semifinals: SF 3: no board" in list_texts(panel.games_list)


def test_semifinal_winner_voids_their_game_until_undone(
    qtbot: object, temp_dir: object, messages: list[str]
) -> None:
    """P1 won SF 1: its results are set aside, then come back on Undo."""
    folder = write_tournament(temp_dir, all_semifinal_results())
    panel = make_panel(qtbot, folder)
    select_player(panel, "p1")
    panel.ask_drop = choosing(DROP_VOID)
    panel.drop_selected_player()
    assert {row.player_id for row in load_voided_results(folder)} == {"p1", "p2", "p3"}
    assert all(row.game_key != SF1 for row in load_results(folder))
    texts = list_texts(panel.games_list)
    # SF 1's board is retired, and P5 and P8 tie for P1's seat.
    assert f"{SF1}: no board" in texts
    assert texts[0] == (
        "Tiebreaker: P5, P8 for a dropped-out player's seat in the Semifinals"
    )

    seen = []

    def undo(dropouts: list, texts: list, problems: list, _parent: object) -> object:
        seen.append((texts, problems))
        return dropouts[0]

    panel.ask_undo = undo
    panel.undo_dropout()
    assert seen == [(["P1: dropped out after winning SF 1, which was voided"], [""])]
    assert load_dropouts(folder) == []
    assert load_voided_results(folder) == []
    assert {row.game_key for row in load_results(folder)} >= {SF1}
    assert list_texts(panel.games_list)[0].startswith(f"{SF1}: played")


def test_a_player_who_cant_drop_out_is_told_why(
    qtbot: object, temp_dir: object, messages: list[str]
) -> None:
    """P2 lost SF 1, so they're already out; nothing is asked or saved."""
    folder = write_tournament(temp_dir, sf1_results())
    panel = make_panel(qtbot, folder)
    select_player(panel, "p2")
    panel.ask_drop = lambda *_args: pytest.fail("shouldn't ask")
    panel.drop_selected_player()
    assert messages == ["P2 is already out."]
    assert load_dropouts(folder) == []


def test_unsaved_tournament_window_edits_block_a_drop(
    qtbot: object, temp_dir: object, messages: list[str]
) -> None:
    """The welcome screen's check stops the drop before anything is saved."""
    folder = write_tournament(temp_dir, sf1_results())
    panel = make_panel(qtbot, folder)
    panel.before_change = lambda: "Save the Tournament window first."
    select_player(panel, "p4")
    panel.ask_drop = lambda *_args: pytest.fail("shouldn't ask")
    panel.drop_selected_player()
    assert messages == ["Save the Tournament window first."]
    assert load_dropouts(folder) == []


def test_editor_plans_the_bracket_for_the_field_after_dropouts(
    qtbot: object, temp_dir: object, messages: list[str]
) -> None:
    """A reduced field shows 8 players and its Chase 1 on the Games tab."""
    folder = write_tournament(temp_dir, sf1_results())
    panel = make_panel(qtbot, folder)
    select_player(panel, "p4")
    panel.ask_drop = choosing(DROP_REDUCE)
    panel.drop_selected_player()
    settings, slots = load_tournament(folder)
    editor = make_editor(qtbot, temp_dir, FakeFetcher(), settings=settings, slots=slots)
    assert editor.bracket.plan.options.player_count == 8
    keys = [editor.games.table.item(row, 0).text() for row in range(3)]
    assert any("Chase 1" in key for key in keys)


def test_drop_dialog_needs_a_name_for_a_replacement(qtbot: object) -> None:
    """Replace shows the name box, and OK waits until a name is typed."""
    situation = DropSituation(
        "p4",
        "P4 hasn't played yet.",
        (
            DropOption(Dropout("p4", "Semifinals", DROP_REDUCE), "Reduce", "", "No."),
            DropOption(Dropout("p4", "Semifinals", DROP_REPLACE), "Replace", "New."),
        ),
    )
    dialog = DropPlayerDialog(situation)
    qtbot.addWidget(dialog)
    assert not dialog.radios[0].isEnabled()
    assert dialog.chosen() == situation.options[1]
    assert not dialog.name_edit.isHidden()
    dialog.accept()
    assert dialog.status_label.text() == "Type the new player's name."
    assert dialog.result() != dialog.DialogCode.Accepted
    dialog.name_edit.setText("  Newbie ")
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.new_player_name() == "Newbie"


def test_welcome_blocks_drops_while_the_tournament_window_has_edits(
    tournament_welcome: tuple,  # noqa: F811
) -> None:
    """Unsaved Tournament window edits would overwrite a drop, so it waits."""
    widget, _game, _parent = tournament_welcome
    panel = widget.tournament_panel
    assert panel.before_change() is None
    edits = SimpleNamespace(editor=SimpleNamespace(has_unsaved_changes=lambda: True))
    widget.tournament_window = edits
    assert "unsaved changes" in panel.before_change()
    edits.editor.has_unsaved_changes = lambda: False
    assert panel.before_change() is None


@pytest.mark.parametrize("choice", [DROP_VOID, DROP_REPLACE])
def test_open_tournament_window_doesnt_undo_a_drop_when_it_saves(
    qtbot: object,
    temp_dir: object,
    tournament_welcome: tuple,  # noqa: F811
    messages: list[str],
    choice: str,
) -> None:
    """An open, clean window rereads the drop, so its next Save keeps it."""
    from jparty.domain.tournament.store import load_tournament_data
    from tests.qt.test_tournament_roster import make_window

    widget, _game, _parent = tournament_welcome
    folder = temp_dir / "Fun"
    window = make_window(qtbot, temp_dir)
    window._open_editor(*load_tournament(folder))
    window.show()
    widget.tournament_window = window
    panel = widget.tournament_panel
    player = "p1" if choice == DROP_VOID else "p4"
    select_player(panel, player)
    panel.ask_drop = choosing(choice, "Newbie")
    panel.drop_selected_player()
    assert not window.editor.has_unsaved_changes()

    window.editor.save()
    settings, data = load_tournament_data(folder)
    if choice == DROP_VOID:
        assert SF1 not in settings.boards
        assert [b.left_game_key for b in settings.retired_boards] == [SF1]
    else:
        assert "Newbie" in [slot.actual_name for slot in data.slots]
