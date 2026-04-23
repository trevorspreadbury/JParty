"""Widgets used during Final Jeopardy and end-of-game summary presentation.

This module provides the final-round answer display widgets and the audience
summary screen shown after the winner has been revealed.
"""

from __future__ import annotations

from math import ceil

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.state import EndGameSeries, EndGameSummary
from jparty.ui.styles import CARDPAL, JBLUE, MyLabel, WINDOWPAL
from jparty.ui.widgets.common import add_shadow
from jparty.ui.widgets.scoreboard import NameLabel

SUMMARY_CURRENT_COLORS = [
    QColor("#ffd447"),
    QColor("#57d6ff"),
    QColor("#ff7b9c"),
    QColor("#6df2a0"),
    QColor("#f7a44c"),
    QColor("#b990ff"),
]
SUMMARY_ORIGINAL_COLOR = QColor(210, 210, 210, 120)
SUMMARY_GRID_COLOR = QColor(255, 255, 255, 45)


class SummaryGraphWidget(QWidget):
    """Draw the end-of-game score history graph."""

    def __init__(
        self,
        current_series: list[EndGameSeries],
        original_series: list[EndGameSeries],
        color_map: dict[int, QColor],
        parent: object = None,
    ) -> None:
        """Initialize the custom score-history graph widget."""
        super().__init__(parent)
        self.current_series = current_series
        self.original_series = original_series
        self.color_map = color_map
        self.setMinimumHeight(320)
        self.setAutoFillBackground(True)
        self.setPalette(CARDPAL)
        add_shadow(self)

    def _all_scores(self) -> list[int]:
        """Return every score value visible in the graph."""
        scores = []
        for series in self.current_series + self.original_series:
            scores.extend(series.scores)
        return scores or [0]

    def paintEvent(self, event: object) -> None:
        """Render axes, gridlines, and player score traces."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(42, 18, -18, -36)
        painter.fillRect(self.rect(), CARDPAL.color(QPalette.ColorRole.Window))

        min_score = min(self._all_scores())
        max_score = max(self._all_scores())
        if min_score == max_score:
            min_score -= 200
            max_score += 200
        score_padding = max((max_score - min_score) * 0.08, 100)
        min_score -= score_padding
        max_score += score_padding

        max_points = max(
            [len(series.scores) for series in self.current_series + self.original_series]
            or [1]
        )
        y_ticks = 5

        def x_pos(index: int) -> float:
            if max_points <= 1:
                return rect.left()
            return rect.left() + (rect.width() * index / (max_points - 1))

        def y_pos(score: int) -> float:
            span = max_score - min_score or 1
            return rect.bottom() - ((score - min_score) / span) * rect.height()

        painter.setPen(QPen(SUMMARY_GRID_COLOR, 1))
        for tick_index in range(y_ticks + 1):
            y = rect.top() + (rect.height() * tick_index / y_ticks)
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        for point_index in range(max_points):
            x = x_pos(point_index)
            painter.drawLine(int(x), rect.top(), int(x), rect.bottom())

        axis_pen = QPen(QColor("white"), 2)
        painter.setPen(axis_pen)
        painter.drawLine(rect.left(), rect.top(), rect.left(), rect.bottom())
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        painter.setPen(QColor("white"))
        painter.drawText(rect.left(), rect.bottom() + 28, "Question #")
        painter.save()
        painter.translate(14, rect.center().y())
        painter.rotate(-90)
        painter.drawText(0, 0, "Score")
        painter.restore()

        for tick_index in range(y_ticks + 1):
            score = int(max_score - ((max_score - min_score) * tick_index / y_ticks))
            y = rect.top() + (rect.height() * tick_index / y_ticks)
            painter.drawText(4, int(y) + 5, f"${score:,}")

        if max_points > 1:
            x_step = max(1, ceil(max_points / 8))
            for point_index in range(0, max_points, x_step):
                painter.drawText(int(x_pos(point_index)) - 8, rect.bottom() + 16, str(point_index))
            if (max_points - 1) % x_step != 0:
                painter.drawText(rect.right() - 8, rect.bottom() + 16, str(max_points - 1))

        for series in self.original_series:
            self._draw_series(painter, rect, series, SUMMARY_ORIGINAL_COLOR, 2, 4)
        for series in self.current_series:
            color = self.color_map.get(series.player_number, QColor("white"))
            self._draw_series(painter, rect, series, color, 3, 6)

    def _draw_series(
        self,
        painter: QPainter,
        rect: object,
        series: EndGameSeries,
        color: QColor,
        width: int,
        marker_size: int,
    ) -> None:
        """Draw one score-history series."""
        if not series.scores:
            return
        max_points = max(len(series.scores) - 1, 1)
        all_scores = self._all_scores()
        min_score = min(all_scores)
        max_score = max(all_scores)
        if min_score == max_score:
            min_score -= 200
            max_score += 200
        score_padding = max((max_score - min_score) * 0.08, 100)
        min_score -= score_padding
        max_score += score_padding

        def x_pos(index: int) -> float:
            return rect.left() + (rect.width() * index / max_points)

        def y_pos(score: int) -> float:
            span = max_score - min_score or 1
            return rect.bottom() - ((score - min_score) / span) * rect.height()

        pen = QPen(color, width)
        painter.setPen(pen)
        path = QPainterPath()
        first_point = QPointF(x_pos(0), y_pos(series.scores[0]))
        path.moveTo(first_point)
        for index, score in enumerate(series.scores[1:], start=1):
            path.lineTo(QPointF(x_pos(index), y_pos(score)))
        painter.drawPath(path)
        painter.setBrush(color)
        for index, score in enumerate(series.scores):
            painter.drawEllipse(QPointF(x_pos(index), y_pos(score)), marker_size, marker_size)


class LegendEntry(QWidget):
    """Render one legend row with a color swatch and player name/signature."""

    def __init__(self, name: str, color: QColor, parent: object = None) -> None:
        """Initialize a current-player legend entry."""
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        swatch = QFrame(self)
        swatch.setFixedSize(18, 18)
        swatch.setStyleSheet(
            "QFrame { border-radius: 4px; background-color: %s; }" % color.name()
        )
        layout.addWidget(swatch, 0, Qt.AlignmentFlag.AlignTop)
        label = NameLabel(name, self)
        label.setMinimumHeight(34)
        layout.addWidget(label, 1)
        self.setLayout(layout)


class PlayerSummaryCard(QWidget):
    """Render one player's end-of-game stat card."""

    def __init__(self, player_stats: object, color: QColor, parent: object = None) -> None:
        """Initialize the player stats card."""
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self.setPalette(WINDOWPAL)
        add_shadow(self)
        layout = QVBoxLayout()
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        marker = QFrame(self)
        marker.setFixedSize(18, 18)
        marker.setStyleSheet(
            "QFrame { border-radius: 4px; background-color: %s; }" % color.name()
        )
        header.addWidget(marker, 0, Qt.AlignmentFlag.AlignTop)
        name_label = NameLabel(player_stats.name, self)
        name_label.setMinimumHeight(40)
        header.addWidget(name_label, 1)
        layout.addLayout(header)

        final_score = QLabel(f"Final Score: ${player_stats.final_score:,}", self)
        final_score.setStyleSheet(
            "QLabel { color: #1010a1; font-size: 26px; font-weight: 800; }"
        )
        layout.addWidget(final_score)

        for stat_line in [
            f"Coryat: ${player_stats.coryat:,}",
            f"Right / Wrong: {player_stats.right_count} / {player_stats.wrong_count}",
            f"Questions Buzzed: {player_stats.questions_buzzed_on}",
            f"Early Buzzes: {player_stats.early_buzzes}",
            self._race_line(player_stats),
        ]:
            label = QLabel(stat_line, self)
            label.setStyleSheet(
                "QLabel { color: black; font-size: 18px; font-weight: 600; }"
            )
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addStretch(1)
        self.setLayout(layout)

    def _race_line(self, player_stats: object) -> str:
        """Format the race-win stat line for one player."""
        percentage = player_stats.race_win_percentage
        if percentage is None:
            percentage_text = "—"
        else:
            percentage_text = f"{percentage:.0f}%"
        return (
            "Race Wins: "
            f"{player_stats.race_wins}/{player_stats.race_opportunities} ({percentage_text})"
        )


