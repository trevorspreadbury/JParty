"""Qt tests for the tournament board picker and its advanced board editor."""

from copy import deepcopy

import pytest
from PyQt6.QtWidgets import QRadioButton

from jparty.domain.tournament.setup import TournamentBoard
from jparty.services.question_media import QuestionMediaStatus
from jparty.ui.widgets import advanced_boards
from jparty.ui.widgets.advanced_boards import (
    AdvancedBoardEditor,
    AdvancedBoardSetup,
    snapshots_from_board_selections,
)
from jparty.ui.widgets.board_setup import INCOMPLETE_TEXT, BoardPickerDialog
from tests.qt.test_welcome_widget import StubGame

pytestmark = pytest.mark.qt


def run_inline(work: object) -> None:
    """Run background work right away."""
    work()


@pytest.fixture()
def fake_games(monkeypatch: object) -> list[str]:
    """Serve StubGame's game for every id, without the network or media.

    Returns:
        The ids loaded, in order.
    """
    loaded = []
    source = StubGame().data

    def get_game(game_id: str) -> object:
        """Record the id and return a copy of the stub game."""
        loaded.append(game_id)
        return deepcopy(source)

    monkeypatch.setattr(advanced_boards, "get_game", get_game)
    monkeypatch.setattr(
        advanced_boards,
        "detect_question_media",
        lambda _game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )
    return loaded


def make_picker(qtbot: object, **kwargs: object) -> BoardPickerDialog:
    """Return a board picker that loads games inline."""
    dialog = BoardPickerDialog("Final: Final", run_async=run_inline, **kwargs)
    qtbot.addWidget(dialog)
    return dialog


def test_picker_starts_empty_and_waits_for_every_slot(qtbot: object) -> None:
    """Use This Board stays off, and accept does nothing, until slots are full."""
    dialog = make_picker(qtbot)
    assert dialog.windowTitle() == "Set Board: Final: Final"
    assert len(dialog.editor.rows) == 3
    assert dialog.summary_label.text() == INCOMPLETE_TEXT
    assert not dialog.use_button.isEnabled()
    dialog.accept()
    assert dialog.board is None
    assert dialog.result() != dialog.DialogCode.Accepted


def test_one_game_for_every_slot_plays_it_as_aired(
    qtbot: object, fake_games: list[str]
) -> None:
    """Use for Every Slot loads the game into each row with its own round."""
    dialog = make_picker(qtbot)
    dialog.one_game_edit.setText("4453")
    dialog.one_game_button.click()
    # One fetch: the other rows use the editor's cache.
    assert fake_games == ["4453"]
    assert dialog.use_button.isEnabled()
    assert "Board 1: 4453 - Jeopardy!" in dialog.summary_label.text()

    dialog.use_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    board = dialog.board
    assert board.label == "4453 (Jeopardy!, Double Jeopardy!, Final Jeopardy!)"
    assert [s["source_round_index"] for s in board.board_selections] == [0, 1, 2]


def test_editing_a_board_round_trips_its_choices(
    qtbot: object, fake_games: list[str]
) -> None:
    """Reopening a board shows its rounds, values, and Daily Doubles unchanged."""
    first = make_picker(qtbot)
    first.editor.fill_all_slots("4453")
    first.editor.rows[0]["value_edits"][0].setText("300")
    first.editor.rows[0]["value_edits"][0].editingFinished.emit()
    first.accept()
    saved = first.board
    assert saved.board_selections[0]["row_values"][0] == 300

    reopened = make_picker(qtbot, board=saved)
    assert [row["gameid_edit"].text() for row in reopened.editor.rows] == [
        "4453",
        "4453",
        "4453",
    ]
    assert reopened.use_button.isEnabled()
    reopened.accept()
    assert reopened.board == saved


def test_picker_shows_a_frankenstein_board(
    qtbot: object, fake_games: list[str]
) -> None:
    """Rows from different games give a Frankenstein board and label."""
    dialog = make_picker(qtbot)
    editor = dialog.editor
    editor.standard_board_count_spinbox.setValue(1)
    for row, game_id in zip(editor.rows, ("11", "22"), strict=True):
        row["gameid_edit"].setText(game_id)
        editor.refresh_row(row["index"])
    dialog.accept()
    assert dialog.board.source_game_ids == ("11", "22")
    assert dialog.board.label == "11 Jeopardy! + 22 Final Jeopardy!"


def test_snapshots_from_board_selections() -> None:
    """Saved selections become row snapshots by slot type."""
    selections = [
        {
            "game_id": "11",
            "source_round_index": 1,
            "board_type": "standard",
            "row_values": [100, 200, 300, 400, 500],
            "daily_double_count": 1,
            "daily_double_indices": [[2, 3]],
        },
        {"game_id": "22", "source_round_index": 2, "board_type": "final"},
    ]
    snapshots = snapshots_from_board_selections(selections)
    standard = snapshots["standard"][0]
    assert standard["values"] == ["100", "200", "300", "400", "500"]
    assert standard["selected_round_index"] == 1
    assert standard["daily_double_indices"] == [[2, 3]]
    assert standard["daily_double_source_round_index"] == 1
    assert snapshots["final"][0]["selected_round_index"] == 2
    assert snapshots["final"][0]["values"] == []


