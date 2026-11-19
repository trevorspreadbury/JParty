"""Tournament bracket designer.

The host picks a player count and optional second round, and the designer
shows the resulting bracket, total games, and how many players get more than
one game. It is used on its own from the Tournament window and as a
tournament's Bracket tab, where the roster sets the player count. Bracket
rules live in :mod:`jparty.domain.tournament`.
"""

from html import escape

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from jparty.domain.tournament import (
    MAX_TOURNAMENT_PLAYERS,
    MIN_TOURNAMENT_PLAYERS,
    SEMIFINAL_FIELD_SIZE,
    BracketGame,
    BracketRound,
    TournamentOptions,
    TournamentPlan,
    default_second_round_players,
    describe_plan,
    plan_tournament,
)
from jparty.domain.tournament_setup import BracketSettings

DEFAULT_TOURNAMENT_PLAYERS = 15
LAYOUT_SPACING = 8
COLUMN_MIN_WIDTH = 190
GAME_CARD_STYLE = (
    "QLabel { background: white; color: black; border: 1px solid #1c2a8c;"
    " border-radius: 4px; padding: 4px; }"
)
CHASE_CARD_STYLE = (
    "QLabel { background: #fff4d6; color: black; border: 1px dashed #b37400;"
    " border-radius: 4px; padding: 4px; }"
)
PROBLEM_STYLE = "QLabel { color: #b00020; }"


