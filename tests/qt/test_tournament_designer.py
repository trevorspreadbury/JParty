"""Qt tests for the tournament bracket designer."""

import pytest
from PyQt6.QtWidgets import QLabel

from jparty.ui.widgets.tournament import TournamentDesigner
from jparty.ui.widgets.welcome import Welcome
from tests.qt.test_welcome_widget import StubGame

pytestmark = pytest.mark.qt


def game_cards(dialog: TournamentDesigner) -> list[QLabel]:
    """Return every game card in the bracket view."""
    return [
        label
        for label in dialog.bracket_widget.findChildren(QLabel)
        if label.objectName() in {"game_card", "chase_game_card"}
    ]


def test_designer_shows_default_bracket(qtbot: object) -> None:
    """The designer opens on a playable bracket with its totals."""
    dialog = TournamentDesigner()
    qtbot.addWidget(dialog)
    assert dialog.plan.valid
    assert "Total games: 9" in dialog.summary_label.text()
    assert len(game_cards(dialog)) == 9
    assert not dialog.byes_spinbox.isEnabled()


def test_changing_players_redraws_bracket(qtbot: object) -> None:
    """Odd field sizes add chase games to the bracket."""
    dialog = TournamentDesigner()
    qtbot.addWidget(dialog)
    dialog.player_spinbox.setValue(17)
    cards = game_cards(dialog)
    assert len(cards) == 10
    assert sum(card.objectName() == "chase_game_card" for card in cards) == 1
    assert "9-10 of 17" in dialog.summary_label.text()


def test_invalid_options_explain_the_problem(qtbot: object) -> None:
    """Options that cannot work show why and clear the bracket."""
    dialog = TournamentDesigner()
    qtbot.addWidget(dialog)
    dialog.player_spinbox.setValue(30)
    assert not dialog.plan.valid
    assert "won't work" in dialog.summary_label.text()
    assert "Add a second round" in dialog.summary_label.text()
    assert game_cards(dialog) == []


def test_second_round_controls(qtbot: object) -> None:
    """Byes reset the second-round field to fill the remaining spots."""
    dialog = TournamentDesigner()
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
    dialog = TournamentDesigner()
    qtbot.addWidget(dialog)
    dialog.player_spinbox.setValue(30)
    dialog.second_round_checkbox.setChecked(True)
    dialog.player_spinbox.setValue(9)
    assert not dialog.second_round_checkbox.isChecked()
    assert not dialog.second_round_checkbox.isEnabled()
    assert dialog.plan.valid


def test_welcome_tournament_button_opens_one_designer(qtbot: object) -> None:
    """The welcome screen opens the designer and reuses it."""
    widget = Welcome(StubGame())
    qtbot.addWidget(widget)
    widget.tournament_button.click()
    designer = widget.tournament_designer
    assert isinstance(designer, TournamentDesigner)
    assert designer.isVisible()
    widget.tournament_button.click()
    assert widget.tournament_designer is designer
    designer.close()
