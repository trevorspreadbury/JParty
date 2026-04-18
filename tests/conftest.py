import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

TEST_TEMP_DIR = Path(__file__).parent / f".runtime_tmp_{os.getpid()}"
TEST_TEMP_DIR.mkdir(exist_ok=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["TMP"] = str(TEST_TEMP_DIR)
os.environ["TEMP"] = str(TEST_TEMP_DIR)
os.environ["TMPDIR"] = str(TEST_TEMP_DIR)
tempfile.tempdir = str(TEST_TEMP_DIR)

from PyQt6.QtWidgets import QApplication

from jparty.game import Board, FinalBoard, Game, GameData, Player, Question


class FakeWave:
    def __init__(self):
        self.play_calls = 0

    def play(self):
        self.play_calls += 1
        return self

    def wait_done(self):
        return None

    def stop(self):
        return None


class FakeSongPlayer:
    def __init__(self):
        self.play_calls = []
        self.final_calls = 0
        self.stop_calls = 0

    def play(self, repeat=False):
        self.play_calls.append(repeat)

    def final(self, repeat=False):
        self.final_calls += 1

    def stop(self):
        self.stop_calls += 1


class FakeTimer:
    instances = []

    def __init__(self, interval, callback, *args, **kwargs):
        self.interval = interval
        self.callback = callback
        self.args = args
        self.kwargs = kwargs
        self.start_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.cancel_calls = 0
        type(self).instances.append(self)

    def start(self):
        self.start_calls += 1

    def pause(self):
        self.pause_calls += 1

    def resume(self):
        self.resume_calls += 1

    def cancel(self):
        self.cancel_calls += 1

    def fire(self):
        self.callback(*self.args, **self.kwargs)


class FakeWaiter:
    def __init__(self):
        self.messages = []
        self.closed = False

    def send(self, message, text=""):
        self.messages.append((message, text))

    def close(self):
        self.closed = True


class FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


class FakeQuestionWidget:
    def __init__(self):
        self.show_question_calls = 0
        self.hint_label = FakeLabel()

    def show_question(self):
        self.show_question_calls += 1


class FakeFinalWindow:
    def __init__(self):
        self.guess_label = FakeLabel()
        self.wager_label = FakeLabel()
        self.winner = None
        self.tie_shown = False

    def show_winner(self, winner):
        self.winner = winner

    def show_tie(self):
        self.tie_shown = True


class FakePlayerWidget:
    def __init__(self, player):
        self.player = player
        self.update_score_calls = 0
        self.run_lights_calls = 0
        self.stop_lights_calls = 0
        self.set_lights_values = []
        self.buzz_hint_calls = 0

    def update_score(self):
        self.update_score_calls += 1

    def run_lights(self):
        self.run_lights_calls += 1

    def stop_lights(self):
        self.stop_lights_calls += 1

    def set_lights(self, value):
        self.set_lights_values.append(value)

    def buzz_hint(self):
        self.buzz_hint_calls += 1


class FakeScoreboard:
    def __init__(self, display):
        self.display = display
        self.refresh_calls = 0

    def refresh_players(self):
        self.refresh_calls += 1
        for player in self.display.game.players:
            self.display.player_widgets.setdefault(player, FakePlayerWidget(player))


class FakeBorders:
    def __init__(self):
        self.lights_values = []
        self.flash_calls = 0
        self.arrowhint_values = []
        self.spacehint_values = []

    def lights(self, value):
        self.lights_values.append(value)

    def flash(self):
        self.flash_calls += 1

    def arrowhints(self, value):
        self.arrowhint_values.append(value)

    def spacehints(self, value):
        self.spacehint_values.append(value)


class FakeBoardWidget:
    def __init__(self):
        self.loaded_rounds = []

    def load_round(self, round_data):
        self.loaded_rounds.append(round_data)


class FakeDisplay:
    def __init__(self, game):
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

    def hide_welcome_widgets(self):
        self.hidden_welcome += 1

    def hide_question(self):
        self.hidden_question += 1

    def load_question(self, question):
        self.loaded_questions.append(question)
        self.question_widget = FakeQuestionWidget()

    def load_final(self, question):
        self.loaded_finals.append(question)

    def load_final_judgement(self):
        self.loaded_final_judgement += 1
        self.final_window = FakeFinalWindow()

    def load_final_graphs(self):
        self.loaded_final_graphs += 1

    def remove_card(self, question):
        self.removed_cards.append(question)

    def restart(self):
        self.restart_calls += 1

    def player_widget(self, player):
        return self.player_widgets.setdefault(player, FakePlayerWidget(player))

    def load_image_review_screen(self, question):
        self.image_review_questions.append(question)


class FakeBuzzerController:
    def __init__(self, game):
        self.game = game
        self.connected_players = []
        self.accepting_players = True
        self.open_wagers_calls = []
        self.prompt_answers_calls = 0
        self.toolate_calls = 0
        self.broadcasts = []
        self.restart_calls = 0
        self.lectern_connections = {}

    def open_wagers(self, players=None):
        self.open_wagers_calls.append(players)
        if players is None:
            players = self.connected_players
        for player in players:
            player.page = "wager"

    def prompt_answers(self):
        self.prompt_answers_calls += 1
        for player in self.connected_players:
            player.page = "answer"

    def toolate(self):
        self.toolate_calls += 1

    def get_player_state_dict(self, player):
        return {
            "name": player.name,
            "score": player.score,
            "player_number": player.player_number,
            "active": False,
            "buzzed": False,
            "finalanswer": getattr(player, "finalanswer", None),
        }

    def broadcast_to_lecterns(self, player_number, state_dict):
        self.broadcasts.append((player_number, state_dict))

    def restart(self):
        self.restart_calls += 1
        self.connected_players = []
        self.accepting_players = True


class TimeController:
    def __init__(self, value=1000.0):
        self.value = value

    def time(self):
        return self.value

    def set(self, value):
        self.value = value

    def advance(self, delta):
        self.value += delta


def build_round(multiplier=1):
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
    return Board(categories, questions, dj=(multiplier == 2))


def build_game_data():
    return GameData(
        rounds=[
            build_round(1),
            build_round(2),
            FinalBoard("Final Category", Question((0, 0), "Final clue", "Final response", "Final Category")),
        ],
        date="January 1, 2026",
        comments="Fixture game",
    )


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def fixture_dir():
    return Path(__file__).parent / "fixtures"


@pytest.fixture()
def temp_dir():
    path = TEST_TEMP_DIR / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


@pytest.fixture()
def sample_general_state(fixture_dir):
    with open(fixture_dir / "general.json", "r") as f:
        return json.load(f)


@pytest.fixture()
def sample_question_history_lines(fixture_dir):
    with open(fixture_dir / "question_history.jsonl", "r") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture()
def sample_custom_game_csv_text(fixture_dir):
    return (fixture_dir / "custom_game.csv").read_text()


@pytest.fixture()
def time_controller():
    return TimeController()


@pytest.fixture()
def game(monkeypatch, temp_dir, time_controller, qapp):
    import jparty.game as game_module

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
def players(game):
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
def game_with_players(game, players):
    return game


@pytest.fixture()
def sample_saved_game_dir(temp_dir, sample_general_state, sample_question_history_lines):
    saved_dir = temp_dir / "saved_game"
    saved_dir.mkdir()
    with open(saved_dir / "general.json", "w") as f:
        json.dump(sample_general_state, f)
    with open(saved_dir / "question_history.jsonl", "w") as f:
        for line in sample_question_history_lines:
            json.dump(line, f)
            f.write("\n")
    return saved_dir
