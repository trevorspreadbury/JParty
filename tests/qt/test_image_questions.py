"""Test image questions module."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from jparty.domain.models import Question
from jparty.services import image_lookup
from jparty.ui.widgets.question import HostImageQuestionWidget, QuestionWidget
from PyQt6 import sip
from PyQt6.QtGui import QColor, QPixmap

pytestmark = pytest.mark.qt


def test_image_question_widget_shows_text_and_image(
    qtbot: object, temp_dir: object
) -> None:
    """Test test image question widget shows text and image."""
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


def test_accept_image_persists_local_file_for_contestant_display(
    qtbot: object, temp_dir: object, monkeypatch: object, offline_image_lookup: None
) -> None:
    """Test test accept image persists local file for contestant display."""
    monkeypatch.setattr("jparty.ui.widgets.question.QUESTION_MEDIA", temp_dir)
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


def _lookup_question() -> Question:
    """Return an image clue that must be looked up because it has no media."""
    return Question(
        index=(0, 1),
        text="This arch is pictured",
        answer="Gateway Arch",
        category="Landmarks",
        value=200,
        image=True,
    )


def _review_widget(question: Question) -> HostImageQuestionWidget:
    """Build a host image-review widget for ``question``."""
    game = SimpleNamespace(
        active_question=question,
        accept_image=lambda: None,
        current_game_id=lambda: "4453",
    )
    return HostImageQuestionWidget(game)


def test_image_lookup_runs_asynchronously_and_loads_thumbnail(
    qtbot: object, local_image_lookup: Path
) -> None:
    """Test the review widget returns immediately and loads the image later."""
    widget = _review_widget(_lookup_question())
    qtbot.addWidget(widget)
    assert widget.current_pixmap is None
    assert widget.image_label.text() == "Searching for image..."
    qtbot.waitUntil(lambda: widget.current_pixmap is not None, timeout=5000)
    assert widget.current_pixmap.width() == 30
    assert Path(widget.image_url.removeprefix("file:///")).name == (
        local_image_lookup.name
    )


def test_offline_image_lookup_shows_failure_without_image_url(
    qtbot: object, offline_image_lookup: None
) -> None:
    """Test an offline lookup leaves the clue playable (issue #49)."""
    widget = _review_widget(_lookup_question())
    qtbot.addWidget(widget)
    qtbot.waitUntil(
        lambda: widget.image_label.text() == "Failed to load image.", timeout=10000
    )
    assert widget.image_url is None
    assert widget.current_pixmap is None


def test_stale_image_lookup_reply_is_ignored(
    qtbot: object,
    local_image_lookup: Path,
    monkeypatch: object,
    unreachable_api_url: str,
) -> None:
    """Test an earlier search that would succeed cannot overwrite a newer one."""
    widget = _review_widget(_lookup_question())
    qtbot.addWidget(widget)
    monkeypatch.setattr(image_lookup, "WIKIMEDIA_API_URL", unreachable_api_url)
    widget.search_image("Something else")
    qtbot.waitUntil(
        lambda: widget.image_label.text() == "Failed to load image.", timeout=10000
    )
    qtbot.wait(200)
    assert widget.image_url is None
    assert widget.current_pixmap is None


def test_deleting_widget_with_pending_lookup_is_safe(
    qtbot: object, offline_image_lookup: None
) -> None:
    """Test a lookup finishing after the review widget is gone does not raise."""
    widget = _review_widget(_lookup_question())
    sip.delete(widget)
    qtbot.wait(2500)
