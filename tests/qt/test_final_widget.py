"""Tests for Final Jeopardy and end-game summary widgets."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFontDatabase, QFontMetrics, QImage, QPalette
from PyQt6.QtWidgets import QApplication, QLabel

from jparty.app.bootstrap import (
    SUMMARY_IMAGE_SIZE,
    build_summary_image_widget,
    configure_application_font,
    render_summary_image,
)
from jparty.domain.state import (
    EndGameGameStats,
    EndGamePlayerStats,
    EndGameSeries,
    EndGameSummary,
)
from jparty.ui.widgets.common import resource_path
from jparty.ui.widgets.final import (
    EndGameSummaryDisplay,
    PlayerSummaryCard,
    SummaryGraphWidget,
    format_money,
)
from jparty.ui.widgets.scoreboard import NameLabel

pytestmark = pytest.mark.qt

# Where the OS keeps Verdana, the font the app asks for first. On Windows the
# offscreen test platform has no system fonts, so it is loaded by path.
SYSTEM_UI_FONT_FILES = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "verdana.ttf",
    Path("/System/Library/Fonts/Supplemental/Verdana.ttf"),
    Path("/Library/Fonts/Verdana.ttf"),
    Path("/usr/share/fonts/truetype/msttcorefonts/Verdana.ttf"),
]
# The in-game audience area the summary is shown in on a 1080p screen.
IN_GAME_SUMMARY_SIZE = (1746, 840)


@pytest.fixture
def summary_fonts(qapp: object) -> None:
    """Draw the summary in the fonts the real app uses.

    Without them the offscreen platform on Windows has no fonts and draws
    every glyph as a wide box, so the summary can't shrink to its real size.
    The bundled Korinna font is always loaded; Verdana, the app's UI font, is
    loaded from the OS when it is there. Without Verdana, text falls back to
    Korinna, which is a little narrower.
    """
    font_ids = [
        QFontDatabase.addApplicationFont(resource_path("ITC_ Korinna Normal.ttf"))
    ]
    if "Verdana" not in QFontDatabase.families():
        for font_file in SYSTEM_UI_FONT_FILES:
            if font_file.is_file():
                font_ids.append(QFontDatabase.addApplicationFont(str(font_file)))
                break
    previous_font = QApplication.font()
    configure_application_font(qapp)
    yield
    QApplication.setFont(previous_font)
    for font_id in font_ids:
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)


def _rect_in(widget: object, ancestor: object) -> QRect:
    """Return ``widget``'s rectangle in ``ancestor``'s coordinates."""
    return QRect(widget.mapTo(ancestor, QPoint(0, 0)), widget.size())


def _assert_stat_labels_fit(display: object, size: tuple[int, int]) -> None:
    """Assert each Game Stats line shows in full inside a ``size`` area.

    The area is the intended size, not the widget's own geometry, so a
    widget that grew past it can't pass.
    """
    intended_rect = QRect(QPoint(0, 0), QSize(*size))
    labels = display.game_summary_card.stat_labels
    assert [label.text().split(":")[0] for label in labels] == [
        "Lead Changes",
        "Combined Coryat",
        "Buzzer Races",
        "Triple Stumpers",
    ]
    for label in labels:
        assert label.isVisible()
        assert not label.wordWrap()
        text_width = label.fontMetrics().horizontalAdvance(label.text())
        assert text_width <= label.contentsRect().width(), label.text()
        assert label.sizeHint().height() <= label.height(), label.text()
        assert intended_rect.contains(_rect_in(label, display)), label.text()


def _player_stats(player_number: int) -> EndGamePlayerStats:
    """Return summary stats for one test player."""
    return EndGamePlayerStats(
        player_number=player_number,
        name=f"Player {player_number}",
        final_score=12000 * player_number,
        coryat=1000,
        right_count=5,
        wrong_count=1,
        questions_buzzed_on=7,
        early_buzzes=0,
        race_wins=2,
        race_opportunities=3,
    )


def _summary(player_count: int) -> EndGameSummary:
    """Return an end-of-game summary with ``player_count`` current players."""
    return EndGameSummary(
        winner_player_numbers=[player_count - 1],
        is_tie=False,
        question_count=3,
        current_players=[_player_stats(number) for number in range(player_count)],
        game_stats=EndGameGameStats(
            lead_changes=1,
            combined_coryat=3000,
            buzzer_races=4,
            triple_stumpers=0,
            victory_summary="A comfortable win",
        ),
        current_series=[
            EndGameSeries(number, f"Player {number}", [0, 200, 400], True, False)
            for number in range(player_count)
        ],
        original_series=[],
    )


def test_player_summary_card_renders_typed_name_in_dark_text(qtbot: object) -> None:
    """Typed names should remain visible on white summary cards."""
    player_stats = EndGamePlayerStats(
        player_number=0,
        name="Alice",
        final_score=1200,
        coryat=1000,
        right_count=5,
        wrong_count=1,
        questions_buzzed_on=7,
        early_buzzes=0,
        race_wins=2,
        race_opportunities=3,
    )

    card = PlayerSummaryCard(player_stats, QColor("#ffd447"))
    qtbot.addWidget(card)

    name_label = card.findChild(NameLabel)
    assert name_label is not None
    assert name_label.text() == "Alice"
    assert name_label.palette().color(QPalette.ColorRole.WindowText) == QColor("black")


def test_summary_graph_series_share_the_longest_x_axis(qtbot: object) -> None:
    """A shorter series must stop at its own clue number, not the right edge."""
    current = EndGameSeries(0, "Alice", [0, 200, 400, 600], True, False)
    original = EndGameSeries(
        None, "Original", [0, 400, 800, 1200, 1600, 2000], False, True
    )
    graph = SummaryGraphWidget([current], [original], {0: QColor("yellow")})
    qtbot.addWidget(graph)
    rect = QRect(0, 0, 500, 300)

    current_points = graph.series_points(rect, current)
    original_points = graph.series_points(rect, original)

    assert [point.x() for point in current_points] == [
        point.x() for point in original_points[:4]
    ]
    assert current_points[-1].x() == pytest.approx(rect.width() * 3 / 5)
    assert original_points[-1].x() == pytest.approx(rect.width())


@pytest.mark.parametrize("player_count", [1, 3, 4, 6])
def test_end_game_summary_fits_a_1080p_screen(qtbot: object, player_count: int) -> None:
    """The summary must fit 1920x1080 for every supported player count."""
    display = EndGameSummaryDisplay(_summary(player_count))
    qtbot.addWidget(display)
    width, height = SUMMARY_IMAGE_SIZE

    assert display.minimumSizeHint().height() <= height
    display.resize(width, height)
    qtbot.waitExposed(display)
    assert display.height() == height
    for card in display.findChildren(PlayerSummaryCard):
        assert display.rect().contains(card.geometry())


def _summary_with_wide_stats(player_count: int) -> EndGameSummary:
    """Return a summary whose Game Stats values are as wide as a real game's."""
    summary = _summary(player_count)
    summary.game_stats.lead_changes = 12
    summary.game_stats.combined_coryat = 54200
    summary.game_stats.buzzer_races = 38
    summary.game_stats.triple_stumpers = 9
    return summary


