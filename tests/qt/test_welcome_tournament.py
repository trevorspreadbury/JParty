"""Qt tests for playing a tournament's games from the welcome screen."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from jparty.domain.roster import PlayerSlot, SignUp
from jparty.domain.tournament_play import INTRO_HEADING, GameResult, TournamentGameRef
from jparty.domain.tournament_store import (
    TournamentSettings,
    load_results,
    save_results,
    save_tournament,
)
from jparty.ui.widgets import welcome as welcome_module
from jparty.ui.widgets.tournament_games import PLAYED_SUFFIX
from jparty.ui.widgets.tournament_play import (
    COLUMN_RESULT,
    COLUMN_SCORE,
    NO_PHONE_TEXT,
    SIGNED_NAME_TEXT,
    TournamentPlayPanel,
    TournamentResultsDialog,
    phone_label,
)
from jparty.ui.widgets.welcome import ContestantIntro, Welcome
from tests.qt.test_tournament_games import board, select_rows
from tests.qt.test_tournament_roster import FakeFetcher, make_editor
from tests.qt.test_welcome_widget import ImmediateLoader, StubGame

pytestmark = pytest.mark.qt

SF1 = "Semifinals: SF 1"
SF2 = "Semifinals: SF 2"
FINAL = "Final: Final"


def write_tournament(root: object, results: list[GameResult] | None = None) -> object:
    """Save a nine-player tournament with boards for SF 1 and SF 2."""
    slots = [PlayerSlot(f"P{index}", player_id=f"p{index}") for index in range(9)]
    slots[0] = PlayerSlot(
        "Ziggy", SignUp("t", "Jane Smith", "teacher", "Chicago"), player_id="p0"
    )
    settings = TournamentSettings(
        "Fun",
        boards={SF1: board("1111"), SF2: board("2222")},
    )
    folder = save_tournament(root, settings, slots)
    if results:
        save_results(folder, results)
    return folder


def sf1_results() -> list[GameResult]:
    """Return results for SF 1, won by P1."""
    return [
        GameResult(SF1, "p1", "P1", 900, 700, "Fun-1111", "win", "s1"),
        GameResult(SF1, "p2", "P2", 100, 100, "Fun-1111", "loss", "s1"),
        GameResult(SF1, "p3", "P3", 0, 0, "Fun-1111", "loss", "s1"),
    ]


def list_texts(widget: object) -> list[str]:
    """Return a list widget's item texts."""
    return [widget.item(row).text() for row in range(widget.count())]


def make_panel(qtbot: object, folder: object) -> TournamentPlayPanel:
    """Return a panel showing the tournament in ``folder``."""
    panel = TournamentPlayPanel()
    qtbot.addWidget(panel)
    panel.load(folder)
    return panel


def test_panel_lists_games_and_greys_out_played_ones(
    qtbot: object, temp_dir: object
) -> None:
    """Played games and players are greyed, and played games can't be picked."""
    panel = make_panel(qtbot, write_tournament(temp_dir, sf1_results()))
    assert panel.title_label.text() == "Tournament: Fun"
    texts = list_texts(panel.games_list)
    assert texts[0] == f"{SF1}: played, won by P1"
    assert texts[1] == f"{SF2}: 2222 (Jeopardy!)"
    assert texts[2] == "Semifinals: SF 3: no board"
    assert not panel.games_list.item(0).flags() & Qt.ItemFlag.ItemIsEnabled
    panel.games_list.setCurrentRow(0)
    assert panel.selected_key() is None
    players = list_texts(panel.players_list)
    assert players[:4] == ["Ziggy", "P1 (played)", "P2 (played)", "P3 (played)"]


def test_podiums_offer_only_eligible_players(qtbot: object, temp_dir: object) -> None:
    """Players who already played this round aren't offered again."""
    panel = make_panel(qtbot, write_tournament(temp_dir, sf1_results()))
    panel.select_game(SF2)
    combo = panel.podium_combos[0]
    offered = [combo.itemData(index) for index in range(1, combo.count())]
    assert offered == ["p0", "p4", "p5", "p6", "p7", "p8"]
    assert panel.problem(3) == "Choose a player for each of the 3 podiums."
    for podium, player_id in enumerate(("p0", "p4", "p5")):
        panel.choose(podium, player_id)
    assert panel.problem(2) == "Wait for 3 phones to join (2 so far)."
    assert panel.problem(3) is None
    assert panel.chosen_players() == [("p0", "Ziggy"), ("p4", "P4"), ("p5", "P5")]
    assert panel.game_ref() == TournamentGameRef("Fun", SF2)
    assert panel.intro_lines() == [
        INTRO_HEADING,
        "A teacher from Chicago, Jane Smith (Ziggy)",
        "P4",
        "P5",
    ]


