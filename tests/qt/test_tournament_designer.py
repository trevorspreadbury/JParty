"""Qt tests for the tournament bracket designer."""

import pytest
from PyQt6.QtWidgets import QLabel

from jparty.domain.tournament.setup import BracketSettings
from jparty.ui.widgets.tournament.bracket import BracketDesigner
from jparty.ui.widgets.tournament.window import TournamentWindow
from jparty.ui.widgets.welcome import Welcome
from tests.qt.test_welcome_widget import StubGame

pytestmark = pytest.mark.qt


def game_cards(dialog: BracketDesigner) -> list[QLabel]:
    """Return every game card in the bracket view."""
    return [
        label
        for label in dialog.bracket_widget.findChildren(QLabel)
        if label.objectName() in {"game_card", "chase_game_card"}
    ]


def test_designer_shows_default_bracket(qtbot: object) -> None:
    """The designer opens on a playable bracket with its totals."""
    dialog = BracketDesigner()
    qtbot.addWidget(dialog)
    assert dialog.plan.valid
    assert "Total games: 9" in dialog.summary_label.text()
    assert len(game_cards(dialog)) == 9
    assert not dialog.byes_spinbox.isEnabled()


def test_changing_players_redraws_bracket(qtbot: object) -> None:
    """Odd field sizes add chase games to the bracket."""
    dialog = BracketDesigner()
    qtbot.addWidget(dialog)
    dialog.player_spinbox.setValue(17)
    cards = game_cards(dialog)
    assert len(cards) == 10
    assert sum(card.objectName() == "chase_game_card" for card in cards) == 1
    assert "9-10 of 17" in dialog.summary_label.text()


def test_invalid_options_explain_the_problem(qtbot: object) -> None:
    """Options that cannot work show why and clear the bracket."""
    dialog = BracketDesigner()
    qtbot.addWidget(dialog)
    dialog.player_spinbox.setValue(30)
    assert not dialog.plan.valid
    assert "won't work" in dialog.summary_label.text()
    assert "Add a second round" in dialog.summary_label.text()
    assert game_cards(dialog) == []


def test_second_round_controls(qtbot: object) -> None:
    """Byes reset the second-round field to fill the remaining spots."""
    dialog = BracketDesigner()
    qtbot.addWidget(dialog)
    dialog.player_spinbox.setValue(30)
    dialog.second_round_checkbox.setChecked(True)
    assert dialog.byes_spinbox.isEnabled()
    dialog.byes_spinbox.setValue(3)
    assert dialog.second_round_players_spinbox.value() == 18
    assert dialog.plan.valid
    assert dialog.plan.total_games == 20
    dialog.second_round_players_spinbox.setValue(12)
    assert dialog.plan.rounds[0].layout.spots == 15


def test_second_round_unchecks_for_small_fields(qtbot: object) -> None:
    """Dropping to nine or fewer players turns the second round off."""
    dialog = BracketDesigner()
    qtbot.addWidget(dialog)
    dialog.player_spinbox.setValue(30)
    dialog.second_round_checkbox.setChecked(True)
    dialog.player_spinbox.setValue(9)
    assert not dialog.second_round_checkbox.isChecked()
    assert not dialog.second_round_checkbox.isEnabled()
    assert dialog.plan.valid


def test_second_round_comes_back_when_the_field_grows(qtbot: object) -> None:
    """The host's second-round choice returns once there are enough players."""
    dialog = BracketDesigner()
    qtbot.addWidget(dialog)
    dialog.player_spinbox.setValue(30)
    dialog.second_round_checkbox.setChecked(True)
    dialog.player_spinbox.setValue(9)
    dialog.player_spinbox.setValue(30)
    assert dialog.second_round_checkbox.isChecked()
    assert dialog.bracket_settings().use_second_round

    # A second round the host turned off stays off.
    dialog.second_round_checkbox.setChecked(False)
    dialog.player_spinbox.setValue(9)
    dialog.player_spinbox.setValue(30)
    assert not dialog.second_round_checkbox.isChecked()


def test_locked_player_count_follows_the_roster(qtbot: object) -> None:
    """In a tournament, the roster sets the count and saved options apply."""
    designer = BracketDesigner(roster_sets_players=True)
    qtbot.addWidget(designer)
    plans = []
    designer.plan_changed.connect(lambda: plans.append(designer.plan))
    assert designer.player_spinbox.isReadOnly()
    designer.set_player_count(30)
    designer.set_bracket_settings(
        BracketSettings(use_second_round=True, semifinal_byes=3)
    )
    assert designer.second_round_players_spinbox.value() == 18
    assert designer.plan.valid
    assert designer.plan.total_games == 20
    assert designer.bracket_settings() == BracketSettings(True, 3, 18)
    assert plans[-1] is designer.plan


def test_welcome_tournament_button_opens_one_window(qtbot: object) -> None:
    """The welcome screen opens the Tournament window and reuses it."""
    widget = Welcome(StubGame())
    qtbot.addWidget(widget)
    widget.tournament_button.click()
    window = widget.tournament_window
    assert isinstance(window, TournamentWindow)
    assert window.isVisible()
    widget.tournament_button.click()
    assert widget.tournament_window is window
    window.close()
