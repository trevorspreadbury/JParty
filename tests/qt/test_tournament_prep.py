"""Qt tests for getting a tournament ready and following it while it's played.

Covers the Games tab's Download All Games and Preview All Media buttons, the
media preview, the Rankings tab and window, the play panel's Edit
Tournament button, and resuming a half-played tournament game.
"""

import json
from pathlib import Path

import pytest
from PyQt6.QtGui import QImage

from jparty.domain.models import Board, GameData, Question
from jparty.domain.tournament_dropouts import DROP_REPLACE, Dropout
from jparty.domain.tournament_play import GameResult, TournamentGameRef
from jparty.domain.tournament_store import load_tournament, save_tournament
from jparty.services.board_prep import PreparedBoard
from jparty.ui.widgets.tournament_editor import TAB_RANKINGS
from jparty.ui.widgets.tournament_games import POOL_BOARD_KEY
from jparty.ui.widgets.tournament_play import IN_PROGRESS_TEXT
from jparty.ui.widgets.tournament_prep import (
    NO_MEDIA_TEXT,
    BoardMediaPreviewDialog,
    media_summary,
)
from jparty.ui.widgets.tournament_rankings import COLUMN_PLAYER, COLUMN_RANK
from jparty.ui.widgets.tournament_window import TournamentWindow
from tests.qt import test_welcome_tournament
from tests.qt.test_tournament_games import board, make_games
from tests.qt.test_tournament_roster import run_inline
from tests.qt.test_welcome_tournament import (
    SF1,
    SF2,
    list_texts,
    make_panel,
    sf1_results,
    write_tournament,
)
from tests.qt.test_welcome_widget import DeferredLoader

pytestmark = pytest.mark.qt

# The welcome screen in tournament mode, shared with the tournament play tests.
tournament_welcome = test_welcome_tournament.tournament_welcome


def media_game(image: Path) -> GameData:
    """Return a one-round game whose first clue shows ``image``."""
    questions = [
        Question((0, row), f"Q{row}", f"A{row}", "Cat", 200 * (row + 1))
        for row in range(5)
    ]
    questions[0].image_url = str(image)
    return GameData([Board(["Cat"], questions)], "today", "")


class FakePrepare:
    """Stand in for ``prepare_boards``: every board loads, one with an error."""

    def __init__(self, image: Path | None = None, fail: str = "") -> None:
        """Give every board ``image``, and fail the board keyed ``fail``."""
        self.image = image
        self.fail = fail
        self.calls = []

    def __call__(
        self, boards: list, on_progress: object, is_cancelled: object
    ) -> list[PreparedBoard]:
        """Record the boards and report progress for each."""
        self.calls.append([key for key, _label, _selections in boards])
        prepared = []
        for index, (key, label, _selections) in enumerate(boards):
            if key == self.fail:
                prepared.append(PreparedBoard(key, label, error="offline"))
            else:
                data = media_game(self.image) if self.image else None
                media = tuple(enumerate(data.rounds[0].questions[:1])) if data else ()
                prepared.append(PreparedBoard(key, label, data or object(), "", media))
            on_progress(index + 1, len(boards))
        return prepared


def test_download_all_games_loads_every_board(qtbot: object) -> None:
    """Games' boards, then pool boards, are loaded; problems are listed."""
    prepare = FakePrepare(fail="Semifinals: SF 2")
    previews = []
    games = make_games(
        qtbot,
        missing_media=lambda _board: [],
        run_async=run_inline,
        prepare=prepare,
        preview_media=lambda boards, _parent: previews.append(boards),
    )
    games.set_boards({SF1: board("1111"), SF2: board("2222")}, [board("3333")])
    games.download_button.click()
    assert prepare.calls == [[SF1, SF2, POOL_BOARD_KEY.format(number=1)]]
    text = games.prepare_label.text()
    assert text.startswith("2 of 3 boards ready to play offline.")
    assert "Semifinals: SF 2: offline" in text
    assert previews == []
    assert games.download_button.isEnabled()


