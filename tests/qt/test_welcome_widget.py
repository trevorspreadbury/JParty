"""Test welcome widget module."""

from copy import deepcopy
from types import SimpleNamespace
from typing import NoReturn

import pytest
from jparty.domain.models import Board, FinalBoard, GameData, Question
from jparty.services.question_media import QuestionMediaStatus
from jparty.ui.widgets.welcome import QuestionMediaPreview, Welcome
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QFileDialog, QLabel, QMessageBox, QWidget

pytestmark = pytest.mark.qt


class StubGame:
    """Test helper for stubgame."""

    def __init__(self) -> None:
        """Test init."""
        categories = [f"Cat {index}" for index in range(6)]
        questions = [
            Question((col, row), f"Q {col}-{row}", f"A {col}-{row}", categories[col])
            for col in range(6)
            for row in range(5)
        ]
        self.data = GameData(
            [
                Board(categories, questions[:30], dj=False),
                Board(categories, questions[:30], dj=True),
                FinalBoard(
                    "Final Category",
                    Question((0, 0), "Final clue", "Final response", "Final Category"),
                ),
            ],
            "January 1, 2026",
            "Fixture game",
        )
        self.resume_expected = None
        self.buzzer_controller = SimpleNamespace(connected_players=[])
        self.start_game_calls = 0
        self.clear_resume_state_calls = 0
        self._selected_round_indices = None
        self._board_selection_configs = []
        self._composed_board_selection_configs = None
        self._composed_game_data = None
        self._session_game_id = ""
        self._reveal_answers_after_triple_stumper = False
        self.resume_claimed = 0

    def start_game(self) -> None:
        """Test start game."""
        self.start_game_calls += 1

    def clear_resume_state(self) -> None:
        """Test clear resume state."""
        self.resume_expected = None
        self.resume_claimed = 0
        self.clear_resume_state_calls += 1

    def prepare_resume_from_dir(self, selected_dir: object) -> object:
        """Test prepare resume from dir."""
        self.resume_expected = 2
        self.resume_claimed = 0
        self.set_selected_round_indices([0, 2])
        return {
            "game_id": "4453",
            "general_state": {
                "players": [{"name": "Alice"}, {"name": "Bob"}],
                "selected_round_indices": [0, 2],
                "reveal_answers_after_triple_stumper": True,
            },
        }

    def startable(self) -> object:
        """Test startable."""
        if self.resume_expected is None:
            return False
        return self.resume_claimed == self.resume_expected

    def set_selected_round_indices(self, indices: object) -> None:
        """Test set selected round indices."""
        self._selected_round_indices = list(indices) if indices is not None else None

    def selected_round_indices(self) -> object:
        """Test selected round indices."""
        if self._selected_round_indices is None:
            return []
        return self._selected_round_indices

    def set_board_selection_configs(self, configs: object) -> None:
        """Test storing board-selection configs."""
        self._board_selection_configs = list(configs) if configs is not None else []

    def board_selection_configs(self) -> object:
        """Test reading board-selection configs."""
        return self._board_selection_configs

    def set_session_game_id(self, game_id: object) -> None:
        """Test storing the current session game id."""
        self._session_game_id = str(game_id)

    def set_composed_game_data(
        self, configs: object, composed_game_data: object | None
    ) -> None:
        """Test storing composed advanced game data."""
        self._composed_board_selection_configs = configs
        self._composed_game_data = composed_game_data

    def matching_composed_game_data(self, configs: object) -> object | None:
        """Test reading composed advanced game data."""
        if configs != self._composed_board_selection_configs:
            return None
        return self._composed_game_data

    def set_reveal_answers_after_triple_stumper(self, enabled: bool) -> None:
        """Test storing the triple-stumper reveal preference."""
        self._reveal_answers_after_triple_stumper = bool(enabled)

    def reveal_answers_after_triple_stumper_enabled(self) -> bool:
        """Test reading the triple-stumper reveal preference."""
        return self._reveal_answers_after_triple_stumper

    def expected_player_count(self) -> object:
        """Test expected player count."""
        return self.resume_expected

    def resume_claim_status(self) -> tuple[int, int]:
        """Test resume claim status."""
        return (self.resume_claimed, self.resume_expected or 0)

    def close(self) -> None:
        """Test close."""
        return None

    def valid_game(self) -> bool:
        """Test valid game."""
        return True