@pytest.mark.parametrize("player_count", [3, 6])
@pytest.mark.parametrize("size", [SUMMARY_IMAGE_SIZE, IN_GAME_SUMMARY_SIZE])
def test_end_game_summary_shows_every_game_stat_value(
    qtbot: object, summary_fonts: None, player_count: int, size: tuple[int, int]
) -> None:
    """Each Game Stats line must fit on one line, so its value stays visible.

    In the ``jparty summary`` image the labels wrapped and their numbers were
    cut off. The summary must also keep the size it was given: if the stats
    need more width, the whole summary grows past the screen instead.
    """
    display = EndGameSummaryDisplay(_summary_with_wide_stats(player_count))
    qtbot.addWidget(display)
    display.resize(*size)
    qtbot.waitExposed(display)

    assert (display.width(), display.height()) == size
    _assert_stat_labels_fit(display, size)


def test_end_game_summary_title_is_visible(qtbot: object) -> None:
    """The "Game Summary" title must take up space, not collapse to nothing."""
    display = EndGameSummaryDisplay(_summary(3))
    qtbot.addWidget(display)
    display.resize(*SUMMARY_IMAGE_SIZE)
    qtbot.waitExposed(display)

    title = display.title_label
    assert title.text() == "Game Summary"
    assert title.isVisible()
    assert title.height() >= title.fontMetrics().height()


