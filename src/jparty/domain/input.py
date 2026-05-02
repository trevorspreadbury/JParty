"""Keyboard input and timer primitives for gameplay flow.

This module contains the low-level domain helpers that map keyboard keys to
players, schedule clue timing callbacks, and manage the activation state of
host-side keystroke events. The game engine builds on these utilities to drive
buzzing, adjudication, and navigation through a match.
"""

import logging
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass

from PyQt6.QtCore import Qt

MAX_PLAYERS = 6
index_to_key = {
    0: Qt.Key.Key_Q,
    1: Qt.Key.Key_W,
    2: Qt.Key.Key_E,
    3: Qt.Key.Key_R,
    4: Qt.Key.Key_T,
    5: Qt.Key.Key_Y,
}


class QuestionTimer:
    """Run a delayed callback that can be paused and resumed.

    The timer tracks elapsed time so clue countdowns can stop and continue
    without losing the remaining duration.
    """

    def __init__(
        self, interval: object, callback: object, *args: object, **kwargs: object
    ) -> None:
        """Initialize a timer for a delayed callback.

        Args:
            interval: Total delay, in seconds, before the callback should run.
            callback: Callable invoked when the timer completes.
            *args: Positional arguments forwarded to ``callback``.
            **kwargs: Keyword arguments forwarded to ``callback``.

        Returns:
            ``None``.
        """
        self.callback = callback
        self.args = args
        self.kwargs = kwargs
        self.interval = interval
        self._thread = None
        self._start_time = None
        self._elapsed_time = 0

    def run(self, interval: object) -> None:
        """Sleep for the remaining interval and invoke the callback if active.

        Args:
            interval: Number of seconds to wait before firing the callback.

        Returns:
            ``None``.
        """
        thread = self._thread
        time.sleep(interval)
        if thread == self._thread:
            self.callback(*self.args, **self.kwargs)

    def start(self) -> None:
        """Start the timer from its current elapsed state.

        Returns:
            ``None``.
        """
        self.resume()

    def cancel(self) -> None:
        """Cancel the timer by delegating to ``pause()``.

        Returns:
            ``None``.
        """
        self.pause()

    def pause(self) -> None:
        """Pause the timer and accumulate elapsed time.

        Returns:
            ``None``.
        """
        self._thread = None
        self._elapsed_time += time.time() - self._start_time

    def resume(self) -> None:
        """Resume the timer using the remaining duration.

        Returns:
            ``None``.
        """
        self._thread = threading.Thread(
            target=self.run, args=(self.interval - self._elapsed_time,)
        )
        self._thread.start()
        self._start_time = time.time()


@dataclass
class KeystrokeEvent:
    """Describe a single keyboard-triggered game action."""

    key: int
    func: callable
    hint_setter: callable = None
    active: bool = False
    persistent: bool = False
    func_args: int = None


class KeystrokeManager:
    """Register, activate, and dispatch keyboard-driven game events."""

    def __init__(self) -> None:
        """Initialize an empty keystroke registry.

        Returns:
            ``None``.
        """
        self._events = {}
        self._KeystrokeManager__events = self._events

    def addEvent(
        self,
        ident: object,
        key: object,
        func: object,
        hint_setter: object = None,
        active: object = False,
        persistent: object = False,
        func_args: object = None,
    ) -> None:
        """Register a keyboard event under an identifier.

        Args:
            ident: Unique name used to activate or deactivate the event.
            key: Qt key constant that should trigger the event.
            func: Callable to execute when the event fires.
            hint_setter: Optional callable that updates UI hint state when the
                event is activated or deactivated.
            active: Whether the event starts in the active state.
            persistent: Whether the event should remain active after firing.
            func_args: Optional single argument passed to ``func`` when invoked.

        Returns:
            ``None``.
        """
        self._events[ident] = KeystrokeEvent(
            key, func, hint_setter, active, persistent, func_args
        )

    def call(self, key: object) -> None:
        """Dispatch all active events bound to a pressed key.

        Args:
            key: Qt key constant received from input handling.

        Returns:
            ``None``.
        """
        events_to_call = []
        for ident, event in self._events.items():
            if event.active and event.key == key:
                logging.info("Calling %s", ident)
                events_to_call.append(event)
                if not event.persistent:
                    self._deactivate(ident)
        for event in events_to_call:
            if event.func_args is not None:
                event.func(event.func_args)
            else:
                event.func()

    def _activate(self, ident: object) -> None:
        """Activate a registered event and update any associated hint UI.

        Args:
            ident: Identifier of the event to activate.

        Returns:
            ``None``.
        """
        logging.info("Activating %s", ident)
        event = self._events[ident]
        event.active = True
        if event.hint_setter:
            event.hint_setter(True)

    def _deactivate(self, ident: object) -> None:
        """Deactivate a registered event and update any associated hint UI.

        Args:
            ident: Identifier of the event to deactivate.

        Returns:
            ``None``.
        """
        event = self._events[ident]
        event.active = False
        if event.hint_setter:
            event.hint_setter(False)

    def activate(self, *idents: object) -> None:
        """Activate one or more registered events.

        Args:
            *idents: Event identifiers to activate.

        Returns:
            ``None``.
        """
        if isinstance(idents, Iterable):
            for ident in idents:
                self._activate(ident)
        else:
            self._activate(idents)

    def deactivate(self, *idents: object) -> None:
        """Deactivate one or more registered events.

        Args:
            *idents: Event identifiers to deactivate.

        Returns:
            ``None``.
        """
        if isinstance(idents, Iterable):
            for ident in idents:
                self._deactivate(ident)
        else:
            self._deactivate(idents)
