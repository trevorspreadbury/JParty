"""Async helpers for the welcome workflow."""

from __future__ import annotations

from threading import Thread


class WelcomeLoader:
    """Run welcome-screen loading work on background threads."""

    def run_async(self, target: object) -> Thread:
        """Start a daemon thread for one welcome loading task."""
        thread = Thread(target=target, daemon=True)
        thread.start()
        return thread
