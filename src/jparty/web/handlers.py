"""Handlers module."""

import logging

import tornado.escape
import tornado.web
import tornado.websocket

from jparty.app.config import MAXPLAYERS
from jparty.domain.models import Player


class WelcomeHandler(tornado.web.RequestHandler):
    """Represent welcomehandler."""

    def get(self) -> None:
        """Run get."""
        self.render("index.html", messages=BuzzerSocketHandler.cache)


class BuzzerHandler(tornado.web.RequestHandler):
    """Represent buzzerhandler."""

    def post(self) -> None:
        """Run post."""
        if not self.get_cookie("test"):
            self.set_cookie("test", "test_val")
            logging.info("set cookie")
        else:
            logging.info("cookie: %s", self.get_cookie("test"))
        self.render("play.html", messages=BuzzerSocketHandler.cache)


class BuzzerSocketHandler(tornado.websocket.WebSocketHandler):
    """Represent buzzersockethandler."""

    cache = []
    cache_size = 400

    def initialize(self) -> None:
        """Run initialize."""
        self.controller = self.application.controller
        self.player = None

    def get_compression_options(self) -> object:
        """Run get compression options."""
        return {}

    def open(self) -> None:
        """Run open."""
        self.set_nodelay(True)

    def send(self, msg: object, text: object = "") -> None:
        """Run send."""
        data = {"message": msg, "text": text}
        try:
            self.write_message(data)
            logging.info("Sent %s", data)
        except Exception:
            logging.error("Error sending message %s", msg, exc_info=True)

    def check_if_exists(self, token: object) -> None:
        """Run check if exists."""
        player = self.controller.player_with_token(token)
        if player is None:
            self.send("NEW")
            return
        logging.info("Reconnected %s", player)
        self.player = player
        player.connected = True
        player.waiter = self
        self.send("EXISTS", tornado.escape.json_encode(player.state()))

    def on_message(self, message: object) -> None:
        """Run on message."""
        if "BUZZ" in message:
            self.buzz()
            return
        parsed = tornado.escape.json_decode(message)
        msg = parsed["message"]
        text = parsed["text"]
        if msg == "NAME":
            self.init_player(text)
        elif msg == "CHECK_IF_EXISTS":
            self.check_if_exists(text)
        elif msg == "WAGER":
            self.wager(text)
        elif msg == "ANSWER":
            self.application.controller.answer(self.player, text)
        else:
            raise Exception("Unknown message")

    def init_player(self, name: object) -> None:
        """Run init player."""
        if not self.controller.accepting_players:
            self.send("GAMESTARTED")
            return
        if len(self.controller.connected_players) >= MAXPLAYERS:
            self.send("FULL")
            return
        player_index = len(self.controller.connected_players)
        self.player = Player(name, self, player_index)
        self.application.controller.new_player(self.player)
        self.send("TOKEN", self.player.token.hex())

    def buzz(self) -> None:
        """Run buzz."""
        self.application.controller.buzz(self.player)

    def wager(self, text: object) -> None:
        """Run wager."""
        self.application.controller.wager(self.player, int(text))
        self.player.page = "null"

    def toolate(self) -> None:
        """Run toolate."""
        self.send("TOOLATE")

    def on_close(self) -> None:
        """Run on close."""
        return None


class LecternHandler(tornado.web.RequestHandler):
    """Represent lecternhandler."""

    def get(self) -> None:
        """Run get."""
        player_number = self.get_argument("player", "0")
        self.render("lectern.html", player_number=player_number)


class LecternSocketHandler(tornado.websocket.WebSocketHandler):
    """Represent lecternsockethandler."""

    def initialize(self) -> None:
        """Run initialize."""
        self.controller = self.application.controller
        self.player_number = None

    def get_compression_options(self) -> object:
        """Run get compression options."""
        return {}

    def open(self) -> None:
        """Run open."""
        self.set_nodelay(True)
        try:
            self.player_number = int(self.get_argument("player", "0"))
            if self.player_number < 0 or self.player_number >= MAXPLAYERS:
                raise ValueError(f"Player number {self.player_number} out of range")
            self.controller.lectern_connections[self.player_number] = self
            self.send_initial_state()
        except (ValueError, TypeError) as exc:
            logging.error("Invalid player number for lectern: %s", exc)
            self.close()

    def send(self, msg: object, text: object = "") -> None:
        """Run send."""
        data = {"message": msg, "text": text}
        try:
            self.write_message(data)
        except Exception:
            logging.error(
                "Error sending message to lectern %s", self.player_number, exc_info=True
            )

    def send_initial_state(self) -> None:
        """Run send initial state."""
        if self.player_number is None or not self.controller.game:
            return
        player = self.controller.get_player_by_number(self.player_number)
        if player:
            state = self.controller.get_player_state_dict(player)
            self.send("PLAYER_STATE", tornado.escape.json_encode(state))
        else:
            self.send("NO_PLAYER", "")

    def on_message(self, message: object) -> None:
        """Run on message."""
        return None

    def on_close(self) -> None:
        """Run on close."""
        if self.player_number in self.controller.lectern_connections:
            del self.controller.lectern_connections[self.player_number]