class BracketDesigner(QWidget):
    """Controls and a live view for trying tournament bracket shapes.

    Attributes:
        plan: The bracket for the current options.
    """

    plan_changed = pyqtSignal()

    def __init__(
        self, parent: QWidget | None = None, roster_sets_players: bool = False
    ) -> None:
        """Build the option controls, summary, and bracket view.

        Args:
            parent: Optional parent widget.
            roster_sets_players: Lock the player count, which then follows
                :meth:`set_player_count`, for a tournament's Bracket tab.

        Returns:
            ``None``.
        """
        super().__init__(parent)
        self.plan: TournamentPlan | None = None

        self.player_spinbox = QSpinBox(self)
        self.player_spinbox.setRange(MIN_TOURNAMENT_PLAYERS, MAX_TOURNAMENT_PLAYERS)
        self.player_spinbox.setValue(DEFAULT_TOURNAMENT_PLAYERS)
        if roster_sets_players:
            self.player_spinbox.setReadOnly(True)
            self.player_spinbox.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            self.player_spinbox.setToolTip(
                "Change the player count on the Players tab."
            )
        self.second_round_checkbox = QCheckBox(
            "Add a second round before the Semifinals", self
        )
        self.byes_spinbox = QSpinBox(self)
        self.byes_spinbox.setRange(0, SEMIFINAL_FIELD_SIZE - 1)
        self.byes_spinbox.setToolTip(
            "Top-scoring preliminary players who skip straight to the Semifinals."
            " Winners come first, then wildcards."
        )
        self.second_round_players_spinbox = QSpinBox(self)
        self.second_round_players_spinbox.setRange(1, MAX_TOURNAMENT_PLAYERS)
        self.second_round_players_spinbox.setValue(default_second_round_players(0))
        self.second_round_players_spinbox.setToolTip(
            "Players who advance from the preliminaries to the second round, "
            "not counting byes."
        )

        form = QFormLayout()
        form.setSpacing(LAYOUT_SPACING)
        form.addRow("Players:", self.player_spinbox)
        form.addRow(self.second_round_checkbox)
        form.addRow("Semifinal byes:", self.byes_spinbox)
        form.addRow("Second-round players:", self.second_round_players_spinbox)

        self.summary_label = QLabel(self)
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.summary_label.setWordWrap(True)
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignTop)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(LAYOUT_SPACING * 3)
        controls_layout.addLayout(form, 1)
        controls_layout.addWidget(self.summary_label, 2)

        self.bracket_widget = QWidget()
        self.bracket_layout = QHBoxLayout(self.bracket_widget)
        self.bracket_layout.setSpacing(LAYOUT_SPACING * 2)
        self.bracket_layout.setContentsMargins(
            LAYOUT_SPACING, LAYOUT_SPACING, LAYOUT_SPACING, LAYOUT_SPACING
        )
        self.bracket_scroll = QScrollArea(self)
        self.bracket_scroll.setWidgetResizable(True)
        self.bracket_scroll.setWidget(self.bracket_widget)

        layout = QVBoxLayout(self)
        layout.setSpacing(LAYOUT_SPACING)
        # The app style sets layout margins to zero, so set them here.
        layout.setContentsMargins(*(LAYOUT_SPACING,) * 4)
        layout.addLayout(controls_layout)
        layout.addWidget(self.bracket_scroll, 1)

        self.player_spinbox.valueChanged.connect(self.refresh)
        self.second_round_checkbox.toggled.connect(self.refresh)
        self.byes_spinbox.valueChanged.connect(self.on_byes_changed)
        self.second_round_players_spinbox.valueChanged.connect(self.refresh)
        self.refresh()

    def options(self) -> TournamentOptions:
        """Return the tournament options currently chosen in the controls."""
        return self.bracket_settings().options(self.player_spinbox.value())

    def bracket_settings(self) -> BracketSettings:
        """Return the chosen options apart from the player count."""
        return BracketSettings(
            use_second_round=self.second_round_checkbox.isChecked(),
            semifinal_byes=self.byes_spinbox.value(),
            second_round_players=self.second_round_players_spinbox.value(),
        )

    def set_player_count(self, count: int) -> None:
        """Show the bracket for ``count`` players.

        Args:
            count: Players on the roster. A count outside the planner's range
                is shown as is, and the summary says why it can't work.

        Returns:
            ``None``.
        """
        self.player_spinbox.setRange(
            min(MIN_TOURNAMENT_PLAYERS, count), max(MAX_TOURNAMENT_PLAYERS, count)
        )
        self.player_spinbox.setValue(count)

    def set_bracket_settings(self, settings: BracketSettings) -> None:
        """Show saved options, then redraw once.

        Args:
            settings: Options to show. A ``None`` second-round field uses
                the default for the bye count.

        Returns:
            ``None``.
        """
        controls = (
            self.second_round_checkbox,
            self.byes_spinbox,
            self.second_round_players_spinbox,
        )
        for control in controls:
            control.blockSignals(True)
        self.second_round_checkbox.setChecked(settings.use_second_round)
        self.byes_spinbox.setValue(settings.semifinal_byes)
        self.second_round_players_spinbox.setValue(
            settings.second_round_players
            if settings.second_round_players is not None
            else default_second_round_players(settings.semifinal_byes)
        )
        for control in controls:
            control.blockSignals(False)
        self.refresh()

    def on_byes_changed(self, byes: int) -> None:
        """Reset the second-round field to fill the remaining Semifinal spots.

        Args:
            byes: New number of Semifinal byes.

        Returns:
            ``None``.
        """
        self.second_round_players_spinbox.blockSignals(True)
        self.second_round_players_spinbox.setValue(default_second_round_players(byes))
        self.second_round_players_spinbox.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        """Re-plan the bracket from the controls and redraw it.

        Returns:
            ``None``.
        """
        second_round_allowed = self.player_spinbox.value() > SEMIFINAL_FIELD_SIZE
        self.second_round_checkbox.setEnabled(second_round_allowed)
        if not second_round_allowed and self.second_round_checkbox.isChecked():
            self.second_round_checkbox.blockSignals(True)
            self.second_round_checkbox.setChecked(False)
            self.second_round_checkbox.blockSignals(False)
        use_second_round = self.second_round_checkbox.isChecked()
        self.byes_spinbox.setEnabled(use_second_round)
        self.second_round_players_spinbox.setEnabled(use_second_round)

        self.plan = plan_tournament(self.options())
        self._update_summary(self.plan)
        self._rebuild_bracket(self.plan)
        self.plan_changed.emit()

    def _update_summary(self, plan: TournamentPlan) -> None:
        """Show the plan's totals, or why the options do not work."""
        lines = [escape(line) for line in describe_plan(plan)]
        if plan.valid:
            self.summary_label.setStyleSheet("")
            self.summary_label.setText("<br>".join(lines))
        else:
            self.summary_label.setStyleSheet(PROBLEM_STYLE)
            self.summary_label.setText(
                "<b>This bracket won't work:</b><br>" + "<br>".join(lines)
            )

    def _rebuild_bracket(self, plan: TournamentPlan) -> None:
        """Replace the bracket columns with one column per round."""
        while self.bracket_layout.count():
            item = self.bracket_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for bracket_round in plan.rounds:
            self.bracket_layout.addWidget(self._round_column(bracket_round))
        self.bracket_layout.addStretch(1)

    def _round_column(self, bracket_round: BracketRound) -> QFrame:
        """Return a column showing one round's games and who advances."""
        column = QFrame(self.bracket_widget)
        column.setObjectName("round_column")
        column.setMinimumWidth(COLUMN_MIN_WIDTH)
        column_layout = QVBoxLayout(column)
        column_layout.setSpacing(LAYOUT_SPACING)
        game_count = len(bracket_round.games)
        title = QLabel(
            f"<b>{escape(bracket_round.name)}</b><br>"
            f"{game_count} game{'s' if game_count != 1 else ''}",
            column,
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column_layout.addWidget(title)
        column_layout.addStretch(1)
        for game in bracket_round.games:
            column_layout.addWidget(self._game_card(game, column))
            column_layout.addStretch(1)
        advance = QLabel(f"Advance: {escape(bracket_round.advance_text)}", column)
        advance.setWordWrap(True)
        advance.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column_layout.addWidget(advance)
        return column

    @staticmethod
    def _game_card(game: BracketGame, parent: QWidget) -> QLabel:
        """Return a card listing a game's name and where each seat comes from."""
        seats = "<br>".join(escape(seat) for seat in game.seats)
        card = QLabel(f"<b>{escape(game.name)}</b><br>{seats}", parent)
        card.setObjectName("chase_game_card" if game.chase else "game_card")
        card.setStyleSheet(CHASE_CARD_STYLE if game.chase else GAME_CARD_STYLE)
        # Seat labels are short; without word wrap the label reports its full
        # height, so a long round scrolls instead of squashing the cards.
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        # Apply the style sheet now so the size hint includes its padding.
        card.ensurePolished()
        return card