def test_preview_all_media_opens_the_preview(qtbot: object) -> None:
    """Preview All Media loads the boards, then shows them."""
    previews = []
    games = make_games(
        qtbot,
        missing_media=lambda _board: [],
        run_async=run_inline,
        prepare=FakePrepare(),
        preview_media=lambda boards, _parent: previews.append(boards),
    )
    games.set_boards({SF1: board("1111")}, [])
    games.show()
    games.preview_button.click()
    assert [[b.key for b in boards] for boards in previews] == [[SF1]]


def test_preview_waits_while_the_window_is_hidden(qtbot: object) -> None:
    """Boards that finish loading after the window hid don't open a preview."""
    previews = []
    pending = []
    games = make_games(
        qtbot,
        missing_media=lambda _board: [],
        run_async=pending.append,
        prepare=FakePrepare(),
        preview_media=lambda boards, _parent: previews.append(boards),
    )
    games.set_boards({SF1: board("1111")}, [])
    games.show()
    games.preview_button.click()
    # The host closes the Tournament window or clicks Play Games.
    games.hide()
    pending.pop()()
    assert previews == []
    assert "Click Preview All Media... to see the media." in (
        games.prepare_label.text()
    )
    assert games.preview_button.isEnabled()


def test_no_boards_to_download(qtbot: object) -> None:
    """With no boards, nothing loads and the tab says so."""
    prepare = FakePrepare()
    games = make_games(qtbot, run_async=run_inline, prepare=prepare)
    games.download_all()
    assert prepare.calls == []
    assert games.prepare_label.text() == "No boards to load yet."


def test_a_stale_download_result_is_dropped(qtbot: object) -> None:
    """Cancelling drops the result of a load still running."""
    pending = []
    games = make_games(qtbot, missing_media=lambda _board: [], run_async=pending.append)
    games.prepare = FakePrepare()
    games.set_boards({SF1: board("1111")}, [])
    games.download_all()
    assert not games.download_button.isEnabled()
    games.cancel_prepare()
    assert games.download_button.isEnabled()
    pending.pop()()
    assert games.prepare_label.text() == "Loading boards: 0 of 1..."


def test_media_preview_shows_each_boards_images(qtbot: object, temp_dir: Path) -> None:
    """Each board gets a heading; media boards get cards, others say so."""
    image = temp_dir / "clue.png"
    QImage(4, 4, QImage.Format.Format_RGB32).save(str(image))
    data = media_game(image)
    boards = [
        PreparedBoard(SF1, "1111", data, "", ((0, data.rounds[0].questions[0]),)),
        PreparedBoard(SF2, "2222", GameData([], "", "")),
        PreparedBoard("Final: Final", "3333", error="Couldn't load the board."),
    ]
    dialog = BoardMediaPreviewDialog(boards)
    qtbot.addWidget(dialog)
    assert len(dialog.cards) == 1
    texts = [label.text() for label in dialog.findChildren(type(dialog.summary_label))]
    assert NO_MEDIA_TEXT in texts
    assert "Couldn't load the board." in texts
    assert "A0" in texts
    assert "Cat for $200" in texts
    assert media_summary(boards) == "1 image on 1 of 3 boards. 1 board couldn't load."


def test_editor_rankings_tab_ranks_played_players(
    qtbot: object, temp_dir: Path
) -> None:
    """The Rankings tab ranks players from the saved results."""
    from tests.qt.test_tournament_roster import FakeFetcher, make_editor

    folder = write_tournament(temp_dir, sf1_results())
    settings, slots = load_tournament(folder)
    editor = make_editor(qtbot, temp_dir, FakeFetcher(), settings=settings, slots=slots)
    editor.tabs.setCurrentIndex(TAB_RANKINGS)
    table = editor.rankings
    assert table.cell_text(0, COLUMN_PLAYER) == "P1"
    assert table.cell_text(0, COLUMN_RANK) == "1"
    assert table.cell_text(3, COLUMN_RANK) == ""
    assert table.table.rowCount() == 9


