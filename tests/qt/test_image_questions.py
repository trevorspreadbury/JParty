"""Test image questions module."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtNetwork import QNetworkReply, QSslSocket

from jparty.domain.models import Question
from jparty.services import image_lookup
from jparty.ui.widgets import question as question_module
from jparty.ui.widgets.question import HostImageQuestionWidget, QuestionWidget

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


class _FakeReply(QObject):
    """Stand-in for ``QNetworkReply`` whose completion the test controls."""

    finished = pyqtSignal()

    def __init__(self, url: str) -> None:
        """Create a pending reply for ``url``."""
        super().__init__()
        self.url = url
        self.aborted = False
        self._error = QNetworkReply.NetworkError.NoError
        self._data = QByteArray()

    def respond(self, data: QByteArray) -> None:
        """Finish successfully with ``data`` as the body."""
        self._data = data
        self.finished.emit()

    def fail(self) -> None:
        """Finish with a connection error."""
        self._error = QNetworkReply.NetworkError.ConnectionRefusedError
        self.finished.emit()

    def abort(self) -> None:
        """Record that the widget cancelled this reply."""
        self.aborted = True

    def error(self) -> QNetworkReply.NetworkError:
        """Return the reply's network error."""
        return self._error

    def readAll(self) -> QByteArray:
        """Return the reply body."""
        return self._data


def _png_bytes(color: str) -> QByteArray:
    """Return a 10x10 PNG filled with ``color``."""
    pixmap = QPixmap(10, 10)
    pixmap.fill(QColor(color))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert pixmap.save(buffer, "PNG")
    buffer.close()
    return data


def _review_widget_with_fake_network(
    qtbot: object, monkeypatch: object, temp_dir: Path, accepted: list
) -> tuple:
    """Build a review widget whose image downloads return ``_FakeReply`` objects.

    Returns:
        The widget and the list of fake replies, in request order.
    """
    monkeypatch.setattr("jparty.ui.widgets.question.QUESTION_MEDIA", temp_dir)
    game = SimpleNamespace(
        active_question=_lookup_question(),
        accept_image=lambda: accepted.append(True),
        current_game_id=lambda: "4453",
    )
    widget = HostImageQuestionWidget(game)
    qtbot.addWidget(widget)
    replies = []

    def fake_get(request: object) -> _FakeReply:
        reply = _FakeReply(request.url().toString())
        replies.append(reply)
        return reply

    monkeypatch.setattr(widget.network_manager, "get", fake_get)
    return widget, replies


def test_failed_fetch_after_good_one_disables_accept(
    qtbot: object, temp_dir: Path, monkeypatch: object, offline_image_lookup: None
) -> None:
    """Test a failed load clears the old image so Accept saves nothing (#68)."""
    accepted = []
    widget, replies = _review_widget_with_fake_network(
        qtbot, monkeypatch, temp_dir, accepted
    )
    widget.fetch_image("https://example.com/good.png")
    replies[-1].respond(_png_bytes("green"))
    assert widget.current_pixmap is not None
    assert widget.start_button.isEnabled()

    widget.fetch_image("https://example.com/broken.png")
    assert widget.current_pixmap is None
    assert not widget.start_button.isEnabled()
    replies[-1].fail()

    assert widget.image_label.text() == "Failed to load image."
    assert widget.current_pixmap is None
    assert not widget.start_button.isEnabled()
    qtbot.mouseClick(widget.start_button, Qt.MouseButton.LeftButton)
    widget.on_accept_image_clicked()
    assert accepted == []
    assert widget.question.image_url is None
    assert not (temp_dir / "reviewed").exists()


def test_first_reply_arriving_last_does_not_replace_newer_image(
    qtbot: object, temp_dir: Path, monkeypatch: object, offline_image_lookup: None
) -> None:
    """Test the shown and accepted image is from the latest request (#68)."""
    accepted = []
    widget, replies = _review_widget_with_fake_network(
        qtbot, monkeypatch, temp_dir, accepted
    )
    widget.fetch_image("https://example.com/first.png")
    widget.fetch_image("https://example.com/second.png")
    first, second = replies
    assert first.aborted
    assert not second.aborted

    second.respond(_png_bytes("blue"))
    first.respond(_png_bytes("red"))

    assert widget.current_pixmap.toImage().pixelColor(0, 0) == QColor("blue")
    assert widget.start_button.isEnabled()
    qtbot.mouseClick(widget.start_button, Qt.MouseButton.LeftButton)
    assert accepted == [True]
    saved = QPixmap(widget.question.image_url)
    assert temp_dir in Path(widget.question.image_url).parents
    assert saved.toImage().pixelColor(0, 0) == QColor("blue")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows TLS backend only")
def test_image_lookup_uses_windows_tls_backend(
    qtbot: object, offline_image_lookup: None
) -> None:
    """Test image lookups use Windows' TLS, not a possibly foreign OpenSSL (#105).

    On conda-based Python, Qt's OpenSSL backend loads conda's ``libssl`` and
    the app crashes after a failed lookup is dismissed.
    """
    widget = _review_widget(_lookup_question())
    qtbot.addWidget(widget)
    assert QSslSocket.activeBackend() == "schannel"


def test_tls_backend_is_left_alone_off_windows(monkeypatch: object) -> None:
    """Test other platforms keep Qt's default TLS backend."""
    chosen = []
    monkeypatch.setattr(question_module.sys, "platform", "linux")
    monkeypatch.setattr(
        question_module.QSslSocket, "setActiveBackend", lambda name: chosen.append(name)
    )
    question_module.use_windows_tls_backend()
    assert chosen == []