class EndGameSummaryDisplay(QWidget):
    """Render the audience-facing end-of-game summary view."""

    def __init__(self, summary: EndGameSummary, parent: object = None) -> None:
        """Initialize the complete end-of-game summary screen."""
        super().__init__(parent)
        self.summary = summary
        self.color_map = {
            player.player_number: SUMMARY_CURRENT_COLORS[index % len(SUMMARY_CURRENT_COLORS)]
            for index, player in enumerate(self.summary.current_players)
        }
        self.setAutoFillBackground(True)
        self.setPalette(CARDPAL)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(18)

        title = MyLabel("Game Summary", lambda: self.height() * 0.08, self)
        recap_text = "We have a tie!" if summary.is_tie else "Winner:"
        recap = QLabel(recap_text, self)
        recap.setStyleSheet(
            "QLabel { color: #ffd447; font-size: 28px; font-weight: 700; }"
        )
        recap_row = QHBoxLayout()
        recap_row.addWidget(recap, 0, Qt.AlignmentFlag.AlignVCenter)
        if not summary.is_tie and summary.current_players:
            winner_number = summary.winner_player_numbers[0]
            winner = next(
                (
                    player
                    for player in summary.current_players
                    if player.player_number == winner_number
                ),
                None,
            )
            if winner is not None:
                winner_label = NameLabel(winner.name, self)
                winner_label.setMinimumHeight(50)
                recap_row.addWidget(winner_label, 0, Qt.AlignmentFlag.AlignVCenter)
        recap_row.addStretch(1)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(18)

        left_panel = QVBoxLayout()
        left_panel.setSpacing(14)
        self.graph_widget = SummaryGraphWidget(
            self.summary.current_series,
            self.summary.original_series,
            self.color_map,
            self,
        )
        left_panel.addWidget(self.graph_widget, 5)
        legend_title = QLabel("Current Players", self)
        legend_title.setStyleSheet(
            "QLabel { color: #ffd447; font-size: 22px; font-weight: 700; }"
        )
        left_panel.addWidget(legend_title)
        legend_grid = QGridLayout()
        legend_grid.setHorizontalSpacing(20)
        legend_grid.setVerticalSpacing(10)
        for index, player in enumerate(self.summary.current_players):
            entry = LegendEntry(player.name, self.color_map[player.player_number], self)
            legend_grid.addWidget(entry, index // 2, index % 2)
        left_panel.addLayout(legend_grid, 2)

        right_panel = QVBoxLayout()
        right_panel.setSpacing(14)
        for player in self.summary.current_players:
            card = PlayerSummaryCard(player, self.color_map[player.player_number], self)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            right_panel.addWidget(card, 1)
        right_panel.addStretch(1)

        content_layout.addLayout(left_panel, 3)
        content_layout.addLayout(right_panel, 2)

        main_layout.addWidget(title)
        main_layout.addLayout(recap_row)
        main_layout.addLayout(content_layout, 1)
        self.setLayout(main_layout)
        self.show()


class FinalDisplay(QWidget):
    """Container widget for Final Jeopardy answer adjudication."""

    def __init__(self, game: object, parent: object) -> None:
        """Initialize the Final Jeopardy display container.

        Args:
            game: Active game instance driving Final Jeopardy flow.
            parent: Parent display widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.setGeometry(parent.rect())
        self.answer_widget = FinalAnswerWidget(game, self)
        main_layout = QVBoxLayout()
        main_layout.addStretch(4)
        main_layout.addWidget(self.answer_widget, 2)
        main_layout.addStretch(3)
        self.setLayout(main_layout)
        self.show()


class FinalAnswerWidget(QWidget):
    """Show Final Jeopardy guesses, wagers, and winner announcements."""

    def __init__(self, game: object, parent: object) -> None:
        """Initialize the final answer widget."""
        super().__init__(parent)
        self.game = game
        self.winner_label = None
        self.main_layout = QVBoxLayout()
        self.guess_label = MyLabel("", self.startFontSize, self)
        self.wager_label = MyLabel("", self.startFontSize, self)
        self.main_layout.addStretch(1)
        self.main_layout.addWidget(self.guess_label, 5)
        self.main_layout.addWidget(self.wager_label, 5)
        self.main_layout.addStretch(1)
        self.setLayout(self.main_layout)
        self.setPalette(CARDPAL)
        self.setAutoFillBackground(True)
        add_shadow(self)
        self.show()

    def startFontSize(self) -> object:
        """Return the starting font size for final-round labels."""
        return self.height() * 0.2

    def show_winner(self, winner: object) -> None:
        """Replace wager text with a winner announcement."""
        self.guess_label.setText("We have a winner!")
        self.wager_label.setText("")
        self.winner_label = NameLabel(winner.name, self)
        self.main_layout.replaceWidget(self.wager_label, self.winner_label)

    def show_tie(self) -> None:
        """Show a tie announcement in the final-round UI."""
        self.guess_label.setText("We have a tie!")
        self.wager_label.setText("")
