"""Test that text typed on a phone is shown as plain text on the host.

Qt labels guess whether text is HTML. A player name or Final answer with
markup such as ``<img src=...>`` would make Qt fetch the image and could hang
the host or leak its Windows login hash. These labels must show the text as
typed.
"""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from jparty.domain.models import Player
from jparty.ui.widgets.final import FinalAnswerWidget
from jparty.ui.widgets.score_correction import ScoreCorrectionDialog
from jparty.ui.widgets.scoreboard import NameLabel

pytestmark = pytest.mark.qt

MARKUP_TEXTS = [
    "<img src='missing-jparty-test-image.png'>",
    "<b>Bold</b> Bob",
]


@pytest.mark.parametrize("name", MARKUP_TEXTS)
def test_name_label_shows_markup_names_as_typed(qtbot: object, name: str) -> None:
    """A name with HTML tags is drawn as the literal text."""
    label = NameLabel(name, None)
    qtbot.addWidget(label)

    assert label.textFormat() == Qt.TextFormat.PlainText
    assert label.text() == name


@pytest.mark.parametrize("answer", MARKUP_TEXTS)
def test_final_guess_label_shows_markup_answers_as_typed(
    qtbot: object, answer: str
) -> None:
    """A Final answer with HTML tags is drawn as the literal text."""
    widget = FinalAnswerWidget(SimpleNamespace(), None)
    qtbot.addWidget(widget)

    widget.guess_label.setText(answer)

    assert widget.guess_label.textFormat() == Qt.TextFormat.PlainText
    assert widget.guess_label.text() == answer


@pytest.mark.parametrize("name", MARKUP_TEXTS)
def test_score_editor_shows_markup_names_as_typed(qtbot: object, name: str) -> None:
    """The score editor's player label shows a markup name as typed."""
    player = Player(name, SimpleNamespace(send=lambda *args, **kwargs: None), 0)
    entry = {
        "question_number": 1,
        "category": "Category",
        "value": 200,
        "answer": "Answer",
        "is_daily_double": False,
        "player_states": {0: "no answer"},
    }
    dialog = ScoreCorrectionDialog([entry], [player])
    qtbot.addWidget(dialog)

    labels = [label for label in dialog.findChildren(QLabel) if name in label.text()]

    assert labels
    for label in labels:
        assert label.textFormat() == Qt.TextFormat.PlainText


def test_autosize_measures_plain_text_labels_as_typed(qtbot: object) -> None:
    """Auto-sizing measures the tags too, since they are drawn on screen."""
    label = NameLabel("<b>Bob</b>", None)
    qtbot.addWidget(label)

    assert label.plaintext() == "<b>Bob</b>"


def test_clue_labels_still_render_line_breaks(qtbot: object) -> None:
    """Clue labels keep rich text so ``<br/>`` still breaks the line."""
    from jparty.ui.styles import MyLabel

    label = MyLabel("DAILY<br/>DOUBLE!", 10, None)
    qtbot.addWidget(label)

    assert label.textFormat() == Qt.TextFormat.AutoText
