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
    def __init__(self, interval, callback, *args, **kwargs):
        self.callback = callback
        self.args = args
        self.kwargs = kwargs
        self.interval = interval
        self._thread = None
        self._start_time = None
        self._elapsed_time = 0

    def run(self, interval):
        thread = self._thread
        time.sleep(interval)
        if thread == self._thread:
            self.callback(*self.args, **self.kwargs)

    def start(self):
        self.resume()

    def cancel(self):
        self.pause()

    def pause(self):
        self._thread = None
        self._elapsed_time += time.time() - self._start_time

    def resume(self):
        self._thread = threading.Thread(
            target=self.run,
            args=(self.interval - self._elapsed_time,),
        )
        self._thread.start()
        self._start_time = time.time()


@dataclass
class KeystrokeEvent:
    key: int
    func: callable
    hint_setter: callable = None
    active: bool = False
    persistent: bool = False
    func_args: int = None


class KeystrokeManager:
    def __init__(self):
        self._events = {}
        self._KeystrokeManager__events = self._events

    def addEvent(
        self,
        ident,
        key,
        func,
        hint_setter=None,
        active=False,
        persistent=False,
        func_args=None,
    ):
        self._events[ident] = KeystrokeEvent(
            key,
            func,
            hint_setter,
            active,
            persistent,
            func_args,
        )

    def call(self, key):
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

    def _activate(self, ident):
        logging.info("Activating %s", ident)
        event = self._events[ident]
        event.active = True
        if event.hint_setter:
            event.hint_setter(True)

    def _deactivate(self, ident):
        event = self._events[ident]
        event.active = False
        if event.hint_setter:
            event.hint_setter(False)

    def activate(self, *idents):
        if isinstance(idents, Iterable):
            for ident in idents:
                self._activate(ident)
        else:
            self._activate(idents)

    def deactivate(self, *idents):
        if isinstance(idents, Iterable):
            for ident in idents:
                self._deactivate(ident)
        else:
            self._deactivate(idents)
