"""Async helpers for the welcome workflow."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from threading import Thread


class WelcomeLoader:
    """Run welcome-screen loading work on background threads."""

    def run_async(self, target: object) -> Thread:
        """Start a daemon thread for one welcome loading task."""
        thread = Thread(target=target, daemon=True)
        thread.start()
        return thread


class LatestRequest:
    """Track the newest load for one target, so older results are dropped.

    Every load takes an id from :meth:`begin`. Its result is applied only
    while :meth:`is_current` still holds for that id; starting another load,
    or :meth:`cancel`, makes older ids stale. A worker can also poll
    :meth:`is_current` to stop early.

    Targets that pass the same ``ids`` counter never share an id, so a result
    meant for a target that was rebuilt can't match its replacement.
    """

    def __init__(self, ids: Iterator[int] | None = None) -> None:
        """Start with no load in flight.

        Args:
            ids: Source of request ids, shared between targets when given.
        """
        self._ids = ids if ids is not None else itertools.count(1)
        self.current = 0

    def begin(self) -> int:
        """Make a new request the current one and return its id."""
        self.current = next(self._ids)
        return self.current

    def cancel(self) -> None:
        """Make every request started so far stale."""
        self.begin()

    def is_current(self, request_id: object) -> bool:
        """Return whether ``request_id`` is the newest request."""
        return request_id == self.current
