"""Tests for Final Jeopardy and end-game summary widgets."""

import pytest
from jparty.domain.state import EndGamePlayerStats
from jparty.ui.widgets.final import PlayerSummaryCard
from jparty.ui.widgets.scoreboard import NameLabel
from PyQt6.QtGui import QColor, QPalette

pytestmark = pytest.mark.qt


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
