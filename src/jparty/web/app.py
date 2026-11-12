"""Tornado application wiring for buzzer and lectern web endpoints.

This module defines the top-level Tornado ``Application`` used by JParty's web
layer. It registers the HTTP and websocket routes that power player buzzers,
host-facing lecterns, and the landing page served to connected devices.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import tornado.web

from jparty.app.paths import web_asset_path
from jparty.web.handlers import (
    BuzzerHandler,
    BuzzerSocketHandler,
    LecternHandler,
    LecternSocketHandler,
    WelcomeHandler,
)

if TYPE_CHECKING:
    from jparty.web.controller import BuzzerController

WEBSOCKET_PING_INTERVAL_SECONDS = 0.19


class Application(tornado.web.Application):
    """Configure the Tornado app used by the buzzer web server."""

    controller: BuzzerController

    def __init__(self, controller: BuzzerController) -> None:
        """Initialize the Tornado application and route table.

        Args:
            controller: ``BuzzerController`` instance shared with all request
                and websocket handlers.

        Returns:
            ``None``.
        """
        handlers = [
            ("/", WelcomeHandler),
            ("/play", BuzzerHandler),
            ("/buzzersocket", BuzzerSocketHandler),
            ("/lectern", LecternHandler),
            ("/lecternsocket", LecternSocketHandler),
        ]
        settings = {
            "cookie_secret": "",
            "template_path": str(web_asset_path("templates")),
            "static_path": str(web_asset_path("static")),
            "xsrf_cookies": False,
            # Frequent pings keep phones' Wi-Fi awake so buzzes arrive quickly.
            "websocket_ping_interval": WEBSOCKET_PING_INTERVAL_SECONDS,
            # Never drop a phone for a late pong. Tornado 6.5+ defaults the
            # timeout to the interval (190 ms), which closed phone sockets on
            # ordinary Wi-Fi lag and made the buzzer page reload in a loop.
            "websocket_ping_timeout": 0,
        }
        super().__init__(handlers, **settings)
        self.controller = controller
