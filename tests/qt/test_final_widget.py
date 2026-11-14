"""Tests for Final Jeopardy and end-game summary widgets."""

import pytest
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QImage, QPalette
from PyQt6.QtWidgets import QLabel

from jparty.app.bootstrap import (
    SUMMARY_IMAGE_SIZE,
    build_summary_image_widget,
    render_summary_image,
)
from jparty.domain.state import (
    EndGameGameStats,
    EndGamePlayerStats,
    EndGameSeries,
    EndGameSummary,
)
from jparty.ui.widgets.final import (
    EndGameSummaryDisplay,
    PlayerSummaryCard,
    SummaryGraphWidget,
    format_money,
)
from jparty.ui.widgets.scoreboard import NameLabel

pytestmark = pytest.mark.qt


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


# The in-game audience area the summary is shown in on a 1080p screen.
IN_GAME_SUMMARY_SIZE = (1746, 840)


@pytest.mark.parametrize("player_count", [3, 6])
@pytest.mark.parametrize("size", [SUMMARY_IMAGE_SIZE, IN_GAME_SUMMARY_SIZE])
def test_end_game_summary_shows_every_game_stat_value(
    qtbot: object, player_count: int, size: tuple[int, int]
) -> None:
    """Each Game Stats line must fit on one line, so its value stays visible.

    In the ``jparty summary`` image the labels wrapped and their numbers were
    cut off.
    """
    display = EndGameSummaryDisplay(_summary(player_count))
    qtbot.addWidget(display)
    display.resize(*size)
    qtbot.waitExposed(display)

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
        top_left = label.mapTo(display, label.rect().topLeft())
        assert display.rect().contains(QRect(top_left, label.size()))


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


def test_summary_image_widget_keeps_the_full_image_size(qtbot: object) -> None:
    """The CLI widget must not be squeezed to fit a smaller screen."""
    widget = build_summary_image_widget(_summary(6))
    qtbot.addWidget(widget)

    assert (widget.width(), widget.height()) == SUMMARY_IMAGE_SIZE
    assert widget.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)


def test_render_summary_image_writes_an_image_of_the_documented_size(
    qtbot: object, temp_dir: object
) -> None:
    """The saved image is 1920x1080 whatever the screen's scaling."""
    output = render_summary_image(_summary(6), temp_dir / "summary.png")

    image = QImage(str(output))
    assert (image.width(), image.height()) == SUMMARY_IMAGE_SIZE


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
