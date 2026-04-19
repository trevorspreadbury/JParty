"""Controller module."""

import logging
import socket
from threading import Thread

import tornado.escape
import tornado.ioloop
from tornado.options import define, options

from jparty.app.config import PORT
from jparty.web.app import Application

define("port", default=PORT, help="run on the given port", type=int)

MAX_PORT_TRIES = 10
DEFAULT_HTTP_PORT = 80


class BuzzerController:
    """Represent buzzercontroller."""

    def __init__(self, game: object) -> None:
        """Initialize the instance."""
        self.thread = None
        self.game = game
        tornado.options.parse_command_line()
        self.app = Application(self)
        self.port = options.port
        self.connected_players = []
        self.accepting_players = True
        self.lectern_connections = {}

    def start(self, threaded: object = True, tries: object = 0) -> None:
        """Run start."""
        try:
            self.app.listen(self.port)
        except OSError as err:
            if tries > MAX_PORT_TRIES:
                raise Exception("Cannot find open port") from err
            self.port += 1
            self.start(threaded, tries + 1)
            return
        if threaded:
            self.thread = Thread(target=tornado.ioloop.IOLoop.current().start)
            self.thread.setDaemon(True)
            self.thread.start()
        else:
            tornado.ioloop.IOLoop.current().start()

    def restart(self) -> None:
        """Run restart."""
        for p in self.connected_players:
            p.waiter.close()
        self.connected_players = []
        self.accepting_players = True

    def buzz(self, player: object) -> None:
        """Run buzz."""
        if self.game:
            i_player = self.game.players.index(player)
            self.game.buzz_trigger.emit(i_player)
        else:
            i_player = self.connected_players.index(player)
            self.game.buzz_hint_trigger.emit(i_player)

    def wager(self, player: object, amount: object) -> None:
        """Run wager."""
        i_player = self.game.players.index(player)
        self.game.wager_trigger.emit(i_player, amount)

    def answer(self, player: object, guess: object) -> None:
        """Run answer."""
        if self.game:
            self.game.answer(player, guess)
            player.page = "null"

    def new_player(self, player: object) -> None:
        """Run new player."""
        self.connected_players.append(player)
        self.game.new_player_trigger.emit()

    @classmethod
    def localip(cls) -> object:
        """Run localip."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", options.port))
        return s.getsockname()[0]

    def host(self) -> str:
        """Run host."""
        localip = BuzzerController.localip()
        if self.port == DEFAULT_HTTP_PORT:
            return f"{localip}"
        else:
            return f"{localip}:{self.port}"

    def player_with_token(self, token: object) -> object:
        """Run player with token."""
        for p in self.connected_players:
            logging.info(f"{p.token}, {token}")
            if p.token.hex() == token:
                logging.info("MATCH")
                return p
        return None

    def open_wagers(self, players: object = None) -> None:
        """Run open wagers."""
        if players is None:
            players = self.connected_players
        for p in players:
            p.waiter.send("PROMPTWAGER", str(max(p.score, 0)))
            p.page = "wager"

    def prompt_answers(self) -> None:
        """Run prompt answers."""
        for p in self.connected_players:
            p.waiter.send("PROMPTANSWER")
            p.page = "answer"

    def toolate(self) -> None:
        """Run toolate."""
        for p in self.connected_players:
            p.waiter.send("TOOLATE")

    def get_player_by_number(self, player_number: object) -> object:
        """Run get player by number."""
        if self.game and player_number < len(self.game.players):
            return self.game.players[player_number]
        return None

    def get_player_state_dict(self, player: object) -> object:
        """Run get player state dict."""
        return {
            "name": player.name,
            "score": player.score,
            "player_number": player.player_number,
            "active": False,
            "buzzed": False,
            "finalanswer": getattr(player, "finalanswer", None),
        }

    def broadcast_to_lecterns(self, player_number: object, state_dict: object) -> None:
        """Run broadcast to lecterns."""
        if player_number in self.lectern_connections:
            lectern = self.lectern_connections[player_number]
            try:
                lectern.send("PLAYER_STATE", tornado.escape.json_encode(state_dict))
            except Exception:
                logging.error(
                    f"Error broadcasting to lectern {player_number}", exc_info=True
                )
