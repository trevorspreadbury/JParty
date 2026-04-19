"""Configure logging and present crash reporting prompts.

This module initializes the application's log file, exposes helpers for opening
prefilled error-report emails, and installs a Qt-aware uncaught exception hook
so unexpected crashes can be logged and surfaced to the user gracefully.
"""

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
    """Open the user's mail client with a prefilled message.

    Args:
        recipients: Comma-separated recipient email addresses without spaces.
        subject: Email subject line to URL-encode into the mailto link.
        body: Email body text to URL-encode into the mailto link.

    Returns:
        ``None``.
    """
    webbrowser.open(f"mailto:{recipients}?subject={quote(subject)}&body={quote(body)}")


def show_exception_box(log_msg: object) -> None:
    """Show a crash dialog when a Qt application instance is available.

    Args:
        log_msg: Formatted exception summary string for the crash that was
            logged.

    Returns:
        ``None``.

    If no ``QApplication`` instance is available, the function logs that the
    dialog could not be shown instead of attempting to display it.
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
    """Install a Qt-compatible handler for otherwise uncaught exceptions.

    The hook forwards crash information to the application logger and emits a
    Qt signal so the UI thread can present a crash dialog safely.
    """

    _exception_caught = pyqtSignal(object)

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize the exception hook object and register it globally.

        Args:
            *args: Positional arguments forwarded to ``QObject``.
            **kwargs: Keyword arguments forwarded to ``QObject``.

        Returns:
            ``None``.
        """
        super().__init__(*args, **kwargs)
        sys.excepthook = self.exception_hook
        self._exception_caught.connect(show_exception_box)

    def exception_hook(
        self, exc_type: object, exc_value: object, exc_traceback: object
    ) -> None:
        """Handle uncaught exceptions.

        Args:
            exc_type: Exception class for the uncaught exception.
            exc_value: Exception instance that was raised.
            exc_traceback: Traceback object associated with the exception.

        Returns:
            ``None``.

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
