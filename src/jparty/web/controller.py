import logging
import tornado.ioloop
from tornado.options import define, options

import socket
from threading import Thread

import tornado.escape

from jparty.app.config import PORT
from jparty.web.app import Application


define("port", default=PORT, help="run on the given port", type=int)


class BuzzerController:
    def __init__(self, game):
        self.thread = None
        self.game = game
        tornado.options.parse_command_line()
        self.app = Application(
            self
        )  # this is to remove sleep mode on Macbook network card
        self.port = options.port
        self.connected_players = []
        self.accepting_players = True
        self.lectern_connections = {}

    def start(self, threaded=True, tries=0):
        try:
            self.app.listen(self.port)
        except OSError as e:
            if tries>10:
                raise Exception("Cannot find open port")
            self.port += 1
            self.start(threaded, tries+1)
            return

        if threaded:
            self.thread = Thread(target=tornado.ioloop.IOLoop.current().start)
            self.thread.setDaemon(True)
            self.thread.start()
        else:
            tornado.ioloop.IOLoop.current().start()

    def restart(self):
        for p in self.connected_players:
            p.waiter.close()
        self.connected_players = []
        self.accepting_players = True

    def buzz(self, player):
        if self.game:
            i_player = self.game.players.index(player)
            self.game.buzz_trigger.emit(i_player)
        else:
            i_player = self.connected_players.index(player)
            self.game.buzz_hint_trigger.emit(i_player)

    def wager(self, player, amount):
        i_player = self.game.players.index(player)
        self.game.wager_trigger.emit(i_player, amount)

    def answer(self, player, guess):
        if self.game:
            self.game.answer(player, guess)
            player.page = "null"

    def new_player(self, player):
        self.connected_players.append(player)
        self.game.new_player_trigger.emit()

    @classmethod
    def localip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", options.port))
        return s.getsockname()[0]

    def host(self):
        localip = BuzzerController.localip()
        if self.port == 80:
            return f"{localip}"
        else:
            return f"{localip}:{self.port}"

    def player_with_token(self, token):
        for p in self.connected_players:
            logging.info(f"{p.token}, {token}")
            if p.token.hex() == token:
                logging.info("MATCH")
                return p
        return None

    def open_wagers(self, players=None):
        if players is None:
            players = self.connected_players

        for p in players:
            p.waiter.send("PROMPTWAGER", str(max(p.score, 0)))
            p.page = "wager"

    def prompt_answers(self):
        for p in self.connected_players:
            p.waiter.send("PROMPTANSWER")
            p.page = "answer"

    def toolate(self):
        for p in self.connected_players:
            p.waiter.send("TOOLATE")

    def get_player_by_number(self, player_number):
        if self.game and player_number < len(self.game.players):
            return self.game.players[player_number]
        return None

    def get_player_state_dict(self, player):
        return {
            "name": player.name,
            "score": player.score,
            "player_number": player.player_number,
            "active": False,
            "buzzed": False,
            "finalanswer": getattr(player, 'finalanswer', None),
        }

    def broadcast_to_lecterns(self, player_number, state_dict):
        if player_number in self.lectern_connections:
            lectern = self.lectern_connections[player_number]
            try:
                lectern.send("PLAYER_STATE", tornado.escape.json_encode(state_dict))
            except:
                logging.error(f"Error broadcasting to lectern {player_number}", exc_info=True)
