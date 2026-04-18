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
    def __init__(self, controller):
        handlers = [
            (r"/", WelcomeHandler),
            (r"/play", BuzzerHandler),
            (r"/buzzersocket", BuzzerSocketHandler),
            (r"/lectern", LecternHandler),
            (r"/lecternsocket", LecternSocketHandler),
        ]
        settings = dict(
            cookie_secret="",
            template_path=str(web_asset_path("templates")),
            static_path=str(web_asset_path("static")),
            xsrf_cookies=False,
            websocket_ping_interval=0.19,
        )
        super().__init__(handlers, **settings)
        self.controller = controller