def test_window_opens_a_tournament_by_name_and_reports_saves(
    qtbot: object, temp_dir: Path
) -> None:
    """open_tournament loads a saved tournament; saving it is announced."""
    write_tournament(temp_dir)
    window = TournamentWindow(temp_dir, run_async=run_inline)
    qtbot.addWidget(window)
    saved = []
    window.tournament_saved.connect(saved.append)
    assert window.open_tournament("Fun")
    assert window.editing("Fun")
    editor = window.editor
    assert window.open_tournament("Fun")
    assert window.editor is editor
    editor.save()
    assert saved == [temp_dir / "Fun"]
    assert not window.open_tournament("Missing")
    assert "Couldn't load Missing" in window.home_status.text()


def write_save(
    states_dir: Path, game_id: str, game_key: str, updated: float = 100.0
) -> Path:
    """Write a half-played tournament game's ``general.json``."""
    path = states_dir / f"{game_id}-20261119T1500"
    path.mkdir(parents=True)
    state = {
        "game_id": game_id,
        "players": [
            {
                "name": "Phone 0",
                "tournament_player_id": "p0",
                "tournament_player_name": "Ziggy",
            },
            {
                "name": "Phone 1",
                "tournament_player_id": "p4",
                "tournament_player_name": "P4",
            },
        ],
        "last_updated": updated,
        "tournament": TournamentGameRef("Fun", game_key).to_json(),
    }
    (path / "general.json").write_text(json.dumps(state), encoding="utf-8")
    return path


def test_panel_marks_half_played_games_and_offers_resume(
    qtbot: object, temp_dir: Path
) -> None:
    """A game with a save shows as in progress, and Resume asks for it."""
    states = temp_dir / "states"
    save_path = write_save(states, "2222", SF2)
    # A save for a game that has since been played isn't offered.
    write_save(states, "1111", SF1)
    folder = write_tournament(temp_dir / "t", sf1_results())
    panel = make_panel(qtbot, folder)
    panel.states_dir = states
    panel.reload()
    texts = list_texts(panel.games_list)
    assert texts[1] == f"{SF2}: 2222 (Jeopardy!) ({IN_PROGRESS_TEXT})"
    assert "Started with Ziggy, P4" in panel.games_list.item(1).toolTip()
    assert set(panel.saves) == {SF2}
    requested = []
    panel.resume_requested.connect(requested.append)
    panel.select_game("Semifinals: SF 3")
    assert not panel.resume_button.isEnabled()
    panel.select_game(SF2)
    assert panel.resume_button.isEnabled()
    panel.resume_button.click()
    assert [save.path for save in requested] == [save_path]


def test_panel_rankings_and_edit_buttons(qtbot: object, temp_dir: Path) -> None:
    """Rankings opens a window of standings; Edit Tournament asks for one."""
    panel = make_panel(qtbot, write_tournament(temp_dir, sf1_results()))
    assert [row.name for row in panel.rankings()[:3]] == ["P1", "P2", "P3"]
    panel.rankings_button.click()
    dialog = panel.rankings_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.windowTitle() == "Rankings: Fun"
    assert dialog.rankings_table.cell_text(0, COLUMN_PLAYER) == "P1"
    panel.rankings_button.click()
    assert panel.rankings_dialog is not dialog
    requested = []
    panel.edit_requested.connect(lambda: requested.append(True))
    panel.edit_button.click()
    assert requested == [True]


