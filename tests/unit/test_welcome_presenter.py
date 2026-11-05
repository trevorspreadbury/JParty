"""Unit tests for the non-Qt welcome presenter."""

import pytest
from jparty.ui.welcome_presenter import WelcomePresenter

pytestmark = pytest.mark.unit


class StubWelcomeGame:
    """Small game stub for presenter tests."""

    def __init__(self) -> None:
        """Initialize a startable game stub."""
        self._selected_round_indices = []
        self._board_selection_configs = []
        self._expected_player_count = None
        self._resume_claim_status = (0, 0)
        self._startable = False

    def selected_round_indices(self) -> list[int]:
        """Return selected round indices."""
        return list(self._selected_round_indices)

    def board_selection_configs(self) -> list[dict]:
        """Return saved board selection configs."""
        return list(self._board_selection_configs)

    def expected_player_count(self) -> int | None:
        """Return expected resume player count."""
        return self._expected_player_count

    def resume_claim_status(self) -> tuple[int, int]:
        """Return claimed and total resume counts."""
        return self._resume_claim_status

    def startable(self) -> bool:
        """Return whether the game can start."""
        return self._startable


def test_presenter_requires_round_selection_for_regular_mode() -> None:
    """Regular mode should not enable start without a selected round."""
    game = StubWelcomeGame()
    game._startable = True
    presenter = WelcomePresenter(game)
    presenter.set_summary_text("Fixture game")

    state = presenter.sync_from_game()

    assert state.start_enabled is False
    assert "Select at least one round to play." in state.status_text


def test_presenter_enables_start_for_complete_advanced_config() -> None:
    """Advanced mode should use board selections as readiness."""
    game = StubWelcomeGame()
    game._startable = True
    game._board_selection_configs = [{"game_id": "111"}]
    presenter = WelcomePresenter(game)
    presenter.set_advanced_enabled(True)
    presenter.set_summary_text("Advanced fixture")

    state = presenter.sync_from_game()

    assert state.start_enabled is True
    assert state.advanced_start_enabled is True


def test_presenter_resume_status_includes_claim_progress() -> None:
    """Resume mode should surface claim progress and gating text."""
    game = StubWelcomeGame()
    game._expected_player_count = 3
    game._resume_claim_status = (1, 3)
    presenter = WelcomePresenter(game)
    presenter.set_resume_path("C:/saved")
    presenter.set_summary_text("Resume fixture")

    state = presenter.sync_from_game()

    assert "Claimed 1 of 3 saved players." in state.status_text
    assert "Claim every saved player profile to resume (1/3)." in state.status_text
