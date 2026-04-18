import os
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


def mailto(recipients, subject, body):
    "recipients: string with comma-separated emails (no spaces!)"
    webbrowser.open(
        "mailto:{}?subject={}&body={}".format(recipients, quote(subject), quote(body))
    )


def show_exception_box(log_msg):
    """Checks if a QApplication instance is available and shows a messagebox with the exception message.
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
            with open(LOG_FILE, "r") as f:
                logdata = f.read()
            message = f"""JPARTY ERROR REPORT:

Version: {__version__}
Platform: {platform.platform()}

===LOGS===


{logdata}
"""

            mailto("me@stuartthomas.us", "JParty Error Report", message)
    else:
        log.debug("No QApplication instance available.")


class UncaughtHook(QObject):
    _exception_caught = pyqtSignal(object)

    def __init__(self, *args, **kwargs):
        super(UncaughtHook, self).__init__(*args, **kwargs)

        # this registers the exception_hook() function as hook with the Python interpreter
        sys.excepthook = self.exception_hook

        # connect signal to execute the message box function always on main thread
        self._exception_caught.connect(show_exception_box)

    def exception_hook(self, exc_type, exc_value, exc_traceback):
        """Function handling uncaught exceptions.
        It is triggered each time an uncaught exception occurs.
        """
        if issubclass(exc_type, KeyboardInterrupt):
            # ignore keyboard interrupt to support console applications
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
        else:
            exc_info = (exc_type, exc_value, exc_traceback)
            log_msg = "\n".join(
                [
                    "".join(traceback.format_tb(exc_traceback)),
                    "{0}: {1}".format(exc_type.__name__, exc_value),
                ]
            )
            log.critical("Uncaught exception:\n {0}".format(log_msg), exc_info=exc_info)

            # trigger message box show
            self._exception_caught.emit(log_msg)


# create a global instance of our class to register the hook
qt_exception_hook = UncaughtHook()