class ResumeGame:
    """Resume methods for the welcome screen's stub tournament game."""

    @staticmethod
    def install(game: object, ref: TournamentGameRef) -> None:
        """Make ``game`` read and apply saves for ``ref``."""
        game.applied = []

        def read_saved_game(path: str) -> str:
            """Return the save's path as the loaded save."""
            return path

        def apply_saved_game(loaded: str) -> dict:
            """Prepare to resume with two saved players to claim."""
            game.applied.append(loaded)
            game.resume_expected = 2
            game.resume_claimed = 0
            game.tournament_game = ref
            game.data = game.source_data
            return {
                "path": loaded,
                "general_state": {
                    "players": [
                        {"tournament_player_name": "Ziggy"},
                        {"tournament_player_name": "P4"},
                    ]
                },
            }

        def startable() -> bool:
            """Resume needs every saved player claimed."""
            if game.resume_expected is not None:
                return game.resume_claimed == game.resume_expected
            return game.data is not None and bool(game.players)

        def clear_resume_state() -> None:
            """Forget the prepared resume."""
            game.resume_expected = None
            game.resume_claimed = 0
            game.tournament_game = None
            game.clear_resume_state_calls += 1

        game.read_saved_game = read_saved_game
        game.apply_saved_game = apply_saved_game
        game.startable = startable
        game.clear_resume_state = clear_resume_state


def test_welcome_resumes_a_half_played_game(
    tournament_welcome: tuple, temp_dir: Path
) -> None:
    """Resume reads the save; once players claim it, Resume! starts it."""
    widget, game, parent = tournament_welcome
    ResumeGame.install(game, TournamentGameRef("Fun", SF2))
    panel = widget.tournament_panel
    panel.states_dir = temp_dir / "states"
    save_path = write_save(panel.states_dir, "2222", SF2)
    panel.reload()
    panel.select_game(SF2)
    assert widget.built == [["2222"]]
    panel.resume_button.click()
    assert game.applied == [str(save_path)]
    assert widget.tournament_start_button.text() == "Resume!"
    assert not widget.tournament_start_button.isEnabled()
    assert "0 of 2 so far" in panel.status_label.text()
    assert "Saved players: Ziggy, P4" in widget.summary_label.text()

    # Picking players doesn't drop the resume or reload the board.
    panel.choose(0, "p0")
    assert widget.tournament_start_button.text() == "Resume!"
    assert widget.built == [["2222"]]

    game.resume_claimed = 2
    widget.check_start()
    assert widget.tournament_start_button.isEnabled()
    assert panel.status_label.text() == "Ready to resume."
    widget.tournament_start_button.click()
    # No introduction: the game picks up where it stopped.
    assert parent.intro is None
    assert game.start_game_calls == 1
    assert game.tournament_calls[-1][0] is None


def test_choosing_another_game_drops_the_resume(
    tournament_welcome: tuple, temp_dir: Path
) -> None:
    """Selecting a different game forgets the save and loads that board."""
    widget, game, _parent = tournament_welcome
    ResumeGame.install(game, TournamentGameRef("Fun", SF2))
    panel = widget.tournament_panel
    panel.states_dir = temp_dir / "states"
    write_save(panel.states_dir, "2222", SF2)
    panel.reload()
    panel.select_game(SF2)
    panel.resume_button.click()
    assert game.resume_expected == 2
    panel.select_game("Semifinals: SF 3")
    assert game.resume_expected is None
    assert widget.tournament_start_button.text() == "Start!"


def test_a_save_for_another_game_is_refused(
    tournament_welcome: tuple, temp_dir: Path, monkeypatch: object
) -> None:
    """A save whose tournament game doesn't match isn't resumed."""
    from jparty.ui.widgets import welcome as welcome_module

    warnings = []
    monkeypatch.setattr(
        welcome_module.QMessageBox,
        "warning",
        lambda *args: warnings.append(args[2]),
    )
    widget, game, _parent = tournament_welcome
    ResumeGame.install(game, TournamentGameRef("Fun", SF1))
    panel = widget.tournament_panel
    panel.states_dir = temp_dir / "states"
    write_save(panel.states_dir, "2222", SF2)
    panel.reload()
    panel.select_game(SF2)
    panel.resume_button.click()
    assert warnings == ["The save is for a different tournament game."]
    assert widget.tournament_start_button.text() == "Start!"
    assert game.resume_expected is None
    # The board loads again, so the game can still start fresh.
    assert widget.built == [["2222"], ["2222"]]


