from types import SimpleNamespace
from pathlib import Path

from PyQt6.QtGui import QColor, QPixmap

import pytest

from jparty.domain.models import Question
from jparty.ui.widgets.question import HostImageQuestionWidget, QuestionWidget


pytestmark = pytest.mark.qt


def test_image_question_widget_shows_text_and_image(qtbot, temp_dir):
    image_path = temp_dir / "clue.png"
    pixmap = QPixmap(40, 40)
    pixmap.fill(QColor("red"))
    assert pixmap.save(str(image_path))

    question = Question(
        index=(0, 0),
        text="Name this landmark",
        answer="What is the Gateway Arch?",
        category="Landmarks",
        value=200,
        image=True,
        image_url=str(image_path),
    )

    widget = QuestionWidget(question)
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    qtbot.waitExposed(widget)

    assert widget.question_label.text() == "NAME THIS LANDMARK"
    assert widget.image_label is not None
    assert widget.image_label.pixmap() is not None
    assert not widget.image_label.pixmap().isNull()


def test_accept_image_persists_local_file_for_contestant_display(qtbot, temp_dir, monkeypatch):
    monkeypatch.setattr("jparty.ui.widgets.question.QUESTION_MEDIA", temp_dir)
    monkeypatch.setattr(
        "jparty.ui.widgets.question.search_wikimedia_image",
        lambda _: "https://example.com/original.png",
    )

    question = Question(
        index=(2, 3),
        text="Identify this person",
        answer="Who is Ada Lovelace?",
        category="History",
        value=400,
    )

    game = SimpleNamespace(
        active_question=question,
        accept_image=lambda: None,
        current_game_id=lambda: "4453",
    )

    widget = HostImageQuestionWidget(game)
    qtbot.addWidget(widget)
    widget.image_url = "https://example.com/ada.png"
    widget.current_pixmap = QPixmap(50, 50)
    widget.current_pixmap.fill(QColor("green"))

    widget.on_accept_image_clicked()

    accepted_path = question.image_url
    assert accepted_path is not None
    assert accepted_path.endswith(".png")
    assert temp_dir in Path(accepted_path).parents
    assert Path(accepted_path).exists()

    contestant_widget = QuestionWidget(question)
    qtbot.addWidget(contestant_widget)
    contestant_widget.resize(800, 600)
    contestant_widget.show()
    qtbot.waitExposed(contestant_widget)

    assert contestant_widget.image_label is not None
    assert contestant_widget.image_label.pixmap() is not None
    assert not contestant_widget.image_label.pixmap().isNull()
