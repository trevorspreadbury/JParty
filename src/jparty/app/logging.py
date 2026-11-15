"""Configure logging and present crash dialogs.

This module exposes ``install_crash_reporting``, which initializes the
application's log file and installs Qt-aware uncaught exception hooks for the
main thread and worker threads, so unexpected crashes are logged and surfaced
to the user gracefully. The previous launch's log is kept next to the current
one so a hard crash still leaves evidence behind.
"""

import logging
import sys
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from jparty.app.paths import LOG_FILE

log = logging.getLogger(__name__)
_installed_hook = None


def previous_log_path(log_file: Path) -> Path:
    """Return where the previous launch's log is kept.

    Args:
        log_file: Path of the current log file, e.g. ``latest.log``.

    Returns:
        The sibling path with ``.1`` appended, e.g. ``latest.log.1``.
    """
    return log_file.with_name(log_file.name + ".1")


def rotate_log_file(log_file: Path) -> bool:
    """Move the existing log aside so this launch starts a fresh one.

    Only one previous log is kept; an older ``.1`` file is replaced.

    Args:
        log_file: Path of the current log file.

    Returns:
        ``True`` if the log was rotated (or there was nothing to rotate),
        ``False`` if the old log could not be moved, for example because
        another running JParty still has it open on Windows.
    """
    if not log_file.exists() or log_file.stat().st_size == 0:
        return True
    try:
        log_file.replace(previous_log_path(log_file))
    except OSError:
        return False
    return True


def show_exception_box(log_msg: object) -> None:
    """Show a crash dialog when a Qt application instance is available.

    Args:
        log_msg: Formatted exception summary string for the crash that was
            logged. The last line (the exception itself) is shown to the user.

    Returns:
        ``None``.

    If no ``QApplication`` instance is available, the function logs that the
    dialog could not be shown instead of attempting to display it.
    """
    if QApplication.instance() is not None:
        summary = str(log_msg).strip().splitlines()[-1:] or [""]
        QMessageBox.critical(
            None,
            "Crashed!",
            "It looks like JParty ran into a problem.\n\n"
            f"{summary[0]}\n\n"
            f"Details were written to the log file:\n{LOG_FILE}",
        )
    else:
        log.debug("No QApplication instance available.")


class UncaughtHook(QObject):
    """Install a Qt-compatible handler for otherwise uncaught exceptions.

    The hook forwards crash information to the application logger and emits a
    Qt signal so the UI thread can present a crash dialog safely. It covers
    both the main thread (``sys.excepthook``) and worker threads
    (``threading.excepthook``); a signal emitted from a worker thread is
    queued onto the UI thread by Qt.
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
        threading.excepthook = self.thread_exception_hook
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

    def thread_exception_hook(self, args: threading.ExceptHookArgs) -> None:
        """Handle an exception that escaped a ``threading.Thread``.

        Args:
            args: Exception details supplied by ``threading.excepthook``.

        Returns:
            ``None``.
        """
        if args.exc_type is SystemExit:
            return
        thread_name = args.thread.name if args.thread is not None else "unknown"
        log.error("Uncaught exception in thread %s", thread_name)
        self.exception_hook(args.exc_type, args.exc_value, args.exc_traceback)


def install_crash_reporting() -> "UncaughtHook":
    """Initialize the log file and install the uncaught exception hook.

    This must be called explicitly at GUI startup. Without the hook, PyQt6
    aborts the process on any unhandled exception raised in a slot or event
    handler, closing the app with no dialog and no log.

    Returns:
        The installed ``UncaughtHook``. Repeated calls return the same hook.
    """
    global _installed_hook
    if _installed_hook is not None:
        return _installed_hook
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    rotated = rotate_log_file(LOG_FILE)
    # Append rather than truncate: if rotation failed, the old log survives.
    logging.basicConfig(
        filename=LOG_FILE,
        encoding="utf-8",
        level=logging.DEBUG,
        filemode="a",
        force=True,
    )
    log.info("Logging initialized at %s", LOG_FILE)
    if not rotated:
        log.warning("Could not move the previous log aside; appending to it")
    _installed_hook = UncaughtHook()
    return _installed_hook