def test_edit_tournament_opens_it_and_saving_refreshes_the_panel(
    tournament_welcome: tuple, temp_dir: Path, monkeypatch: object
) -> None:
    """Edit Tournament opens the window on it; Save updates the panel."""
    from jparty.ui.widgets import welcome as welcome_module

    monkeypatch.setattr(welcome_module, "TOURNAMENTS_DIR", temp_dir)
    widget, _game, _parent = tournament_welcome
    panel = widget.tournament_panel
    panel.edit_button.click()
    window = widget.tournament_window
    assert window is not None and window.isVisible()
    assert window.editing("Fun")

    # Give SF 3 a board on disk, then save from the window.
    settings, slots = load_tournament(temp_dir / "Fun")
    settings.boards = {**settings.boards, "Semifinals: SF 3": board("3333")}
    save_tournament(temp_dir, settings, slots)
    window.tournament_saved.emit(temp_dir / "Fun")
    assert list_texts(panel.games_list)[2] == "Semifinals: SF 3: 3333 (Jeopardy!)"
    window.hide()


def test_saving_during_a_game_waits_for_the_game(
    tournament_welcome: tuple, temp_dir: Path
) -> None:
    """A save while a game runs leaves its board alone."""
    widget, game, parent = tournament_welcome
    panel = widget.tournament_panel
    panel.select_game(SF2)
    for podium, player_id in enumerate(("p0", "p4", "p5")):
        panel.choose(podium, player_id)
    widget.tournament_start_button.click()
    parent.intro.start_button.click()
    assert game.start_game_calls == 1
    data = game.data
    widget._on_tournament_saved(panel.folder)
    assert game.data is data


def test_results_after_resume_are_still_logged_as_played(
    qtbot: object, temp_dir: Path
) -> None:
    """Once a resumed game's results are saved, it's played, not in progress."""
    states = temp_dir / "states"
    write_save(states, "2222", SF2)
    results = sf1_results() + [
        GameResult(SF2, "p0", "Ziggy", 900, 700, "Fun-2222", "win", "s2"),
        GameResult(SF2, "p4", "P4", 0, 0, "Fun-2222", "loss", "s2"),
        GameResult(SF2, "p5", "P5", 0, 0, "Fun-2222", "loss", "s2"),
    ]
    panel = make_panel(qtbot, write_tournament(temp_dir / "t", results))
    panel.states_dir = states
    panel.reload()
    assert panel.saves == {}
    assert list_texts(panel.games_list)[1] == f"{SF2}: played, won by Ziggy"


def test_resume_is_refused_once_a_saved_player_drops_out(
    qtbot: object, temp_dir: Path
) -> None:
    """A save whose player dropped out stays in progress but can't resume."""
    states = temp_dir / "states"
    write_save(states, "2222", SF2)
    panel = make_panel(qtbot, write_tournament(temp_dir / "t", sf1_results()))
    panel.states_dir = states
    panel.reload()
    panel.select_game(SF2)
    assert panel.resume_problem() is None
    assert panel.resume_button.isEnabled()

    panel.dropouts = [Dropout("p4", "Semifinals", DROP_REPLACE, other_id="p9")]
    panel.select_game("Semifinals: SF 3")
    panel.select_game(SF2)
    assert panel.resume_problem().startswith("P4 dropped out")
    assert not panel.resume_button.isEnabled()
    assert "Can't resume: P4 dropped out" in panel.status_label.text()
    requested = []
    panel.resume_requested.connect(requested.append)
    panel.resume_selected()
    assert requested == []


