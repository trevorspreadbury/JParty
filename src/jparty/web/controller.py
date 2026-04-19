"""Controller for the Tornado-based buzzer and lectern server.

This module contains the bridge between the game engine and the web-facing
player interfaces. The controller starts the Tornado server, tracks connected
players and lecterns, and translates websocket events into game actions.
"""

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
    """Manage player, lectern, and websocket interactions for the game."""

    def __init__(self, game: object) -> None:
        """Initialize the buzzer controller and its Tornado application.

        Args:
            game: Active game instance that should receive buzz, wager, and
                answer events.

        Returns:
            ``None``.
        """
        self.thread = None
        self.game = game
        tornado.options.parse_command_line()
        self.app = Application(self)
        self.port = options.port
        self.connected_players = []
        self.accepting_players = True
        self.lectern_connections = {}

    def start(self, threaded: object = True, tries: object = 0) -> None:
        """Start the Tornado server, retrying with higher ports if needed.

        Args:
            threaded: Whether to start Tornado on a background thread.
            tries: Current retry count while searching for an open port.

        Returns:
            ``None``.

        Raises:
            Exception: If no open port can be found within the configured retry
                limit.
        """
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
        """Disconnect all players and reset lobby acceptance state.

        Returns:
            ``None``.
        """
        for p in self.connected_players:
            p.waiter.close()
        self.connected_players = []
        self.accepting_players = True

    def buzz(self, player: object) -> None:
        """Forward a player's buzz event into the game engine.

        Args:
            player: Player object that initiated the buzz.

        Returns:
            ``None``.
        """
        if self.game:
            i_player = self.game.players.index(player)
            self.game.buzz_trigger.emit(i_player)
        else:
            i_player = self.connected_players.index(player)
            self.game.buzz_hint_trigger.emit(i_player)

    def wager(self, player: object, amount: object) -> None:
        """Forward a player's Final Jeopardy wager into the game engine.

        Args:
            player: Player object submitting the wager.
            amount: Numeric wager amount from the client.

        Returns:
            ``None``.
        """
        i_player = self.game.players.index(player)
        self.game.wager_trigger.emit(i_player, amount)

    def answer(self, player: object, guess: object) -> None:
        """Forward a player's Final Jeopardy response into the game engine.

        Args:
            player: Player object submitting the response.
            guess: Final response text from the client.

        Returns:
            ``None``.
        """
        if self.game:
            self.game.answer(player, guess)
            player.page = "null"

    def new_player(self, player: object) -> None:
        """Register a newly connected player and notify the game.

        Args:
            player: Player object created for the new connection.

        Returns:
            ``None``.
        """
        self.connected_players.append(player)
        self.game.new_player_trigger.emit()

    @classmethod
    def localip(cls) -> object:
        """Return the machine's outward-facing local IP address.

        Returns:
            String IP address used by clients on the local network.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", options.port))
        return s.getsockname()[0]

    def host(self) -> str:
        """Return the host string clients should use to connect.

        Returns:
            Hostname string including the port when it is non-default.
        """
        localip = BuzzerController.localip()
        if self.port == DEFAULT_HTTP_PORT:
            return f"{localip}"
        else:
            return f"{localip}:{self.port}"

    def player_with_token(self, token: object) -> object:
        """Look up a connected player by their reconnect token.

        Args:
            token: Hex-encoded player token received from the client.

        Returns:
            Matching player object, or ``None`` if no player matches.
        """
        for p in self.connected_players:
            logging.info(f"{p.token}, {token}")
            if p.token.hex() == token:
                logging.info("MATCH")
                return p
        return None

    def open_wagers(self, players: object = None) -> None:
        """Prompt one or more players to enter Final Jeopardy wagers.

        Args:
            players: Optional iterable of players to prompt. When omitted, all
                connected players are prompted.

        Returns:
            ``None``.
        """
        if players is None:
            players = self.connected_players
        for p in players:
            p.waiter.send("PROMPTWAGER", str(max(p.score, 0)))
            p.page = "wager"

    def prompt_answers(self) -> None:
        """Prompt all connected players to enter Final Jeopardy answers.

        Returns:
            ``None``.
        """
        for p in self.connected_players:
            p.waiter.send("PROMPTANSWER")
            p.page = "answer"

    def toolate(self) -> None:
        """Notify all connected players that the response window has closed.

        Returns:
            ``None``.
        """
        for p in self.connected_players:
            p.waiter.send("TOOLATE")

    def get_player_by_number(self, player_number: object) -> object:
        """Return the current game player assigned to a lectern slot.

        Args:
            player_number: Zero-based player slot number.

        Returns:
            Matching player object, or ``None`` when the slot is empty.
        """
        if self.game and player_number < len(self.game.players):
            return self.game.players[player_number]
        return None

    def get_player_state_dict(self, player: object) -> object:
        """Build the serialized lectern state for a player.

        Args:
            player: Player object whose state should be exposed.

        Returns:
            Dictionary containing the player's lectern-facing state fields.
        """
        return {
            "name": player.name,
            "score": player.score,
            "player_number": player.player_number,
            "active": False,
            "buzzed": False,
            "finalanswer": getattr(player, "finalanswer", None),
        }

    def broadcast_to_lecterns(self, player_number: object, state_dict: object) -> None:
        """Send an updated state payload to a specific lectern connection.

        Args:
            player_number: Zero-based lectern slot number to update.
            state_dict: Serialized player state to send.

        Returns:
            ``None``.
        """
        if player_number in self.lectern_connections:
            lectern = self.lectern_connections[player_number]
            try:
                lectern.send("PLAYER_STATE", tornado.escape.json_encode(state_dict))
            except Exception:
                logging.error(
                    f"Error broadcasting to lectern {player_number}", exc_info=True
                )
