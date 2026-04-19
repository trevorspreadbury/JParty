"""Logging module."""

import logging
import platform
import sys
import traceback
import webbrowser
from urllib.parse import quote

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from jparty import __version__
from jparty.app.paths import LOG_FILE

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_FILE.touch(exist_ok=True)
logging.basicConfig(
    filename=LOG_FILE, encoding="utf-8", level=logging.DEBUG, filemode="w", force=True
)
log = logging.getLogger(__name__)
log.info("Logging initialized at %s", LOG_FILE)


def mailto(recipients: object, subject: object, body: object) -> None:
    """recipients: string with comma-separated emails (no spaces!)"""
    webbrowser.open(f"mailto:{recipients}?subject={quote(subject)}&body={quote(body)}")


def show_exception_box(log_msg: object) -> None:
    """Check whether a QApplication instance is available and show the exception box.

    If unavailable (non-console application), log an additional notice.
    """
    if QApplication.instance() is not None:
        button = QMessageBox.critical(
            None,
            "Crashed!",
            "It looks like JParty ran into a problem. Do you want to send a report? (I would really appreciate it!)",
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.Yes,
        )
        if button is QMessageBox.StandardButton.Yes:
            with LOG_FILE.open() as f:
                logdata = f.read()
            message = f"JPARTY ERROR REPORT:\n\nVersion: {__version__}\nPlatform: {platform.platform()}\n\n===LOGS===\n\n\n{logdata}\n"
            mailto("me@stuartthomas.us", "JParty Error Report", message)
    else:
        log.debug("No QApplication instance available.")


class UncaughtHook(QObject):
    """Represent uncaughthook."""

    _exception_caught = pyqtSignal(object)

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize the instance."""
        super().__init__(*args, **kwargs)
        sys.excepthook = self.exception_hook
        self._exception_caught.connect(show_exception_box)

    def exception_hook(
        self, exc_type: object, exc_value: object, exc_traceback: object
    ) -> None:
        """Handle uncaught exceptions.

        It is triggered each time an uncaught exception occurs.
        """
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
        else:
            exc_info = (exc_type, exc_value, exc_traceback)
            log_msg = "\n".join(
                [
                    "".join(traceback.format_tb(exc_traceback)),
                    f"{exc_type.__name__}: {exc_value}",
                ]
            )
            log.critical(f"Uncaught exception:\n {log_msg}", exc_info=exc_info)
            self._exception_caught.emit(log_msg)


qt_exception_hook = UncaughtHook()