class PreviewParent(QWidget):
    """Minimal parent object that captures preview requests."""

    def __init__(self, game: object) -> None:
        """Initialize preview capture state."""
        super().__init__()
        self.game = game
        self.preview_widget = None
        self.preview_requests = []
        self.back_calls = 0

    def load_question_media_preview(
        self, preview_questions: list[tuple[int, object]]
    ) -> None:
        """Capture and render the preview widget."""
        self.preview_requests.append(preview_questions)
        self.preview_widget = QuestionMediaPreview(
            self.game,
            preview_questions,
            on_back=self.show_welcome_from_preview,
            on_start=self.game.start_game,
        )

    def show_welcome_from_preview(self) -> None:
        """Track returns from the preview widget."""
        self.back_calls += 1


def test_load_saved_game_requires_matching_player_count(
    qtbot: object, monkeypatch: object
) -> None:
    """Test test load saved game requires matching player count."""
    game = StubGame()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "C:/saved"
    )
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.load_saved_game()
    assert widget.start_button.text() == "Resume!"
    assert widget.start_button.isEnabled() is False
    assert [checkbox.text() for checkbox in widget.round_checkboxes] == [
        "[x] Jeopardy!",
        "[ ] Double Jeopardy!",
        "[x] Final Jeopardy!",
    ]
    assert [checkbox.isChecked() for checkbox in widget.round_checkboxes] == [
        True,
        False,
        True,
    ]
    assert all(checkbox.isEnabled() for checkbox in widget.round_checkboxes)
    assert widget.reveal_answers_radio.isChecked() is True
    assert "Claimed 0 of 2 saved players" in widget.summary_label.text()
    assert (
        "Claim every saved player profile to resume (0/2)."
        in widget.summary_label.text()
    )
    game.resume_claimed = 2
    widget.check_start()
    assert widget.start_button.isEnabled() is True


def test_load_saved_game_round_checkboxes_remain_editable(
    qtbot: object, monkeypatch: object
) -> None:
    """Resumed games should restore and still allow changing saved round picks."""
    game = StubGame()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "C:/saved"
    )
    widget = Welcome(game)
    qtbot.addWidget(widget)

    widget.load_saved_game()
    widget.round_checkboxes[1].setChecked(True)

    assert game.selected_round_indices() == [0, 1, 2]
    assert widget.round_checkboxes[1].text() == "[x] Double Jeopardy!"


def test_load_saved_game_preserves_double_and_final_subset_labels(
    qtbot: object, monkeypatch: object
) -> None:
    """Subset resumes should still show the full original round list."""
    game = StubGame()

    def prepare_resume_from_dir(selected_dir: object) -> object:
        game.resume_expected = 1
        game.resume_claimed = 0
        game.set_selected_round_indices([1, 2])
        return {
            "game_id": "4453",
            "general_state": {
                "players": [{"name": "Alice"}],
                "selected_round_indices": [1, 2],
                "board_selections": [
                    {
                        "game_id": "4453",
                        "source_round_index": 1,
                        "source_round_label": "Double Jeopardy!",
                        "board_type": "standard",
                        "row_values": [400, 800, 1200, 1600, 2000],
                    },
                    {
                        "game_id": "4453",
                        "source_round_index": 2,
                        "source_round_label": "Final Jeopardy!",
                        "board_type": "final",
                        "row_values": [],
                    },
                ],
            },
        }

    game.prepare_resume_from_dir = prepare_resume_from_dir
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "C:/saved"
    )
    widget = Welcome(game)
    qtbot.addWidget(widget)

    widget.load_saved_game()

    assert [checkbox.text() for checkbox in widget.round_checkboxes] == [
        "[ ] Jeopardy!",
        "[x] Double Jeopardy!",
        "[x] Final Jeopardy!",
    ]
    assert game.selected_round_indices() == [1, 2]


def test_load_saved_game_invalid_folder_shows_warning(
    qtbot: object, monkeypatch: object
) -> None:
    """Test test load saved game invalid folder shows warning."""
    game = StubGame()
    warnings = []
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "C:/bad"
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    def raise_error(selected_dir: object) -> NoReturn:
        """Test raise error."""
        raise FileNotFoundError("Saved game folder must contain general.json")

    game.prepare_resume_from_dir = raise_error
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.load_saved_game()
    assert warnings
    assert widget.start_button.text() == "Start!"
    assert widget.start_button.isEnabled() is False