def test_phone_labels() -> None:
    """Podiums show the phone's name, or say a signature or no phone."""
    assert phone_label("Ann") == "Ann"
    assert phone_label("data:image/png;base64,AAAA") == SIGNED_NAME_TEXT
    assert phone_label(None) == NO_PHONE_TEXT


class TournamentGame(StubGame):
    """A stub game that seats phones and records tournament starts."""

    def __init__(self, phones: int = 3) -> None:
        """Connect ``phones`` phones with no board loaded."""
        super().__init__()
        self.source_data = self.data
        self.data = None
        self.players = [
            SimpleNamespace(name=f"Phone {index}", player_number=index)
            for index in range(phones)
        ]
        self.tournament_calls = []

    def startable(self) -> bool:
        """Start needs a board and a phone."""
        return self.data is not None and bool(self.players)

    def set_tournament_game(self, ref: object, players: list | None = None) -> None:
        """Record what the welcome screen seated."""
        self.tournament_calls.append((ref, list(players or [])))


class IntroParent(QWidget):
    """Captures the welcome screen's introduction request."""

    def __init__(self) -> None:
        """Start with no introduction shown."""
        super().__init__()
        self.intro = None

    def load_contestant_intro(self, lines: list[str], on_start: object) -> None:
        """Show the introduction widget, as the host window does."""
        self.intro = ContestantIntro(lines, on_back=lambda: None, on_start=on_start)


