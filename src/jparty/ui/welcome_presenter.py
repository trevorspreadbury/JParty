"""Plain-Python presenter state for the welcome workflow."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WelcomeState:
    """Serializable state derived from the welcome workflow."""

    summary_text: str = ""
    loading_summary: bool = False
    resume_path: str | None = None
    regular_game_id: str = ""
    advanced_enabled: bool = False
    selected_rounds: list[int] = field(default_factory=list)
    board_selection_configs: list[dict] = field(default_factory=list)
    expected_player_count: int | None = None
    resume_claimed: int = 0
    resume_total: int = 0
    start_enabled: bool = False
    advanced_start_enabled: bool = False
    status_text: str = ""


class WelcomePresenter:
    """Own derived state for the host-side welcome workflow."""

    def __init__(self, game: object) -> None:
        """Store the game and initialize presenter state."""
        self.game = game
        self.state = WelcomeState()

    def set_loading(self, loading: bool) -> WelcomeState:
        """Update summary-loading state."""
        self.state.loading_summary = loading
        return self.state

    def set_resume_path(self, resume_path: str | None) -> WelcomeState:
        """Store the current resume path when resuming a saved session."""
        self.state.resume_path = resume_path
        return self.state

    def set_regular_game_id(self, game_id: str) -> WelcomeState:
        """Store the current single-game id text input."""
        self.state.regular_game_id = game_id
        return self.state

    def set_advanced_enabled(self, enabled: bool) -> WelcomeState:
        """Store whether advanced mode is currently active."""
        self.state.advanced_enabled = enabled
        return self.state

    def set_summary_text(self, summary_text: str) -> WelcomeState:
        """Store the current base summary text."""
        self.state.summary_text = summary_text
        return self.state

    def sync_from_game(self) -> WelcomeState:
        """Refresh derived state from the current game object."""
        selected_rounds = getattr(self.game, "selected_round_indices", lambda: [])()
        board_selection_configs = getattr(
            self.game, "board_selection_configs", lambda: []
        )()
        expected_player_count = getattr(
            self.game, "expected_player_count", lambda: None
        )()
        resume_claimed, resume_total = getattr(
            self.game, "resume_claim_status", lambda: (0, 0)
        )()
        self.state.selected_rounds = list(selected_rounds or [])
        self.state.board_selection_configs = list(board_selection_configs or [])
        self.state.expected_player_count = expected_player_count
        self.state.resume_claimed = resume_claimed
        self.state.resume_total = resume_total
        return self.compute_start_state()

    def compute_start_state(self) -> WelcomeState:
        """Compute button enablement and status text from current state."""
        if self.state.advanced_enabled:
            rounds_selected = bool(self.state.board_selection_configs)
        else:
            rounds_selected = bool(self.state.selected_rounds) or bool(
                self.state.board_selection_configs
            )

        startable = bool(getattr(self.game, "startable", lambda: False)())
        start_enabled = startable and rounds_selected
        self.state.start_enabled = start_enabled
        self.state.advanced_start_enabled = start_enabled

        status_text = self.state.summary_text
        if self.state.resume_path is not None and status_text:
            status_text += f"\nClaimed {self.state.resume_claimed} of {self.state.resume_total} saved players."
        if (
            not start_enabled
            and self.state.expected_player_count is not None
            and status_text
        ):
            status_text += (
                "\nClaim every saved player profile to resume "
                f"({self.state.resume_claimed}/{self.state.resume_total})."
            )
        elif (
            not start_enabled
            and not self.state.loading_summary
            and not rounds_selected
            and status_text
        ):
            status_text += "\n\nSelect at least one round to play."
        self.state.status_text = status_text
        return self.state