def test_welcome_round_checkboxes_default_to_all_selected(qtbot: object) -> None:
    """Test welcome round checkboxes default to all selected."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.set_summary("January 1, 2026\nFixture game")
    assert [checkbox.text() for checkbox in widget.round_checkboxes] == [
        "[x] Jeopardy!",
        "[x] Double Jeopardy!",
        "[x] Final Jeopardy!",
    ]
    assert all(checkbox.isChecked() for checkbox in widget.round_checkboxes)
    assert game.selected_round_indices() == [0, 1, 2]


def test_welcome_round_checkboxes_update_selected_rounds(qtbot: object) -> None:
    """Test welcome round checkboxes update selected rounds."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.set_summary("January 1, 2026\nFixture game")
    widget.round_checkboxes[1].setChecked(False)
    assert widget.round_checkboxes[1].text() == "[ ] Double Jeopardy!"
    assert game.selected_round_indices() == [0, 2]
    widget.round_checkboxes[1].setChecked(True)
    assert widget.round_checkboxes[1].text() == "[x] Double Jeopardy!"
    assert game.selected_round_indices() == [0, 1, 2]


def test_welcome_round_checkboxes_survive_summary_rebuild(qtbot: object) -> None:
    """Refreshing the summary should preserve an existing round selection."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.set_summary("January 1, 2026\nFixture game")
    widget.round_checkboxes[0].setChecked(False)

    widget.set_summary("January 1, 2026\nFixture game")

    assert [checkbox.isChecked() for checkbox in widget.round_checkboxes] == [
        False,
        True,
        True,
    ]
    assert game.selected_round_indices() == [1, 2]


def test_welcome_round_checkboxes_label_triple_jeopardy_games(qtbot: object) -> None:
    """Test welcome labels a third standard board as Triple Jeopardy."""
    game = StubGame()
    game.data = GameData(
        [
            game.data.rounds[0],
            game.data.rounds[1],
            Board(
                [f"Cat {index}" for index in range(6)],
                [
                    Question(
                        (col, row),
                        f"TQ {col}-{row}",
                        f"TA {col}-{row}",
                        f"Cat {col}",
                    )
                    for col in range(6)
                    for row in range(5)
                ],
                dj=False,
            ),
            game.data.rounds[2],
        ],
        game.data.date,
        game.data.comments,
    )
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.set_summary("January 1, 2026\nFixture game")
    assert [checkbox.text() for checkbox in widget.round_checkboxes] == [
        "[x] Jeopardy!",
        "[x] Double Jeopardy!",
        "[x] Triple Jeopardy!",
        "[x] Final Jeopardy!",
    ]


def test_build_summary_text_warns_about_missing_questions(qtbot: object) -> None:
    """Test welcome summary shows missing-question warnings."""
    game = StubGame()
    game.data.rounds[0].questions = game.data.rounds[0].questions[:29]
    widget = Welcome(game)
    qtbot.addWidget(widget)
    summary = widget.build_summary_text()
    assert "WARNING: Missing 1 question" in summary


def test_build_summary_text_flags_missing_daily_double(qtbot: object) -> None:
    """Test welcome summary flags missing Daily Doubles as critical."""
    game = StubGame()
    for question in game.data.rounds[0].questions:
        question.dd = False
    widget = Welcome(game)
    qtbot.addWidget(widget)
    summary = widget.build_summary_text()
    assert "CRITICAL: Missing Daily Double" in summary


def test_welcome_radio_updates_triple_stumper_reveal_option(qtbot: object) -> None:
    """Test the welcome radio toggles the reveal-answer game option."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    assert widget.reveal_answers_radio.isChecked() is False
    widget.reveal_answers_radio.setChecked(True)
    assert game.reveal_answers_after_triple_stumper_enabled() is True