@pytest.fixture()
def tournament_welcome(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> tuple[Welcome, TournamentGame, object]:
    """Return a welcome screen in tournament mode, with boards built inline."""
    game = TournamentGame()
    built = []

    def build(selections: list[dict]) -> object:
        """Record the board and return the stub game's data."""
        built.append([selection["game_id"] for selection in selections])
        return deepcopy(game.source_data)

    monkeypatch.setattr(
        welcome_module, "build_game_from_board_selection_configs", build
    )
    parent = IntroParent()
    qtbot.addWidget(parent)
    widget = Welcome(game, parent)
    widget.loader = ImmediateLoader()
    folder = write_tournament(temp_dir, sf1_results())
    assert widget.enter_tournament_mode(folder)
    widget.built = built
    return widget, game, parent


def test_welcome_tournament_mode_swaps_the_controls(tournament_welcome: tuple) -> None:
    """The panel replaces the game id box; Leave brings it back."""
    widget, game, _parent = tournament_welcome
    assert widget.tournament_mode
    assert not widget.tournament_panel.isHidden()
    assert widget.regular_workflow_widget.isHidden()
    assert widget.advanced_options_checkbox.isHidden()
    assert not widget.tournament_button.isEnabled()
    widget.tournament_panel.leave_button.click()
    assert not widget.tournament_mode
    assert widget.tournament_panel.isHidden()
    assert not widget.regular_workflow_widget.isHidden()
    assert game.tournament_calls[-1] == (None, [])


def test_choosing_a_game_loads_its_board_then_start_introduces_players(
    tournament_welcome: tuple,
) -> None:
    """The board loads automatically; Start shows the intro, then starts."""
    widget, game, parent = tournament_welcome
    panel = widget.tournament_panel
    panel.select_game(SF2)
    assert widget.built == [["2222"]]
    assert game.data is not None
    assert game.board_selection_configs()[0]["game_id"] == "2222"
    assert game._session_game_id == "2222"
    assert not widget.tournament_start_button.isEnabled()

    for podium, player_id in enumerate(("p0", "p4", "p5")):
        panel.choose(podium, player_id)
    assert widget.tournament_start_button.isEnabled()
    assert [label.text() for label in panel.phone_labels] == [
        "Phone: Phone 0",
        "Phone: Phone 1",
        "Phone: Phone 2",
    ]
    # Picking players doesn't reload the board.
    assert widget.built == [["2222"]]

    widget.tournament_start_button.click()
    assert parent.intro is not None
    assert parent.intro.title_label.text() == INTRO_HEADING
    assert game.start_game_calls == 0
    parent.intro.start_button.click()
    assert game.start_game_calls == 1
    assert game.tournament_calls[-1] == (
        TournamentGameRef("Fun", SF2),
        [("p0", "Ziggy"), ("p4", "P4"), ("p5", "P5")],
    )


def test_start_waits_for_three_phones(tournament_welcome: tuple) -> None:
    """With two phones, Start stays off and says why."""
    widget, game, _parent = tournament_welcome
    game.players = game.players[:2]
    panel = widget.tournament_panel
    panel.select_game(SF2)
    for podium, player_id in enumerate(("p0", "p4", "p5")):
        panel.choose(podium, player_id)
    assert not widget.tournament_start_button.isEnabled()
    assert "2 so far" in panel.status_label.text()
    widget.on_start_clicked()
    assert game.start_game_calls == 0


def test_after_a_game_the_panel_shows_new_results(
    tournament_welcome: tuple, temp_dir: object
) -> None:
    """Back on the welcome screen, the game just played is greyed out."""
    widget, game, _parent = tournament_welcome
    widget.tournament_panel.select_game(SF2)
    save_results(
        temp_dir / "Fun",
        sf1_results()
        + [
            GameResult(SF2, "p4", "P4", 1, 1, "Fun-2222", "win", "s2"),
            GameResult(SF2, "p5", "P5", 0, 0, "Fun-2222", "loss", "s2"),
            GameResult(SF2, "p0", "Ziggy", 0, 0, "Fun-2222", "loss", "s2"),
        ],
    )
    widget.restart()
    assert widget.tournament_mode
    assert list_texts(widget.tournament_panel.games_list)[1] == (
        f"{SF2}: played, won by P4"
    )
    assert widget.tournament_panel.selected_key() is None
    assert game.data is None


def test_results_dialog_fixes_scores_and_winners(
    qtbot: object, temp_dir: object
) -> None:
    """Edited scores and results are saved; every game needs a winner."""
    folder = write_tournament(temp_dir, sf1_results())
    dialog = TournamentResultsDialog(folder, load_results(folder))
    qtbot.addWidget(dialog)
    dialog.table.item(1, COLUMN_SCORE).setText("1500")
    dialog.table.cellWidget(0, COLUMN_RESULT).setCurrentText("loss")
    dialog.save()
    assert "needs a winner" in dialog.status_label.text()
    dialog.table.cellWidget(1, COLUMN_RESULT).setCurrentText("win")
    dialog.table.item(2, COLUMN_SCORE).setText("lots")
    dialog.save()
    assert "whole numbers" in dialog.status_label.text()
    dialog.table.item(2, COLUMN_SCORE).setText("5")
    dialog.save()
    saved = load_results(folder)
    assert [(r.player_id, r.score, r.result) for r in saved] == [
        ("p1", 900, "loss"),
        ("p2", 1500, "win"),
        ("p3", 5, "loss"),
    ]


def test_deleting_a_games_results_makes_it_playable(
    qtbot: object, temp_dir: object
) -> None:
    """Delete Game's Results drops every row of that game."""
    folder = write_tournament(temp_dir, sf1_results())
    dialog = TournamentResultsDialog(folder, load_results(folder))
    qtbot.addWidget(dialog)
    dialog.table.setCurrentCell(1, 0)
    dialog.delete_button.click()
    assert dialog.table.rowCount() == 0
    dialog.save()
    assert load_results(folder) == []


def test_play_games_saves_then_hands_over_the_folder(
    qtbot: object, temp_dir: object
) -> None:
    """Play Games saves a new tournament first, then asks to play it."""
    editor = make_editor(qtbot, temp_dir, FakeFetcher())
    editor.name_edit.setText("Fun")
    editor.roster.player_spinbox.setValue(9)
    for row in range(9):
        editor.roster.table.item(row, 1).setText(f"Player {row}")
    requested = []
    editor.play_requested.connect(requested.append)
    editor.play_button.click()
    assert requested == [temp_dir / "Fun"]
    assert (temp_dir / "Fun" / "tournament.json").is_file()


def test_play_games_needs_a_working_bracket(qtbot: object, temp_dir: object) -> None:
    """With a bracket that can't work, Play Games explains instead."""
    editor = make_editor(qtbot, temp_dir, FakeFetcher())
    editor.name_edit.setText("Fun")
    editor.roster.player_spinbox.setValue(10)
    requested = []
    editor.play_requested.connect(requested.append)
    editor.play_button.click()
    assert requested == []
    assert "Fix the bracket" in editor.status_label.text()


def test_played_games_lock_their_boards(qtbot: object, temp_dir: object) -> None:
    """A played game's board can't be changed, swapped, or unassigned."""
    folder = write_tournament(temp_dir, sf1_results())
    from jparty.domain.tournament_store import load_tournament

    settings, slots = load_tournament(folder)
    editor = make_editor(qtbot, temp_dir, FakeFetcher(), settings=settings, slots=slots)
    games = editor.games
    assert games.table.item(0, 2).text().endswith(PLAYED_SUFFIX)
    select_rows(games.table, 0)
    assert not games.set_board_button.isEnabled()
    assert not games.unassign_button.isEnabled()
    games.unassign_selected()
    assert SF1 in games.boards
    assert "has been played" in games.summary_label.text()
    select_rows(games.table, 0, 1)
    assert not games.swap_button.isEnabled()
    games.swap_selected()
    assert games.boards[SF1] == board("1111")
    select_rows(games.table, 1)
    assert games.unassign_button.isEnabled()
