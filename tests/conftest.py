"""Conftest module."""

import atexit
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
PROJECT_TEMP_ROOT = Path(__file__).resolve().parents[1] / ".tmp"
PROJECT_TEMP_ROOT.mkdir(exist_ok=True)
TEST_TEMP_DIR = PROJECT_TEMP_ROOT / f"pytest-runtime-{os.getpid()}"
TEST_TEMP_DIR.mkdir(exist_ok=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DATA_DIR", str(TEST_TEMP_DIR / "user_data"))
os.environ.setdefault("JPARTY_DATA_DIR", str(TEST_TEMP_DIR / "user_data"))
os.environ["TMP"] = str(TEST_TEMP_DIR)
os.environ["TEMP"] = str(TEST_TEMP_DIR)
os.environ["TMPDIR"] = str(TEST_TEMP_DIR)
tempfile.tempdir = str(TEST_TEMP_DIR)


def _cleanup_test_temp_dir() -> None:
    """Test cleanup test temp dir."""
    for _ in range(5):
        shutil.rmtree(TEST_TEMP_DIR, ignore_errors=True)
        if not TEST_TEMP_DIR.exists():
            break
        time.sleep(0.1)


from jparty.domain import Board, FinalBoard, Game, GameData, Player, Question

atexit.register(_cleanup_test_temp_dir)


class FakeWave:
    """Test helper for fakewave."""

    def __init__(self) -> None:
        """Test init."""
        self.play_calls = 0

    def play(self) -> object:
        """Test play."""
        self.play_calls += 1
        return self

    def wait_done(self) -> None:
        """Test wait done."""
        return None

    def stop(self) -> None:
        """Test stop."""
        return None


class FakeSongPlayer:
    """Test helper for fakesongplayer."""

    def __init__(self) -> None:
        """Test init."""
        self.play_calls = []
        self.final_calls = 0
        self.stop_calls = 0

    def play(self, repeat: object = False) -> None:
        """Test play."""
        self.play_calls.append(repeat)

    def final(self, repeat: object = False) -> None:
        """Test final."""
        self.final_calls += 1

    def stop(self) -> None:
        """Test stop."""
        self.stop_calls += 1


class FakeTimer:
    """Test helper for faketimer."""

    instances = []

    def __init__(
        self, interval: object, callback: object, *args: object, **kwargs: object
    ) -> None:
        """Test init."""
        self.interval = interval
        self.callback = callback
        self.args = args
        self.kwargs = kwargs
        self.start_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.cancel_calls = 0
        type(self).instances.append(self)

    def start(self) -> None:
        """Test start."""
        self.start_calls += 1

    def pause(self) -> None:
        """Test pause."""
        self.pause_calls += 1

    def resume(self) -> None:
        """Test resume."""
        self.resume_calls += 1

    def cancel(self) -> None:
        """Test cancel."""
        self.cancel_calls += 1

    def fire(self) -> None:
        """Test fire."""
        self.callback(*self.args, **self.kwargs)


class FakeWaiter:
    """Test helper for fakewaiter."""

    def __init__(self) -> None:
        """Test init."""
        self.messages = []
        self.closed = False

    def send(self, message: object, text: object = "") -> None:
        """Test send."""
        self.messages.append((message, text))

    def close(self) -> None:
        """Test close."""
        self.closed = True


class FakeLabel:
    """Test helper for fakelabel."""

    def __init__(self) -> None:
        """Test init."""
        self.text = ""

    def setText(self, text: object) -> None:
        """Test setText."""
        self.text = text


class FakeQuestionWidget:
    """Test helper for fakequestionwidget."""

    def __init__(self) -> None:
        """Test init."""
        self.show_question_calls = 0
        self.hint_label = FakeLabel()

    def show_question(self) -> None:
        """Test show question."""
        self.show_question_calls += 1


class FakeFinalWindow:
    """Test helper for fakefinalwindow."""

    def __init__(self) -> None:
        """Test init."""
        self.guess_label = FakeLabel()
        self.wager_label = FakeLabel()
        self.winner = None
        self.tie_shown = False

    def show_winner(self, winner: object) -> None:
        """Test show winner."""
        self.winner = winner

    def show_tie(self) -> None:
        """Test show tie."""
        self.tie_shown = True


class FakePlayerWidget:
    """Test helper for fakeplayerwidget."""

    def __init__(self, player: object) -> None:
        """Test init."""
        self.player = player
        self.update_score_calls = 0
        self.run_lights_calls = 0
        self.stop_lights_calls = 0
        self.set_lights_values = []
        self.buzz_hint_calls = 0

    def update_score(self) -> None:
        """Test update score."""
        self.update_score_calls += 1

    def run_lights(self) -> None:
        """Test run lights."""
        self.run_lights_calls += 1

    def stop_lights(self) -> None:
        """Test stop lights."""
        self.stop_lights_calls += 1

    def set_lights(self, value: object) -> None:
        """Test set lights."""
        self.set_lights_values.append(value)

    def buzz_hint(self) -> None:
        """Test buzz hint."""
        self.buzz_hint_calls += 1


class FakeScoreboard:
    """Test helper for fakescoreboard."""

    def __init__(self, display: object) -> None:
        """Test init."""
        self.display = display
        self.refresh_calls = 0

    def refresh_players(self) -> None:
        """Test refresh players."""
        self.refresh_calls += 1
        for player in self.display.game.players:
            self.display.player_widgets.setdefault(player, FakePlayerWidget(player))


class FakeBorders:
    """Test helper for fakeborders."""

    def __init__(self) -> None:
        """Test init."""
        self.lights_values = []
        self.flash_calls = 0
        self.arrowhint_values = []
        self.spacehint_values = []

    def lights(self, value: object) -> None:
        """Test lights."""
        self.lights_values.append(value)

    def flash(self) -> None:
        """Test flash."""
        self.flash_calls += 1

    def arrowhints(self, value: object) -> None:
        """Test arrowhints."""
        self.arrowhint_values.append(value)

    def spacehints(self, value: object) -> None:
        """Test spacehints."""
        self.spacehint_values.append(value)


class FakeBoardWidget:
    """Test helper for fakeboardwidget."""

    def __init__(self) -> None:
        """Test init."""
        self.loaded_rounds = []

    def load_round(self, round_data: object) -> None:
        """Test load round."""
        self.loaded_rounds.append(round_data)


class FakeDisplay:
    """Test helper for fakedisplay."""

    def __init__(self, game: object) -> None:
        """Test init."""
        self.game = game
        self.player_widgets = {}
        self.scoreboard = FakeScoreboard(self)
        self.borders = FakeBorders()
        self.board_widget = FakeBoardWidget()
        self.question_widget = FakeQuestionWidget()
        self.final_window = FakeFinalWindow()
        self.hidden_welcome = 0
        self.hidden_question = 0
        self.loaded_questions = []
        self.loaded_finals = []
        self.removed_cards = []
        self.loaded_final_judgement = 0
        self.loaded_final_graphs = 0
        self.restart_calls = 0
        self.image_review_questions = []

    def hide_welcome_widgets(self) -> None:
        """Test hide welcome widgets."""
        self.hidden_welcome += 1

    def hide_question(self) -> None:
        """Test hide question."""
        self.hidden_question += 1

    def load_question(self, question: object) -> None:
        """Test load question."""
        self.loaded_questions.append(question)
        self.question_widget = FakeQuestionWidget()

    def load_final(self, question: object) -> None:
        """Test load final."""
        self.loaded_finals.append(question)

    def load_final_judgement(self) -> None:
        """Test load final judgement."""
        self.loaded_final_judgement += 1
        self.final_window = FakeFinalWindow()

    def load_final_graphs(self) -> None:
        """Test load final graphs."""
        self.loaded_final_graphs += 1

    def remove_card(self, question: object) -> None:
        """Test remove card."""
        self.removed_cards.append(question)

    def restart(self) -> None:
        """Test restart."""
        self.restart_calls += 1

    def player_widget(self, player: object) -> object:
        """Test player widget."""
        return self.player_widgets.setdefault(player, FakePlayerWidget(player))

    def load_image_review_screen(self, question: object) -> None:
        """Test load image review screen."""
        self.image_review_questions.append(question)


class FakeBuzzerController:
    """Test helper for fakebuzzercontroller."""

    def __init__(self, game: object) -> None:
        """Test init."""
        self.game = game
        self.connected_players = []
        self.accepting_players = True
        self.open_wagers_calls = []
        self.prompt_answers_calls = 0
        self.toolate_calls = 0
        self.broadcasts = []
        self.restart_calls = 0
        self.lectern_connections = {}

    def open_wagers(self, players: object = None) -> None:
        """Test open wagers."""
        self.open_wagers_calls.append(players)
        if players is None:
            players = self.connected_players
        for player in players:
            player.page = "wager"

    def prompt_answers(self) -> None:
        """Test prompt answers."""
        self.prompt_answers_calls += 1
        for player in self.connected_players:
            player.page = "answer"

    def toolate(self) -> None:
        """Test toolate."""
        self.toolate_calls += 1

    def get_player_state_dict(self, player: object) -> object:
        """Test get player state dict."""
        return {
            "name": player.name,
            "score": player.score,
            "player_number": player.player_number,
            "active": False,
            "buzzed": False,
            "finalanswer": getattr(player, "finalanswer", None),
        }

    def broadcast_to_lecterns(self, player_number: object, state_dict: object) -> None:
        """Test broadcast to lecterns."""
        self.broadcasts.append((player_number, state_dict))

    def restart(self) -> None:
        """Test restart."""
        self.restart_calls += 1
        self.connected_players = []
        self.accepting_players = True


class TimeController:
    """Test helper for timecontroller."""

    def __init__(self, value: object = 1000.0) -> None:
        """Test init."""
        self.value = value

    def time(self) -> object:
        """Test time."""
        return self.value

    def set(self, value: object) -> None:
        """Test set."""
        self.value = value

    def advance(self, delta: object) -> None:
        """Test advance."""
        self.value += delta


def build_round(multiplier: object = 1) -> object:
    """Test build round."""
    categories = [f"Cat {i}" for i in range(6)]
    questions = []
    for col in range(6):
        for row in range(5):
            questions.append(
                Question(
                    index=(col, row),
                    text=f"Question {multiplier}-{col}-{row}",
                    answer=f"Answer {multiplier}-{col}-{row}",
                    category=categories[col],
                    value=(row + 1) * 200 * multiplier,
                )
            )
    return Board(categories, questions, dj=multiplier == 2)


def build_game_data() -> object:
    """Test build game data."""
    return GameData(
        rounds=[
            build_round(1),
            build_round(2),
            FinalBoard(
                "Final Category",
                Question((0, 0), "Final clue", "Final response", "Final Category"),
            ),
        ],
        date="January 1, 2026",
        comments="Fixture game",
    )


@pytest.fixture(scope="session")
def qapp() -> object:
    """Test qapp."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def fixture_dir() -> object:
    """Test fixture dir."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture()
def temp_dir() -> object:
    """Test temp dir."""
    path = TEST_TEMP_DIR / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


@pytest.fixture()
def sample_general_state(fixture_dir: object) -> object:
    """Test sample general state."""
    with Path(fixture_dir / "general.json").open() as f:
        return json.load(f)


@pytest.fixture()
def sample_question_history_lines(fixture_dir: object) -> object:
    """Test sample question history lines."""
    with Path(fixture_dir / "question_history.jsonl").open() as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture()
def sample_custom_game_csv_text(fixture_dir: object) -> object:
    """Test sample custom game csv text."""
    return (fixture_dir / "custom_game.csv").read_text()


@pytest.fixture()
def time_controller() -> object:
    """Test time controller."""
    return TimeController()


@pytest.fixture()
def game(
    monkeypatch: object, temp_dir: object, time_controller: object, qapp: object
) -> object:
    """Test game."""
    import jparty.domain.game_engine as game_module

    FakeTimer.instances = []
    wave = FakeWave()
    monkeypatch.setattr(game_module, "SongPlayer", FakeSongPlayer)
    monkeypatch.setattr(game_module, "QuestionTimer", FakeTimer)
    monkeypatch.setattr(game_module.time, "time", time_controller.time)
    monkeypatch.setattr(game_module.sa.WaveObject, "from_wave_file", lambda _: wave)
    game = Game()
    game.wave = wave
    game._game_state_dir = temp_dir / "game_state"
    game._game_state_dir.mkdir()
    game._game_started_at = time_controller.time()
    host_display = SimpleNamespace(
        welcome_widget=SimpleNamespace(check_start=lambda: None),
        question_widget=FakeQuestionWidget(),
        load_image_review_screen=lambda question: None,
        borders=FakeBorders(),
    )
    main_display = SimpleNamespace()
    display = FakeDisplay(game)
    game.host_display = host_display
    game.main_display = main_display
    game.dc = display
    game.buzzer_controller = FakeBuzzerController(game)
    game.data = build_game_data()
    game.current_round = game.data.rounds[0]
    return game


@pytest.fixture()
def players(game: object) -> object:
    """Test players."""
    players = [
        Player("Alice", FakeWaiter(), 0),
        Player("Bob", FakeWaiter(), 1),
        Player("Cara", FakeWaiter(), 2),
    ]
    game.players = players
    game.buzzer_controller.connected_players = list(players)
    game.dc.scoreboard.refresh_players()
    return players


@pytest.fixture()
def game_with_players(game: object, players: object) -> object:
    """Test game with players."""
    return game


@pytest.fixture()
def sample_saved_game_dir(
    temp_dir: object,
    sample_general_state: object,
    sample_question_history_lines: object,
) -> object:
    """Test sample saved game dir."""
    saved_dir = temp_dir / "saved_game"
    saved_dir.mkdir()
    with Path(saved_dir / "general.json").open("w") as f:
        json.dump(sample_general_state, f)
    with Path(saved_dir / "question_history.jsonl").open("w") as f:
        for line in sample_question_history_lines:
            json.dump(line, f)
            f.write("\n")
    return saved_dir


def pytest_sessionfinish(session: object, exitstatus: object) -> None:
    """Test pytest sessionfinish."""
    _cleanup_test_temp_dir()