def test_advanced_options_compose_frankenstein_board(
    qtbot: object, monkeypatch: object
) -> None:
    """Advanced options should compose multiple boards into one game config."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    source_a = game.data
    source_b = GameData(
        [source_a.rounds[0], source_a.rounds[2]],
        "January 2, 2026",
        "Second fixture",
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"111": source_a, "222": source_b}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": source_a, "222": source_b}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(1)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget.refresh_advanced_row(0)
    widget._advanced_rows[1]["gameid_edit"].setText("222")
    widget.refresh_advanced_row(1)
    widget._advanced_rows[0]["value_edits"][0].setText("300")
    widget.sync_advanced_configuration()

    assert len(game.board_selection_configs()) == 2
    assert game.board_selection_configs()[0]["game_id"] == "111"
    assert game.board_selection_configs()[1]["game_id"] == "222"
    assert game.board_selection_configs()[0]["board_type"] == "standard"
    assert game.board_selection_configs()[1]["board_type"] == "final"
    assert game.data.rounds[0].get_question(0, 0).value == 300
    assert "Board 1: 111 - Jeopardy!" in widget.summary_label.text()
    assert "Final 1: 222 - Final Jeopardy!" in widget.summary_label.text()


def test_advanced_options_store_daily_double_count_and_locations(
    qtbot: object, monkeypatch: object
) -> None:
    """Advanced standard rows should persist chosen Daily Double locations."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    source = game.data
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget.refresh_advanced_row(0)
    widget._advanced_rows[0]["daily_double_spinbox"].setValue(3)
    widget.sync_advanced_configuration()

    selection = game.board_selection_configs()[0]
    assert selection["daily_double_count"] == 3
    assert len(selection["daily_double_indices"]) == 3
    assert "DDs: 3" in widget.summary_label.text()


