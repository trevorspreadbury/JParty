"""Web server package for JParty's buzzer and lectern interfaces.

The ``jparty.web`` package contains the Tornado application, controller, and
request handlers that expose player buzzer pages and host lectern displays over
the local network.
"""

from .app import Application
from .controller import BuzzerController

__all__ = ["Application", "BuzzerController"]
