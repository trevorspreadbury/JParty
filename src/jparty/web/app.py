"""App module."""

import tornado.web

from jparty.app.paths import web_asset_path
from jparty.web.handlers import (
    BuzzerHandler,
    BuzzerSocketHandler,
    LecternHandler,
    LecternSocketHandler,
    WelcomeHandler,
)


class Application(tornado.web.Application):
    """Represent application."""

    def __init__(self, controller: object) -> None:
        """Initialize the instance."""
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
            "websocket_ping_interval": 0.19,
        }
        super().__init__(handlers, **settings)
        self.controller = controller