def test_advanced_row_typing_uses_debounce_without_focus_loss(
    qtbot: object, monkeypatch: object
) -> None:
    """Advanced rows should fetch after debounce while typing, not on blur."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    source = game.data
    load_calls = []
    monkeypatch.setattr("jparty.ui.widgets.welcome.ADVANCED_ROW_DEBOUNCE_MS", 10)
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: load_calls.append(game_id) or {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("111")

    assert load_calls == []
    qtbot.waitUntil(lambda: load_calls == ["111"], timeout=500)
    qtbot.waitUntil(
        lambda: len(widget._advanced_rows[0]["board_radios"]) == 2,
        timeout=500,
    )


def test_advanced_daily_double_toggle_does_not_reload_source_games(
    qtbot: object, monkeypatch: object
) -> None:
    """Daily Double count changes should compose from cached row data only."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    source = game.data
    load_calls = []
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: load_calls.append(game_id) or {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget.refresh_advanced_row(0)

    assert load_calls == ["111"]
    widget._advanced_rows[0]["daily_double_spinbox"].setValue(3)

    assert load_calls == ["111"]


def test_advanced_row_round_radios_remain_single_select(
    qtbot: object, monkeypatch: object
) -> None:
    """Choosing a different source round should uncheck the prior one."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    source = game.data
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget.refresh_advanced_row(0)

    radios = widget._advanced_rows[0]["board_radios"]
    assert len(radios) == 2
    assert radios[0].isChecked() is True
    radios[1].click()

    assert radios[0].isChecked() is False
    assert radios[1].isChecked() is True


def test_advanced_row_round_click_updates_selected_source_round(
    qtbot: object, monkeypatch: object
) -> None:
    """Clicking a different round should update the saved source round."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    source = game.data
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget.refresh_advanced_row(0)

    widget._advanced_rows[0]["board_radios"][1].click()

    assert game.board_selection_configs()[0]["source_round_index"] == 1


def test_advanced_row_switching_round_reuses_selected_round_daily_doubles(
    qtbot: object, monkeypatch: object
) -> None:
    """Changing source rounds should use that round's original Daily Doubles."""
    game = StubGame()
    game.data.rounds[0].questions = deepcopy(game.data.rounds[0].questions)
    game.data.rounds[1].questions = deepcopy(game.data.rounds[1].questions)
    game.data.rounds[0].questions[1].dd = True
    game.data.rounds[1].questions[1].dd = False
    game.data.rounds[1].questions[9].dd = True
    game.data.rounds[1].questions[22].dd = True
    widget = Welcome(game)
    qtbot.addWidget(widget)
    source = game.data
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget.refresh_advanced_row(0)
    widget._advanced_rows[0]["daily_double_spinbox"].setValue(2)
    widget._advanced_rows[0]["board_radios"][1].click()

    selection = game.board_selection_configs()[0]
    assert selection["source_round_index"] == 1
    assert selection["daily_double_indices"] == [[1, 4], [4, 2]]


def test_advanced_daily_doubles_keep_originals_when_adding_more(
    qtbot: object, monkeypatch: object
) -> None:
    """Increasing DD count should preserve original HTML DD locations."""
    game = StubGame()
    game.data.rounds[0].questions = deepcopy(game.data.rounds[0].questions)
    for question in game.data.rounds[0].questions:
        question.dd = False
    game.data.rounds[0].questions[1].dd = True
    game.data.rounds[0].questions[14].dd = True
    widget = Welcome(game)
    qtbot.addWidget(widget)
    source = game.data
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget.refresh_advanced_row(0)
    widget._advanced_rows[0]["daily_double_spinbox"].setValue(4)

    selection = game.board_selection_configs()[0]
    assert [0, 1] in selection["daily_double_indices"]
    assert [2, 4] in selection["daily_double_indices"]
    assert len(selection["daily_double_indices"]) == 4


def test_advanced_daily_doubles_below_original_only_keep_original_subset(
    qtbot: object, monkeypatch: object
) -> None:
    """Reducing DD count below original should only keep original HTML DDs."""
    game = StubGame()
    game.data.rounds[0].questions = deepcopy(game.data.rounds[0].questions)
    for question in game.data.rounds[0].questions:
        question.dd = False
    game.data.rounds[0].questions[1].dd = True
    game.data.rounds[0].questions[14].dd = True
    widget = Welcome(game)
    qtbot.addWidget(widget)
    source = game.data
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget.refresh_advanced_row(0)
    widget._advanced_rows[0]["daily_double_spinbox"].setValue(4)
    widget._advanced_rows[0]["daily_double_spinbox"].setValue(1)

    selection = game.board_selection_configs()[0]
    assert len(selection["daily_double_indices"]) == 1
    assert selection["daily_double_indices"][0] in [[0, 1], [2, 4]]


def test_advanced_options_replace_regular_workflow(
    qtbot: object, monkeypatch: object
) -> None:
    """Advanced mode should hide the regular picker and use row-local actions."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda _: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)

    assert widget.regular_workflow_widget.isHidden() is True
    assert widget.advanced_controls_widget.isHidden() is False
    assert widget.advanced_start_button.isVisible() is True
    assert "random_button" in widget._advanced_rows[0]
    assert "load_media_button" in widget._advanced_rows[0]


def test_advanced_row_layout_keeps_compact_game_id_and_wider_action_buttons(
    qtbot: object, monkeypatch: object
) -> None:
    """Advanced rows should favor usable action buttons over oversized id fields."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda _: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.resize(1600, 1000)
    widget.advanced_options_checkbox.setChecked(True)
    row = widget._advanced_rows[0]

    assert row["gameid_edit"].maximumWidth() <= 260
    assert row["random_button"].minimumWidth() >= 130
    assert row["load_media_button"].minimumWidth() >= 130


def test_advanced_row_random_populates_matching_board_type(
    qtbot: object, monkeypatch: object
) -> None:
    """Advanced row Random should load a source game that matches the slot type."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    standard_source = game.data
    final_only = GameData(
        [game.data.rounds[2]],
        "January 3, 2026",
        "Final-only fixture",
    )
    random_ids = iter(["333", "111"])
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_random_game", lambda: next(random_ids)
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"111": standard_source, "333": final_only}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": standard_source, "333": final_only}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget.random_advanced_row(0)

    assert widget._advanced_rows[0]["gameid_edit"].text() == "111"


def test_advanced_row_load_media_uses_row_game_id(
    qtbot: object, monkeypatch: object
) -> None:
    """Advanced row media import should target that row's source game id."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    imported = []
    source = game.data
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.import_question_media",
        lambda source_path, game_id: imported.append((source_path, game_id)),
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget.refresh_advanced_row(0)
    monkeypatch.setattr(widget, "select_question_media_path", lambda: "C:/media")

    widget.load_advanced_question_media(0)

    assert imported == [("C:/media", "111")]


def test_advanced_options_validate_board_type(
    qtbot: object, monkeypatch: object
) -> None:
    """Advanced rows should reject source games without the expected board type."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    final_only = GameData(
        [game.data.rounds[2]],
        "January 3, 2026",
        "Final-only fixture",
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"333": final_only}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"333": final_only}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("333")
    widget.refresh_advanced_row(0)

    assert (
        "No Jeopardy board found in this source game."
        in widget._advanced_rows[0]["status_label"].text()
    )
    assert game.board_selection_configs() == []
    assert widget.start_button.isEnabled() is False


def test_advanced_options_preserve_existing_rows_when_board_counts_change(
    qtbot: object, monkeypatch: object
) -> None:
    """Changing advanced board counts should preserve existing row data."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    source = game.data
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(1)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget.refresh_advanced_row(0)
    widget._advanced_rows[0]["value_edits"][0].setText("300")

    widget.standard_board_count_spinbox.setValue(2)

    assert widget._advanced_rows[0]["gameid_edit"].text() == "111"
    assert widget._advanced_rows[0]["value_edits"][0].text() == "300"
    assert widget._advanced_rows[1]["gameid_edit"].text() == ""


def test_advanced_options_require_all_rows_before_start_enables(
    qtbot: object, monkeypatch: object
) -> None:
    """Advanced mode should not become startable until every slot is filled."""
    game = StubGame()
    game.startable = lambda: True
    widget = Welcome(game)
    qtbot.addWidget(widget)
    source = game.data
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.get_game",
        lambda game_id: {"111": source, "222": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.services.game_loader.get_game",
        lambda game_id: {"111": source, "222": source}[game_id],
    )
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda game_id: QuestionMediaStatus(directory=None, zip_file=None),
    )

    widget.advanced_options_checkbox.setChecked(True)
    widget.standard_board_count_spinbox.setValue(2)
    widget.final_board_count_spinbox.setValue(0)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget.refresh_advanced_row(0)

    assert game.board_selection_configs() == []
    assert widget.advanced_start_button.isEnabled() is False
    assert "Fill every board slot before starting" in widget.summary_label.text()

    widget._advanced_rows[1]["gameid_edit"].setText("222")
    widget.refresh_advanced_row(1)

    assert len(game.board_selection_configs()) == 2
    assert widget.advanced_start_button.isEnabled() is True