def test_resume_is_refused_for_a_player_who_cant_play_the_game(
    qtbot: object, temp_dir: Path
) -> None:
    """A saved player who played this round already can't be resumed into it."""
    states = temp_dir / "states"
    save = write_save(states, "2222", SF2)
    state = json.loads((save / "general.json").read_text(encoding="utf-8"))
    state["players"][1]["tournament_player_id"] = "p1"
    state["players"][1]["tournament_player_name"] = "P1"
    (save / "general.json").write_text(json.dumps(state), encoding="utf-8")
    panel = make_panel(qtbot, write_tournament(temp_dir / "t", sf1_results()))
    panel.states_dir = states
    panel.reload()
    panel.select_game(SF2)
    assert panel.resume_problem() == (
        f"P1 can no longer play {SF2}, so this game can't be resumed. "
        "Start it again with new players."
    )
    assert not panel.resume_button.isEnabled()


def test_a_dropout_after_the_resume_is_ready_turns_resume_off(
    tournament_welcome: tuple, temp_dir: Path
) -> None:
    """Resume! is checked again, so a later dropout stops it."""
    widget, game, _parent = tournament_welcome
    ResumeGame.install(game, TournamentGameRef("Fun", SF2))
    panel = widget.tournament_panel
    panel.states_dir = temp_dir / "states"
    write_save(panel.states_dir, "2222", SF2)
    panel.reload()
    panel.select_game(SF2)
    panel.resume_button.click()
    game.resume_claimed = 2
    widget.check_start()
    assert widget.tournament_start_button.isEnabled()
    panel.dropouts = [Dropout("p0", "Semifinals", DROP_REPLACE, other_id="p9")]
    widget.check_start()
    assert not widget.tournament_start_button.isEnabled()
    assert panel.status_label.text().startswith("Ziggy dropped out")
    widget.on_start_clicked()
    assert game.start_game_calls == 0


def test_picking_a_podium_while_the_save_loads_keeps_the_resume(
    tournament_welcome: tuple, temp_dir: Path
) -> None:
    """A podium pick during the read doesn't start loading the board instead."""
    widget, game, _parent = tournament_welcome
    ResumeGame.install(game, TournamentGameRef("Fun", SF2))
    panel = widget.tournament_panel
    panel.states_dir = temp_dir / "states"
    write_save(panel.states_dir, "2222", SF2)
    panel.reload()
    panel.select_game(SF2)
    loader = DeferredLoader()
    widget.loader = loader
    panel.resume_button.click()
    assert panel.status_label.text() == "Loading the saved game..."
    assert not widget.tournament_start_button.isEnabled()
    panel.choose(0, "p0")
    assert len(loader.pending) == 1
    assert widget.built == [["2222"]]
    loader.pending.pop()()
    assert game.applied
    assert widget.tournament_start_button.text() == "Resume!"


def test_choosing_another_game_while_the_save_loads_drops_it(
    tournament_welcome: tuple, temp_dir: Path
) -> None:
    """A different game during the read loads that board; the read is ignored."""
    widget, game, _parent = tournament_welcome
    ResumeGame.install(game, TournamentGameRef("Fun", SF2))
    panel = widget.tournament_panel
    panel.states_dir = temp_dir / "states"
    write_save(panel.states_dir, "2222", SF2)
    panel.reload()
    panel.select_game(SF2)
    loader = DeferredLoader()
    widget.loader = loader
    panel.resume_button.click()
    read = loader.pending.pop()
    panel.games_list.setCurrentRow(-1)
    read()
    assert game.applied == []
    assert widget.tournament_start_button.text() == "Start!"


def test_welcome_status_says_why_a_save_cant_resume(
    tournament_welcome: tuple, temp_dir: Path
) -> None:
    """The welcome screen keeps the panel's "Can't resume" line (HOST.md)."""
    widget, game, _parent = tournament_welcome
    panel = widget.tournament_panel
    panel.states_dir = temp_dir / "states"
    write_save(panel.states_dir, "2222", SF2)
    panel.reload()
    panel.dropouts = [Dropout("p4", "Semifinals", DROP_REPLACE, other_id="p9")]
    panel.select_game(SF2)
    widget.check_start()
    status = panel.status_label.text()
    assert "Can't resume: P4 dropped out" in status
    assert not panel.resume_button.isEnabled()
