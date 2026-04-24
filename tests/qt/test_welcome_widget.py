"""Test welcome widget module."""

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
        self.data = GameData(
            [self.data.rounds[0], self.data.rounds[2]],
            self.data.date,
            self.data.comments,
        )
        return {
            "game_id": "4453",
            "general_state": {
                "players": [{"name": "Alice"}, {"name": "Bob"}],
                "selected_round_indices": [0, 2],
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
        "[x] Final Jeopardy!",
    ]
    assert all(checkbox.isChecked() for checkbox in widget.round_checkboxes)
    assert all(not checkbox.isEnabled() for checkbox in widget.round_checkboxes)
    assert "Claimed 0 of 2 saved players" in widget.summary_label.text()
    assert (
        "Claim every saved player profile to resume (0/2)."
        in widget.summary_label.text()
    )
    game.resume_claimed = 2
    widget.check_start()
    assert widget.start_button.isEnabled() is True


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