def test_advanced_board_setup_readiness() -> None:
    """A setup is complete when every row is ready, and ready once composed."""
    one = ({"game_id": "1"},)
    assert not AdvancedBoardSetup(one, slot_count=2).complete
    partial = AdvancedBoardSetup(one + ({"game_id": "2"},), slot_count=2)
    assert partial.complete
    assert not partial.ready
    assert partial.summary_text() == ""
    assert partial.session_game_id == "frankenstein-1-2"


def test_editor_reports_changes_without_a_game(
    qtbot: object, fake_games: list[str]
) -> None:
    """The editor only signals; callers read the board from current_setup."""
    editor = AdvancedBoardEditor(run_async=run_inline)
    qtbot.addWidget(editor)
    changes = []
    editor.setup_changed.connect(lambda: changes.append(1))
    editor.fill_all_slots("4453")
    assert changes
    setup = editor.current_setup()
    assert setup.ready
    assert setup.session_game_id == "4453"
    editor.reset()
    assert [row["gameid_edit"].text() for row in editor.rows] == ["", "", ""]
    assert not editor.current_setup().complete


def test_slot_counts_follow_the_saved_board(
    qtbot: object, fake_games: list[str]
) -> None:
    """A saved board's slot counts are restored, within the editor's limits."""
    saved = TournamentBoard(
        "x",
        (
            {"game_id": "1", "source_round_index": 0, "board_type": "standard"},
            {"game_id": "1", "source_round_index": 2, "board_type": "final"},
            {"game_id": "2", "source_round_index": 2, "board_type": "final"},
        ),
    )
    dialog = make_picker(qtbot, board=saved)
    assert dialog.editor.standard_board_count_spinbox.value() == 1
    assert dialog.editor.final_board_count_spinbox.value() == 2
    assert [row["gameid_edit"].text() for row in dialog.editor.rows] == [
        "1",
        "1",
        "2",
    ]


class DeferredRunner:
    """Hold background work until :meth:`finish` runs it."""

    def __init__(self) -> None:
        """Start with no work waiting."""
        self.waiting = []

    def __call__(self, work: object) -> None:
        """Keep ``work`` for later."""
        self.waiting.append(work)

    def finish(self) -> None:
        """Run the waiting work, including work it starts."""
        while self.waiting:
            self.waiting.pop(0)()


def choose_round(row: dict, source_round_index: int) -> None:
    """Click a row's radio button for ``source_round_index``."""
    for radio in row["board_radio_widget"].findChildren(QRadioButton):
        if radio.property("source_round_index") == source_round_index:
            radio.click()
            return
    raise AssertionError(f"no radio for round {source_round_index}")


def test_reopened_board_keeps_its_rounds_if_counts_change_while_loading(
    qtbot: object, fake_games: list[str]
) -> None:
    """Changing a slot count before a reopened board loads keeps its choices."""
    first = make_picker(qtbot)
    first.editor.fill_all_slots("4453")
    # Swap the first two rows' rounds, so the defaults would differ.
    choose_round(first.editor.rows[0], 1)
    choose_round(first.editor.rows[1], 0)
    first.accept()
    saved = first.board
    assert [s["source_round_index"] for s in saved.board_selections] == [1, 0, 2]

    runner = DeferredRunner()
    reopened = BoardPickerDialog("Final: Final", board=saved, run_async=runner)
    qtbot.addWidget(reopened)
    assert runner.waiting
    reopened.editor.final_board_count_spinbox.setValue(2)
    reopened.editor.final_board_count_spinbox.setValue(1)
    runner.finish()
    reopened.accept()
    assert reopened.board == saved


def test_one_game_for_every_slot_starts_from_a_plain_board(
    qtbot: object, fake_games: list[str]
) -> None:
    """Use for Every Slot drops an edited board's values and slot counts."""
    plain = make_picker(qtbot)
    plain.editor.fill_all_slots("4453")
    plain.accept()

    dialog = make_picker(qtbot)
    editor = dialog.editor
    editor.fill_all_slots("4453")
    editor.rows[0]["value_edits"][0].setText("777")
    editor.rows[0]["value_edits"][0].editingFinished.emit()
    editor.rows[0]["daily_double_spinbox"].setValue(3)
    editor.standard_board_count_spinbox.setValue(3)
    dialog.one_game_edit.setText("4453")
    dialog.one_game_button.click()
    dialog.accept()

    def as_aired(board: TournamentBoard) -> list[tuple]:
        """Return what decides the board, apart from random Daily Doubles."""
        return [
            (
                s["source_round_index"],
                s.get("row_values"),
                s.get("daily_double_count"),
            )
            for s in board.board_selections
        ]

    assert as_aired(dialog.board) == as_aired(plain.board)