def test_disabling_advanced_options_clears_advanced_state_and_returns_to_standard_mode(
    qtbot: object, monkeypatch: object
) -> None:
    """Turning off advanced options should reset the welcome screen."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda _: QuestionMediaStatus(directory=None, zip_file=None),
    )
    widget.textbox.setText("4453")
    widget.set_summary("January 1, 2026\nFixture game")

    widget.advanced_options_checkbox.setChecked(True)
    widget._advanced_rows[0]["gameid_edit"].setText("111")
    widget._advanced_rows[1]["gameid_edit"].setText("222")
    widget.advanced_options_checkbox.setChecked(False)

    assert widget.advanced_controls_widget.isVisible() is False
    assert widget.standard_board_count_spinbox.value() == 2
    assert widget.final_board_count_spinbox.value() == 1
    assert widget.textbox.text() == ""
    assert widget.summary_label.text() == ""
    assert widget.rounds_widget.isHidden() is True
    assert widget.round_checkboxes == []
    assert game.board_selection_configs() == []
    assert widget.start_button.isEnabled() is False

    widget.advanced_options_checkbox.setChecked(True)
    assert widget._advanced_rows[0]["gameid_edit"].text() == ""
    assert widget._advanced_rows[1]["gameid_edit"].text() == ""


def test_resume_round_selector_does_not_clear_saved_board_selections(
    qtbot: object,
) -> None:
    """Resume-mode round UI should not overwrite a saved Frankenstein config."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.resume_path = "C:/saved"
    game.set_board_selection_configs(
        [
            {
                "game_id": "111",
                "source_round_index": 0,
                "source_round_label": "Jeopardy!",
                "board_type": "standard",
                "row_values": [200, 400, 600, 800, 1000],
            },
            {
                "game_id": "222",
                "source_round_index": 1,
                "source_round_label": "Double Jeopardy!",
                "board_type": "standard",
                "row_values": [400, 800, 1200, 1600, 2000],
            },
        ]
    )
    widget.configure_round_selector(enabled=False)

    assert [selection["game_id"] for selection in game.board_selection_configs()] == [
        "111",
        "222",
    ]


