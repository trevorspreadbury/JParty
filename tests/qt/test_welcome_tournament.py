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
    PLAYED_COLOR,
    SIGNATURE_LINES,
    SIGNED_NAME_TEXT,
    TournamentPlayPanel,
    TournamentResultsDialog,
    phone_label,
    signature_pixmap,
)
from jparty.ui.widgets.welcome import ContestantIntro, Welcome
from tests.qt.test_tournament_games import board, select_rows
from tests.qt.test_tournament_roster import FakeFetcher, make_editor
from tests.qt.test_welcome_widget import DeferredLoader, ImmediateLoader, StubGame

pytestmark = pytest.mark.qt

SF1 = "Semifinals: SF 1"
SF2 = "Semifinals: SF 2"
FINAL = "Final: Final"


def write_tournament(
    root: object, results: list[GameResult] | None = None, **boards: object
) -> object:
    """Save a nine-player tournament with boards for SF 1 and SF 2.

    ``boards`` adds more, by game key with spaces and colons as underscores
    (``Final_Final="9999"``).
    """
    slots = [PlayerSlot(f"P{index}", player_id=f"p{index}") for index in range(9)]
    slots[0] = PlayerSlot(
        "Ziggy", SignUp("t", "Jane Smith", "teacher", "Chicago"), player_id="p0"
    )
    extra = {
        name.replace("__", ": ").replace("_", " "): board(str(game_id))
        for name, game_id in boards.items()
    }
    settings = TournamentSettings(
        "Fun",
        boards={SF1: board("1111"), SF2: board("2222"), **extra},
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
    assert players[:4] == [
        "Ziggy",
        "P1 (played the Semifinals)",
        "P2 (played the Semifinals)",
        "P3 (played the Semifinals)",
    ]
    greyed = [
        panel.players_list.item(row).foreground().color() == PLAYED_COLOR
        for row in range(4)
    ]
    assert greyed == [False, True, True, True]


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


class Phone(SimpleNamespace):
    """A connected phone's player; hashable, as the scoreboard needs."""

    __hash__ = object.__hash__

    def __init__(self, name: str, player_number: int) -> None:
        """Start the phone's player on $0."""
        super().__init__(name=name, player_number=player_number, score=0)


class TournamentGame(StubGame):
    """A stub game that seats phones and records tournament starts."""

    def __init__(self, phones: int = 3) -> None:
        """Connect ``phones`` phones with no board loaded."""
        super().__init__()
        self.source_data = self.data
        self.data = None
        self.players = [Phone(f"Phone {index}", index) for index in range(phones)]
        self.tournament_calls = []

    def startable(self) -> bool:
        """Start needs a board and a phone."""
        return self.data is not None and bool(self.players)

    def set_tournament_game(self, ref: object, players: list | None = None) -> None:
        """Record what the welcome screen seated."""
        self.tournament_calls.append((ref, list(players or [])))

    def remove_player(self, player: object) -> None:
        """Ignore the scoreboard's remove button."""

    def move_player_up(self, player: object) -> None:
        """Ignore the scoreboard's ▲ button."""

    def move_player_down(self, player: object) -> None:
        """Ignore the scoreboard's ▼ button."""


class IntroParent(QWidget):
    """Captures the welcome screen's introduction request."""

    def __init__(self) -> None:
        """Start with no introduction shown."""
        super().__init__()
        self.intro = None
        self.preview_start = None
        self.returned_to_welcome = 0

    def _set_welcome_enabled(self, enabled: bool) -> None:
        """Enable or disable the welcome screen, as the host window does."""
        for welcome in self.findChildren(Welcome):
            welcome.setDisabled(not enabled)

    def load_contestant_intro(self, lines: list[str], on_start: object) -> None:
        """Show the introduction widget, with the welcome screen disabled."""
        self._set_welcome_enabled(False)
        self.intro = ContestantIntro(lines, on_back=lambda: None, on_start=on_start)

    def load_question_media_preview(
        self, questions: list, on_start: object = None
    ) -> None:
        """Keep the media preview's Start callback; the welcome stays disabled."""
        self._set_welcome_enabled(False)
        self.preview_start = on_start

    def show_welcome_from_preview(self) -> None:
        """Count returns to the welcome screen, and enable it again."""
        self.returned_to_welcome += 1
        self._set_welcome_enabled(True)


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
        "Phone 0",
        "Phone 1",
        "Phone 2",
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
    assert _parent.intro is None
    assert game.start_game_calls == 0


def _ready_to_start(widget: Welcome, expect_enabled: bool = True) -> None:
    """Pick SF2 and three eligible players, so Start! turns on."""
    panel = widget.tournament_panel
    panel.select_game(SF2)
    for podium, player_id in enumerate(("p0", "p4", "p5")):
        panel.choose(podium, player_id)
    assert widget.tournament_start_button.isEnabled() is expect_enabled


@pytest.mark.parametrize("change", ["drop", "join"])
def test_start_game_rechecks_phones_after_the_intro(
    tournament_welcome: tuple, change: str
) -> None:
    """A phone joining or dropping during the intro stops Start Game."""
    widget, game, parent = tournament_welcome
    _ready_to_start(widget)
    widget.tournament_start_button.click()
    assert parent.intro is not None

    if change == "drop":
        game.players = game.players[:2]
    else:
        game.players.append(SimpleNamespace(name="Phone 3", player_number=3))
    parent.intro.start_button.click()

    assert game.start_game_calls == 0
    assert game.tournament_calls[-1] == (None, [])
    assert parent.returned_to_welcome == 1
    assert not widget.tournament_start_button.isEnabled()
    assert "phone" in widget.tournament_panel.status_label.text().lower()


def test_media_preview_start_rechecks_phones(tournament_welcome: tuple) -> None:
    """The local-media preview's Start re-checks too, then seats and starts."""
    widget, game, parent = tournament_welcome
    _ready_to_start(widget)
    widget.preview_questions = lambda: [(0, object())]
    widget.tournament_start_button.click()
    parent.intro.start_button.click()
    assert parent.preview_start is not None
    assert game.start_game_calls == 0

    game.players = game.players[:2]
    parent.preview_start()
    assert game.start_game_calls == 0
    assert parent.returned_to_welcome == 1

    game.players.append(SimpleNamespace(name="Phone 2", player_number=2))
    parent.preview_start()
    assert game.start_game_calls == 1
    assert game.tournament_calls[-1][0] == TournamentGameRef("Fun", SF2)


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


def test_unreadable_results_after_a_game_block_start(
    tournament_welcome: tuple, temp_dir: object, monkeypatch: object
) -> None:
    """If results.csv can't be read after a game, Start stays off and says why."""
    widget, game, _parent = tournament_welcome
    panel = widget.tournament_panel
    results_path = temp_dir / "Fun" / "results.csv"
    good_text = results_path.read_text(encoding="utf-8")
    results_path.write_text(good_text.replace(",", ";"), encoding="utf-8")
    widget.restart()

    _ready_to_start(widget, expect_enabled=False)
    assert not widget.tournament_start_button.isEnabled()
    assert "Couldn't read the tournament" in panel.status_label.text()

    # Fix Results won't open over results it couldn't read.
    opened = []
    monkeypatch.setattr(
        TournamentResultsDialog, "exec", lambda self: opened.append(self) or 0
    )
    panel.fix_results()
    assert opened == []
    assert "Couldn't read the tournament" in panel.status_label.text()

    # Once the file is fixed, Fix Results reads it again and Start comes back.
    results_path.write_text(good_text, encoding="utf-8")
    panel.fix_results()
    assert len(opened) == 1
    assert panel.load_error is None
    _ready_to_start(widget)


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


def _played_editor(qtbot: object, temp_dir: object) -> tuple[object, object]:
    """Return a tournament editor for a tournament whose SF 1 was played."""
    from jparty.domain.tournament_store import load_tournament

    folder = write_tournament(temp_dir, sf1_results())
    settings, slots = load_tournament(folder)
    editor = make_editor(qtbot, temp_dir, FakeFetcher(), settings=settings, slots=slots)
    return editor, folder


def test_played_board_cant_be_set_or_assigned(qtbot: object, temp_dir: object) -> None:
    """Set Board and Assign to Selected Game refuse a played game too."""
    editor, _folder = _played_editor(qtbot, temp_dir)
    games = editor.games
    games.pick_board = lambda *args: pytest.fail("asked for a played game's board")
    games.set_board(SF1)
    assert games.boards[SF1] == board("1111")
    assert "has been played" in games.summary_label.text()

    games.unassigned = [board("3333")]
    games._redraw()
    select_rows(games.table, 0)
    games.pool_list.setCurrentRow(0)
    assert not games.assign_pool_button.isEnabled()
    games.assign_selected_pool_board()
    assert games.boards[SF1] == board("1111")
    assert games.unassigned == [board("3333")]


def test_lock_refreshes_for_games_played_since_opening(
    qtbot: object, temp_dir: object
) -> None:
    """A game played while the editor was open locks when it refreshes."""
    editor, folder = _played_editor(qtbot, temp_dir)
    games = editor.games
    assert not games.table.item(1, 2).text().endswith(PLAYED_SUFFIX)
    save_results(
        folder,
        sf1_results()
        + [
            GameResult(SF2, "p4", "P4", 1, 1, "Fun-2222", "win", "s2"),
            GameResult(SF2, "p5", "P5", 0, 0, "Fun-2222", "loss", "s2"),
            GameResult(SF2, "p0", "Ziggy", 0, 0, "Fun-2222", "loss", "s2"),
        ],
    )
    editor.refresh_played()
    assert games.table.item(1, 2).text().endswith(PLAYED_SUFFIX)
    select_rows(games.table, 1)
    assert not games.set_board_button.isEnabled()


def test_bracket_that_drops_a_played_game_cant_be_saved(
    qtbot: object, temp_dir: object
) -> None:
    """Re-planning away a played game warns, and Save refuses it."""
    from jparty.domain.tournament import TournamentOptions, plan_tournament
    from jparty.domain.tournament_store import load_tournament
    from tests.qt.test_tournament_roster import click_save

    editor, folder = _played_editor(qtbot, temp_dir)
    games = editor.games
    games.set_plan(plan_tournament(TournamentOptions(3)))
    assert games.dropped_played_games() == [SF1]
    assert "must keep it" in games.summary_label.text()

    click_save(editor)
    assert "must keep it" in editor.status_label.text()
    settings, _slots = load_tournament(folder)
    assert settings.boards[SF1] == board("1111")

    # Changing the bracket back puts the board back and allows saving.
    games.set_plan(plan_tournament(TournamentOptions(9)))
    assert games.dropped_played_games() == []
    assert games.boards[SF1] == board("1111")


@pytest.fixture()
def deferred_welcome(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> tuple[Welcome, TournamentGame, DeferredLoader]:
    """Return a tournament welcome screen whose board loads wait for the test.

    Nothing has been played, so both semifinals can be picked. A board for
    game ``"fail"`` raises when built.
    """
    game = TournamentGame()

    def build(selections: list[dict]) -> object:
        """Return a board named for its game, or raise for ``"fail"``."""
        game_id = selections[0]["game_id"]
        if game_id == "fail":
            raise RuntimeError("J-Archive is down")
        data = deepcopy(game.source_data)
        data.comments = game_id
        return data

    monkeypatch.setattr(
        welcome_module, "build_game_from_board_selection_configs", build
    )
    parent = IntroParent()
    qtbot.addWidget(parent)
    widget = Welcome(game, parent)
    loader = DeferredLoader()
    widget.loader = loader
    # Keep the parent alive; Qt deletes the welcome screen with it.
    loader.parent = parent
    assert widget.enter_tournament_mode(write_tournament(temp_dir))
    return widget, game, loader


def test_board_for_a_game_no_longer_picked_is_ignored(deferred_welcome: tuple) -> None:
    """A board that loads after the host picked another game isn't used."""
    widget, game, loader = deferred_welcome
    widget.tournament_panel.select_game(SF1)
    widget.tournament_panel.select_game(SF2)
    sf1_load, sf2_load = loader.pending

    sf2_load()
    assert game.data.comments == "2222"
    sf1_load()
    assert game.data.comments == "2222"
    assert game._session_game_id == "2222"


def test_board_arriving_after_leaving_tournament_mode_is_ignored(
    deferred_welcome: tuple, temp_dir: object
) -> None:
    """Leaving, or leaving and coming back, drops a board still loading."""
    widget, game, loader = deferred_welcome
    widget.tournament_panel.select_game(SF2)
    widget.tournament_panel.leave_button.click()
    loader.pending.pop()()
    assert game.data is None
    assert not widget.tournament_mode

    widget.tournament_panel.select_game(SF2)
    assert loader.pending == []
    assert widget.enter_tournament_mode(temp_dir / "Fun")
    widget.tournament_panel.select_game(SF1)
    widget.tournament_panel.select_game(SF2)
    loader.pending.pop()()
    assert game.data.comments == "2222"
    loader.pending.pop()()
    assert game.data.comments == "2222"


def test_board_that_fails_to_load_says_so(
    deferred_welcome: tuple, temp_dir: object
) -> None:
    """A board that can't be built leaves Start off and tells the host why."""
    from jparty.domain.tournament_store import load_tournament, save_tournament

    widget, game, loader = deferred_welcome
    settings, slots = load_tournament(temp_dir / "Fun")
    settings.boards[SF2] = board("fail")
    save_tournament(temp_dir, settings, slots)
    assert widget.enter_tournament_mode(temp_dir / "Fun")
    widget.tournament_panel.select_game(SF2)
    for podium, player_id in enumerate(("p0", "p4", "p5")):
        widget.tournament_panel.choose(podium, player_id)
    loader.pending.pop()()

    assert game.data is None
    assert "Couldn't load this game's board: J-Archive is down" in (
        widget.summary_label.text()
    )
    assert not widget.tournament_start_button.isEnabled()


def _signature() -> str:
    """Return a signed name as phones send it: a PNG data URL."""
    from base64 import urlsafe_b64encode

    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtGui import QColor, QImage

    image = QImage(300, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("#1010a1"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return "data:image/png;base64," + urlsafe_b64encode(bytes(buffer.data())).decode()


def test_podium_shows_the_signature_a_phone_signed_in_with(qtbot: object) -> None:
    """A signed name is shown as the image itself, sized to the text."""
    panel = TournamentPlayPanel()
    qtbot.addWidget(panel)
    panel.apply_scale(800)
    panel.set_phones(["Ann", _signature()])

    assert panel.phone_labels[0].text() == "Ann"
    signed = panel.phone_labels[1]
    assert signed.text() == ""
    assert signed.pixmap().height() == panel._font_pixels * SIGNATURE_LINES
    assert signed.toolTip() == SIGNED_NAME_TEXT
    assert panel.phone_labels[2].text() == NO_PHONE_TEXT

    # Rescaling redraws it; a phone that leaves goes back to text.
    panel.apply_scale(1200)
    assert signed.pixmap().height() == panel._font_pixels * SIGNATURE_LINES
    panel.set_phones(["Ann"])
    assert signed.text() == NO_PHONE_TEXT
    assert signed.pixmap().isNull()


def test_signature_pixmap_ignores_typed_and_broken_names() -> None:
    """Only a readable PNG data URL becomes an image."""
    assert signature_pixmap("Ann") is None
    assert signature_pixmap(None) is None
    assert signature_pixmap("data:image/png;base64,not-a-png") is None
    assert signature_pixmap(_signature()) is not None


def test_tournament_mode_always_reveals_triple_stumper_answers(
    tournament_welcome: tuple,
) -> None:
    """The reveal option is hidden and on in tournament mode, then restored."""
    widget, game, parent = tournament_welcome
    assert widget.reveal_answers_radio.isHidden()
    assert game.reveal_answers_after_triple_stumper_enabled()

    _ready_to_start(widget)
    game.set_reveal_answers_after_triple_stumper(False)
    widget.tournament_start_button.click()
    parent.intro.start_button.click()
    assert game.start_game_calls == 1
    assert game.reveal_answers_after_triple_stumper_enabled()

    # Back in the lobby after the game, the welcome screen is enabled again.
    widget.setDisabled(False)
    widget.tournament_panel.leave_button.click()
    assert not widget.reveal_answers_radio.isHidden()
    assert not widget.reveal_answers_radio.isChecked()
    assert not game.reveal_answers_after_triple_stumper_enabled()


def test_footer_buttons_stay_readable_in_tournament_mode(
    tournament_welcome: tuple,
) -> None:
    """Quit, Show help, and Tournament keep a usable height beside the panel."""
    widget, _game, _parent = tournament_welcome
    widget.resize(1280, 720)
    widget.resizeEvent(None)
    for button in (widget.quit_button, widget.help_button, widget.tournament_button):
        assert button.minimumHeight() >= 32
    widget.tournament_panel.leave_button.click()
    assert widget.quit_button.minimumHeight() == 0


class FakeMediaPreview(QWidget):
    """Stands in for QuestionMediaPreview; keeps the Start callback."""

    instances: list = []

    def __init__(
        self,
        game: object,
        questions: list,
        on_back: object,
        on_start: object,
        parent: object = None,
    ) -> None:
        """Record ``on_start`` for the test to call."""
        super().__init__(parent)
        self.on_start = on_start
        FakeMediaPreview.instances.append(self)


@pytest.fixture()
def host_window_welcome(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> tuple[object, Welcome, TournamentGame]:
    """Return the real host window, its welcome screen in tournament mode."""
    from jparty.ui.windows import display as display_module
    from tests.qt.test_display_window import StubHostDisplayWindow

    game = TournamentGame()
    game.buzzer_controller = SimpleNamespace(host=lambda: "localhost")
    monkeypatch.setattr(
        welcome_module,
        "build_game_from_board_selection_configs",
        lambda selections: deepcopy(game.source_data),
    )
    FakeMediaPreview.instances = []
    monkeypatch.setattr(display_module, "QuestionMediaPreview", FakeMediaPreview)
    host = StubHostDisplayWindow(game)
    qtbot.addWidget(host)
    widget = host.welcome_widget
    widget.loader = ImmediateLoader()
    assert widget.enter_tournament_mode(write_tournament(temp_dir, sf1_results()))
    host.scoreboard.refresh_players()
    return host, widget, game


@pytest.mark.parametrize("media", [False, True])
def test_real_host_window_seats_the_players_then_starts(
    host_window_welcome: tuple, media: bool
) -> None:
    """Through the real host window, Start Game seats the players and starts.

    With local media, the preview's Start must be the tournament's seating
    step, not a bare ``start_game``.
    """
    host, widget, game = host_window_welcome
    if media:
        widget.preview_questions = lambda: [(0, object())]
    _ready_to_start(widget)
    widget.tournament_start_button.click()
    intro = host.preview_widget
    assert isinstance(intro, ContestantIntro)
    assert not widget.isEnabled()
    intro.start_button.click()

    if media:
        assert game.start_game_calls == 0
        (preview,) = FakeMediaPreview.instances
        preview.on_start()
    assert game.start_game_calls == 1
    assert game.tournament_calls[-1][0] == TournamentGameRef("Fun", SF2)


def test_back_in_the_lobby_the_phones_can_be_fixed(host_window_welcome: tuple) -> None:
    """When a 4th phone stops Start Game, remove and reorder work again."""
    host, widget, game = host_window_welcome
    _ready_to_start(widget)
    widget.tournament_start_button.click()
    assert all(
        not pw.remove_button.isVisible() for pw in host.scoreboard.player_widgets
    )

    game.players.append(Phone("Phone 3", 3))
    host.scoreboard.refresh_players()
    host.preview_widget.start_button.click()

    assert game.start_game_calls == 0
    assert host.preview_widget is None
    assert widget.isEnabled()
    widgets = host.scoreboard.player_widgets
    assert len(widgets) == 4
    assert all(pw.remove_button.isVisibleTo(host) for pw in widgets)
    assert all(pw.remove_button.isEnabled() for pw in widgets)
    assert [pw.up_button.isEnabled() for pw in widgets] == [False, True, True, True]
    assert [pw.down_button.isEnabled() for pw in widgets] == [True, True, True, False]


def test_reopening_the_tournament_window_locks_newly_played_games(
    qtbot: object, temp_dir: object
) -> None:
    """A game played while the window was hidden is locked when it reopens."""
    from jparty.domain.tournament_store import load_tournament
    from tests.qt.test_tournament_roster import make_window

    folder = write_tournament(temp_dir, sf1_results())
    window = make_window(qtbot, temp_dir)
    window._open_editor(*load_tournament(folder))
    window.show()
    games = window.editor.games
    assert not games.table.item(1, 2).text().endswith(PLAYED_SUFFIX)
    window.hide()

    save_results(
        folder,
        sf1_results()
        + [
            GameResult(SF2, "p4", "P4", 1, 1, "Fun-2222", "win", "s2"),
            GameResult(SF2, "p5", "P5", 0, 0, "Fun-2222", "loss", "s2"),
            GameResult(SF2, "p0", "Ziggy", 0, 0, "Fun-2222", "loss", "s2"),
        ],
    )
    window.show()
    assert games.table.item(1, 2).text().endswith(PLAYED_SUFFIX)


def all_semifinal_results() -> list[GameResult]:
    """Return results for all three Semifinals, won by P1, P4, and P7."""
    return sf1_results() + [
        GameResult(SF2, "p4", "P4", 900, 700, "Fun-2222", "win", "s2"),
        GameResult(SF2, "p5", "P5", 100, 100, "Fun-2222", "loss", "s2"),
        GameResult(SF2, "p6", "P6", 0, 0, "Fun-2222", "loss", "s2"),
        GameResult("Semifinals: SF 3", "p7", "P7", 900, 700, "Fun-3", "win", "s3"),
        GameResult("Semifinals: SF 3", "p8", "P8", 100, 100, "Fun-3", "loss", "s3"),
        GameResult("Semifinals: SF 3", "p0", "Ziggy", 0, 0, "Fun-3", "loss", "s3"),
    ]


def combo_ids(combo: object) -> list[str]:
    """Return a podium picker's player ids, without the "Choose" entry."""
    return [combo.itemData(index) for index in range(1, combo.count())]


def test_final_offers_only_the_semifinal_winners(
    qtbot: object, temp_dir: object
) -> None:
    """Once the Semifinals are decided, only their winners can sit the Final."""
    folder = write_tournament(temp_dir, all_semifinal_results(), Final__Final=9999)
    panel = make_panel(qtbot, folder)
    panel.select_game(FINAL)
    assert combo_ids(panel.podium_combos[0]) == ["p1", "p4", "p7"]
    players = list_texts(panel.players_list)
    assert "P1 (won, in the Final)" in players
    assert "P5 (out)" in players


def test_later_round_says_why_no_one_can_play_it_yet(
    qtbot: object, temp_dir: object
) -> None:
    """With Semifinals left to play, the Final offers no one and says why."""
    folder = write_tournament(temp_dir, sf1_results(), Final__Final=9999)
    panel = make_panel(qtbot, folder)
    panel.select_game(FINAL)
    assert combo_ids(panel.podium_combos[0]) == []
    assert panel.problem(3) == (
        "The Semifinals aren't finished: 2 games left (SF 2, SF 3)."
    )


def test_results_that_no_longer_add_up_are_flagged(
    qtbot: object, temp_dir: object
) -> None:
    """A Final played by someone who didn't win a Semifinal shows a warning."""
    results = all_semifinal_results() + [
        GameResult(FINAL, "p1", "P1", 1, 1, "Fun-9", "win", "f"),
        GameResult(FINAL, "p4", "P4", 0, 0, "Fun-9", "loss", "f"),
        GameResult(FINAL, "p5", "P5", 0, 0, "Fun-9", "loss", "f"),
    ]
    panel = make_panel(qtbot, write_tournament(temp_dir, results))
    assert not panel.conflicts_label.isHidden()
    assert "Final: P5 played, but they didn't advance into the Final." in (
        panel.conflicts_label.text()
    )

    panel = make_panel(
        qtbot, write_tournament(temp_dir / "ok", all_semifinal_results())
    )
    assert panel.conflicts_label.isHidden()


# Tiebreakers

QF = "Quarterfinals"


def write_tied_tournament(root: object) -> object:
    """Save a 12-player tournament whose Quarterfinals end with a tie.

    The four Quarterfinals are won by ``w1``..``w4``. Of the eight others,
    ``e`` and ``f`` are tied at 400 for the last of five wildcard spots.
    """
    ids = ["w1", "w2", "w3", "w4", *"abcdefgh"]
    slots = [PlayerSlot(player_id.upper(), player_id=player_id) for player_id in ids]
    settings = TournamentSettings("Tied", boards={SF1: board("1111")})
    folder = save_tournament(root, settings, slots)
    losers = {"a": 800, "b": 700, "c": 600, "d": 500, "e": 400, "f": 400, "g": 200}
    losers["h"] = 100
    names = list(losers)
    results = []
    for game in range(4):
        key = f"{QF}: QF {game + 1}"
        winner = f"w{game + 1}"
        results.append(GameResult(key, winner, winner.upper(), 5000, 0, "g", "win"))
        for player_id in names[2 * game : 2 * game + 2]:
            results.append(
                GameResult(
                    key, player_id, player_id.upper(), losers[player_id], 0, "g", "loss"
                )
            )
    save_results(folder, results)
    return folder


def test_open_tie_is_listed_first_with_its_players(
    qtbot: object, temp_dir: object
) -> None:
    """The tie comes first in Games; picking it shows who plays, in order."""
    panel = make_panel(qtbot, write_tied_tournament(temp_dir))
    assert list_texts(panel.games_list)[0] == (
        "Tiebreaker: E, F for the last wildcard spot in the Quarterfinals"
    )
    panel.games_list.setCurrentRow(0)
    assert panel.selected_key() is None
    assert panel.selected_tie().players == ("e", "f")
    assert [combo.currentText() for combo in panel.podium_combos] == ["E", "F", "-"]
    assert not any(combo.isEnabled() for combo in panel.podium_combos)
    assert panel.problem(1) == (
        "Wait for 2 phones to join (1 so far), in this order: E, F."
    )
    assert panel.problem(2) is None
    session = panel.tiebreaker_session()
    assert session.players == (("e", "E"), ("f", "F"))
    assert session.tournament == "Tied"

    # The Semifinals wait for the tie, and say so.
    panel.select_game(SF1)
    assert panel.problem(3).startswith("E, F are tied at $400")


def test_saved_tiebreaker_settles_the_tie(qtbot: object, temp_dir: object) -> None:
    """Once the tiebreaker is saved, the tie is gone and its winner advances."""
    from jparty.domain.tournament_advancement import Tiebreak
    from jparty.domain.tournament_store import record_tiebreak

    folder = write_tied_tournament(temp_dir)
    record_tiebreak(folder, Tiebreak(QF, frozenset("ef"), "f", "F"))
    panel = make_panel(qtbot, folder)
    assert not list_texts(panel.games_list)[0].startswith("Tiebreaker")
    players = list_texts(panel.players_list)
    assert "F (wildcard, in the Semifinals)" in players
    assert "E (out)" in players
    panel.select_game(SF1)
    assert "f" in combo_ids(panel.podium_combos[0])
    assert "e" not in combo_ids(panel.podium_combos[0])


def test_start_plays_the_selected_tiebreaker(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """With one phone per tied player, Start begins the tiebreaker session."""
    game = TournamentGame(phones=2)
    started = []
    game.start_tiebreaker_session = started.append
    parent = IntroParent()
    qtbot.addWidget(parent)
    widget = Welcome(game, parent)
    widget.loader = ImmediateLoader()
    assert widget.enter_tournament_mode(write_tied_tournament(temp_dir))
    widget.tournament_panel.games_list.setCurrentRow(0)
    assert widget.tournament_start_button.isEnabled()
    assert widget.summary_label.text().startswith("E, F are tied at $400")
    assert game.data is None

    game.set_reveal_answers_after_triple_stumper(False)
    widget.tournament_start_button.click()
    (session,) = started
    assert session.tie.players == ("e", "f")
    assert parent.intro is None
    assert game.reveal_answers_after_triple_stumper_enabled()

    game.players = game.players[:1]
    widget.check_start()
    assert not widget.tournament_start_button.isEnabled()
