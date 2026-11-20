"""A tournament's rankings: every player, best first.

:class:`RankingsTable` shows :func:`jparty.domain.tournament_rankings
.tournament_rankings` as a table. The Tournament window shows it on a
Rankings tab, and the play panel's Rankings button opens it in a
:class:`RankingsDialog`.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.tournament_rankings import PlayerRanking

LAYOUT_SPACING = 8
RANKING_COLUMNS = (
    "Rank",
    "Player",
    "Reached",
    "Status",
    "Games",
    "Total",
    "Best",
    "Coryat",
)
(
    COLUMN_RANK,
    COLUMN_PLAYER,
    COLUMN_REACHED,
    COLUMN_STATUS,
    COLUMN_GAMES,
    COLUMN_TOTAL,
    COLUMN_BEST,
    COLUMN_CORYAT,
) = range(len(RANKING_COLUMNS))
OUT_COLOR = Qt.GlobalColor.gray
EXPLANATION = (
    "Ranked by the furthest round reached, players still in first, then by "
    "score in their latest round."
)


def _money(value: int | None) -> str:
    """Return ``value`` as dollars, or ``""`` for ``None``."""
    if value is None:
        return ""
    return f"-${-value:,}" if value < 0 else f"${value:,}"


def ranking_cells(ranking: PlayerRanking) -> tuple[str, ...]:
    """Return the table's text for one player, in column order."""
    return (
        "" if ranking.rank is None else str(ranking.rank),
        ranking.name,
        ranking.reached,
        ranking.status,
        str(ranking.games),
        _money(ranking.total_score) if ranking.games else "",
        _money(ranking.best_score),
        _money(ranking.coryat),
    )


class RankingsTable(QWidget):
    """A read-only table of a tournament's rankings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build an empty table; :meth:`show_rankings` fills it.

        Args:
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.rankings: list[PlayerRanking] = []
        self.explanation = QLabel(EXPLANATION, self)
        self.explanation.setWordWrap(True)
        self.table = QTableWidget(0, len(RANKING_COLUMNS), self)
        self.table.setHorizontalHeaderLabels(RANKING_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_STATUS, QHeaderView.ResizeMode.Stretch)
        layout = QVBoxLayout(self)
        layout.setSpacing(LAYOUT_SPACING)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING,) * 4)
        layout.addWidget(self.explanation)
        layout.addWidget(self.table, 1)

    def show_rankings(self, rankings: Sequence[PlayerRanking]) -> None:
        """Show ``rankings``, greying out players who are out.

        Args:
            rankings: Every player, best first.

        Returns:
            ``None``.
        """
        self.rankings = list(rankings)
        self.table.setRowCount(len(self.rankings))
        for row, ranking in enumerate(self.rankings):
            for column, text in enumerate(ranking_cells(ranking)):
                item = QTableWidgetItem(text)
                if column not in (COLUMN_PLAYER, COLUMN_REACHED, COLUMN_STATUS):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if ranking.out:
                    item.setForeground(QBrush(OUT_COLOR))
                self.table.setItem(row, column, item)

    def cell_text(self, row: int, column: int) -> str:
        """Return the text shown in one cell, for tests."""
        item = self.table.item(row, column)
        return item.text() if item is not None else ""


class RankingsDialog(QDialog):
    """A window showing a tournament's rankings."""

    def __init__(
        self,
        title: str,
        rankings: Sequence[PlayerRanking],
        parent: QWidget | None = None,
    ) -> None:
        """Show ``rankings``.

        Args:
            title: Window title.
            rankings: Every player, best first.
            parent: Optional parent widget.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 560)
        self.rankings_table = RankingsTable(self)
        self.rankings_table.show_rankings(rankings)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING * 2,) * 4)
        layout.addWidget(self.rankings_table, 1)
        layout.addWidget(buttons)