def test_build_summary_text_includes_question_media_status(
    qtbot: object, monkeypatch: object
) -> None:
    """Welcome summary should include the detected media status line."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.textbox.setText("4453")
    monkeypatch.setattr(
        "jparty.ui.widgets.welcome.detect_question_media",
        lambda _: QuestionMediaStatus(directory=None, zip_file=None),
    )
    widget._question_media_status = QuestionMediaStatus(directory=None, zip_file=None)
    summary = widget.build_summary_text()
    assert "Question media status: no folder or zip archive found." in summary


def test_load_question_media_requires_game_id(
    qtbot: object, monkeypatch: object
) -> None:
    """Import should warn when no destination game id has been typed."""
    game = StubGame()
    widget = Welcome(game)
    qtbot.addWidget(widget)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    widget.load_question_media()
    assert warnings


def test_load_question_media_imports_directory_and_refreshes_status(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """Successful import should refresh the welcome summary."""
    game = StubGame()
    source_dir = temp_dir / "source"
    source_dir.mkdir()
    media_file = source_dir / "0-0-0.png"
    media_file.write_bytes(b"png")
    monkeypatch.setattr(
        "jparty.services.question_media.QUESTION_MEDIA", temp_dir / "question_media"
    )
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.textbox.setText("4453")
    monkeypatch.setattr(widget, "select_question_media_path", lambda: str(source_dir))
    widget.load_question_media()
    assert (temp_dir / "question_media" / "4453" / "0-0-0.png").exists()
    assert "Question media status: found folder." in widget.summary_label.text()


def test_load_question_media_imports_zip_and_refreshes_status(
    qtbot: object, temp_dir: object, monkeypatch: object
) -> None:
    """Zip imports should extract into the game directory and refresh the summary."""
    from zipfile import ZipFile

    game = StubGame()
    source_zip = temp_dir / "media.zip"
    with ZipFile(source_zip, "w") as archive:
        archive.writestr("1-2-3.jpg", b"jpg")
    monkeypatch.setattr(
        "jparty.services.question_media.QUESTION_MEDIA", temp_dir / "question_media"
    )
    widget = Welcome(game)
    qtbot.addWidget(widget)
    widget.textbox.setText("4453")
    monkeypatch.setattr(widget, "select_question_media_path", lambda: str(source_zip))
    widget.load_question_media()
    assert (temp_dir / "question_media" / "4453" / "1-2-3.jpg").exists()
    assert "Question media status: found folder." in widget.summary_label.text()


def test_start_click_opens_preview_for_selected_round_local_media(
    qtbot: object, temp_dir: object
) -> None:
    """Welcome should show preview instead of starting immediately when local media exists."""
    game = StubGame()
    image_path = temp_dir / "0-0-0.png"
    pixmap = QPixmap(40, 40)
    pixmap.fill(QColor("blue"))
    assert pixmap.save(str(image_path))
    game.data.rounds[0].questions[0].image = True
    game.data.rounds[0].questions[0].image_url = str(image_path)
    game.data.rounds[1].questions[0].image = True
    game.data.rounds[1].questions[0].image_url = str(image_path)
    game.set_selected_round_indices([0])
    parent = PreviewParent(game)
    qtbot.addWidget(parent)
    widget = Welcome(game, parent)
    qtbot.addWidget(widget)
    widget._question_media_status = QuestionMediaStatus(
        directory=temp_dir, zip_file=None
    )
    widget.on_start_clicked()
    assert game.start_game_calls == 0
    assert len(parent.preview_requests) == 1
    assert len(parent.preview_requests[0]) == 1
    assert parent.preview_widget is not None
    qtbot.addWidget(parent.preview_widget)
    assert parent.preview_widget.cards
    answer_labels = parent.preview_widget.cards[0].findChildren(QLabel)
    assert any(
        label.text() == game.data.rounds[0].questions[0].answer
        for label in answer_labels
    )


def test_preview_buttons_go_back_or_start_game(qtbot: object, temp_dir: object) -> None:
    """Preview buttons should return to welcome or continue into game start."""
    game = StubGame()
    image_path = temp_dir / "0-0-0.png"
    pixmap = QPixmap(40, 40)
    pixmap.fill(QColor("green"))
    assert pixmap.save(str(image_path))
    question = game.data.rounds[0].questions[0]
    question.image = True
    question.image_url = str(image_path)
    parent = PreviewParent(game)
    qtbot.addWidget(parent)
    preview = QuestionMediaPreview(
        game,
        [(0, question)],
        on_back=parent.show_welcome_from_preview,
        on_start=game.start_game,
    )
    qtbot.addWidget(preview)
    preview.show()
    qtbot.mouseClick(preview.back_button, Qt.MouseButton.LeftButton)
    assert parent.back_calls == 1
    qtbot.mouseClick(preview.start_button, Qt.MouseButton.LeftButton)
    assert game.start_game_calls == 1