@pytest.mark.parametrize("player_count", [3, 6])
def test_summary_image_widget_keeps_the_full_image_size(
    qtbot: object, summary_fonts: None, player_count: int
) -> None:
    """The CLI widget must be exactly 1920x1080 with every stat inside it."""
    widget = build_summary_image_widget(_summary_with_wide_stats(player_count))
    qtbot.addWidget(widget)

    assert (widget.width(), widget.height()) == SUMMARY_IMAGE_SIZE
    assert widget.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    _assert_stat_labels_fit(widget, SUMMARY_IMAGE_SIZE)


def test_render_summary_image_writes_an_image_of_the_documented_size(
    qtbot: object, summary_fonts: None, temp_dir: object
) -> None:
    """The saved image is 1920x1080 and every stat label lies inside it."""
    summary = _summary_with_wide_stats(6)
    output = render_summary_image(summary, temp_dir / "summary.png")

    image = QImage(str(output))
    assert (image.width(), image.height()) == SUMMARY_IMAGE_SIZE
    # The widget behind the image is built the same way; its labels must lie
    # inside the image, not just inside the widget.
    widget = build_summary_image_widget(summary)
    qtbot.addWidget(widget)
    for label in widget.game_summary_card.stat_labels:
        assert image.rect().contains(_rect_in(label, widget)), label.text()


# Run in a fresh process, since Qt reads the scale factor when it starts.
_RENDER_SCALED_SCRIPT = """
import json, sys
from tests.qt.test_final_widget import _summary
from jparty.app.bootstrap import render_summary_image
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

app = QApplication([])
ratio = app.primaryScreen().devicePixelRatio()
output = render_summary_image(_summary(3), sys.argv[1])
image = QImage(str(output))
print(json.dumps([image.width(), image.height(), ratio]))
"""


def test_render_summary_image_ignores_display_scaling(temp_dir: object) -> None:
    """With 150% display scaling the image must still be 1920x1080.

    ``QWidget.grab()`` multiplies by the screen's scale, which gave a
    2880x1620 image on a 150% Windows display.
    """
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR="1.5")
    result = subprocess.run(
        [sys.executable, "-c", _RENDER_SCALED_SCRIPT, str(temp_dir / "scaled.png")],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parents[2],
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    width, height, ratio = json.loads(result.stdout.strip().splitlines()[-1])
    assert ratio == pytest.approx(1.5)
    assert (width, height) == SUMMARY_IMAGE_SIZE


def test_summary_graph_axis_text_never_overlaps(
    qtbot: object, summary_fonts: None
) -> None:
    """The "Score" title, tick labels and plot must not overlap.

    With a fixed left margin, wide scores such as ``$1,350,000`` ran into the
    plot and the rotated title.
    """
    series = EndGameSeries(0, "Alice", [0, -48000, 1250000], True, False)
    graph = SummaryGraphWidget([series], [], {0: QColor("yellow")})
    qtbot.addWidget(graph)
    graph.resize(900, 500)
    metrics = QFontMetrics(graph.font())

    axis = graph.axis_layout(metrics)

    assert axis.tick_labels[0].startswith("$1,")
    assert axis.tick_labels[-1].startswith("-$")
    widget_rect = QRectF(graph.rect())
    assert widget_rect.contains(axis.title_rect)
    for label, label_rect in zip(axis.tick_labels, axis.tick_label_rects, strict=True):
        assert label_rect.width() == metrics.horizontalAdvance(label)
        assert widget_rect.contains(label_rect), label
        assert label_rect.left() >= axis.title_rect.right(), label
        assert label_rect.right() <= axis.plot_rect.left(), label


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(0, "$0"), (1200, "$1,200"), (-200, "-$200"), (-123450, "-$123,450")],
)
def test_format_money_puts_the_minus_sign_first(amount: int, expected: str) -> None:
    """Negative amounts read ``-$200``, not ``$-200``."""
    assert format_money(amount) == expected


def test_player_summary_card_shows_negative_scores_with_leading_minus(
    qtbot: object,
) -> None:
    """A negative final score and Coryat show as ``-$...`` on the card."""
    stats = _player_stats(0)
    stats.final_score = -200
    stats.coryat = -800
    card = PlayerSummaryCard(stats, QColor("#ffd447"))
    qtbot.addWidget(card)

    texts = [label.text() for label in card.findChildren(QLabel)]
    assert "Final Score: -$200" in texts
    assert "Coryat: -$800" in texts
