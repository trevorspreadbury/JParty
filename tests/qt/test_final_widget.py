"""Tests for Final Jeopardy and end-game summary widgets."""

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QPalette

from jparty.app.bootstrap import SUMMARY_IMAGE_SIZE
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
