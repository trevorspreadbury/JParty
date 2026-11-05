"""HTTP and websocket handlers for buzzers, lecterns, and landing pages.

This module contains Tornado request handlers for the join pages and websocket
handlers that maintain live communication with player buzzers and lectern
displays. Together they form the network-facing interface of JParty's web
layer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import tornado.escape
import tornado.web
import tornado.websocket

from jparty.app.config import MAXPLAYERS
from jparty.domain.models import Player

if TYPE_CHECKING:
    from jparty.web.app import Application
    from jparty.web.controller import BuzzerController


class WelcomeHandler(tornado.web.RequestHandler):
    """Serve the landing page for clients joining the game."""

    def get(self) -> None:
        """Render the welcome page.

        Returns:
            ``None``.
        """
        self.render("index.html", messages=BuzzerSocketHandler.cache)


class BuzzerHandler(tornado.web.RequestHandler):
    """Serve the player buzzer page after the initial form post."""

    def post(self) -> None:
        """Ensure the test cookie exists and render the buzzer page.

        Returns:
            ``None``.
        """
        if not self.get_cookie("test"):
            self.set_cookie("test", "test_val")
            logging.info("set cookie")
        else:
            logging.info("cookie: %s", self.get_cookie("test"))
        self.render("play.html", messages=BuzzerSocketHandler.cache)


class BuzzerSocketHandler(tornado.websocket.WebSocketHandler):
    """Handle live websocket traffic for player buzzer clients."""

    application: Application
    controller: BuzzerController
    player: Player | None

    cache: list[dict[str, str]] = []
    cache_size = 400

    def initialize(self) -> None:
        """Attach controller references for this websocket connection.

        Returns:
            ``None``.
        """
        self.controller = self.application.controller
        self.player = None

    def get_compression_options(self) -> dict[str, Any]:
        """Enable default websocket compression support.

        Returns:
            Empty dict enabling Tornado's default compression behavior.
        """
        return {}

    def open(self) -> None:
        """Configure the socket immediately after it opens.

        Returns:
            ``None``.
        """
        self.set_nodelay(True)
        self.controller.register_socket(self)

    def send(self, msg: str, text: str = "") -> None:
        """Send a structured websocket message to the player client.

        Args:
            msg: Message type identifier.
            text: Optional message payload text.

        Returns:
            ``None``.
        """
        data = {"message": msg, "text": text}
        try:
            self.write_message(data)
            logging.info("Sent %s", data)
        except Exception:
            logging.error("Error sending message %s", msg, exc_info=True)

    def check_if_exists(self, token: str) -> None:
        """Reconnect a player if the supplied token matches an existing player.

        Args:
            token: Hex-encoded player reconnect token from the client.

        Returns:
            ``None``.
        """
        player = self.controller.player_with_token(token)
        if player is None:
            if self.controller.in_saved_player_reclaim_mode():
                if self.controller.saved_player_claims_complete():
                    self.send("ALL_CLAIMED")
                else:
                    self.send(
                        "SHOW_CHOOSER",
                        tornado.escape.json_encode(
                            self.controller.saved_player_choices_payload()
                        ),
                    )
            else:
                self.send("NEW")
            return
        logging.info("Reconnected %s", player)
        self.player = player
        player.connected = True
        player.waiter = self
        self.send("EXISTS", tornado.escape.json_encode(player.state()))

    def on_message(self, message: str) -> None:
        """Dispatch an inbound websocket message from a player client.

        Args:
            message: Raw websocket message string received from the client.

        Returns:
            ``None``.
        """
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
        elif msg == "CLAIM_PLAYER":
            self.claim_player(text)
        elif msg == "WAGER":
            self.wager(text)
        elif msg == "ANSWER":
            self.application.controller.answer(self.player, text)
        else:
            raise Exception("Unknown message")

    def init_player(self, name: str) -> None:
        """Create and register a player from the submitted display name.

        Args:
            name: Player name provided by the client.

        Returns:
            ``None``.
        """
        if self.controller.in_saved_player_reclaim_mode():
            if self.controller.saved_player_claims_complete():
                self.send("ALL_CLAIMED")
            else:
                self.send(
                    "SHOW_CHOOSER",
                    tornado.escape.json_encode(
                        self.controller.saved_player_choices_payload()
                    ),
                )
            return
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

    def claim_player(self, player_number: str) -> None:
        """Claim a saved player profile during resume setup.

        Args:
            player_number: Saved player slot requested by the client.

        Returns:
            ``None``.
        """
        if not self.controller.in_saved_player_reclaim_mode():
            self.send("NEW")
            return
        if self.controller.saved_player_claims_complete() and self.player is None:
            self.send("ALL_CLAIMED")
            return
        try:
            saved_player_number = int(player_number)
        except (TypeError, ValueError):
            self.send(
                "SHOW_CHOOSER",
                tornado.escape.json_encode(
                    self.controller.saved_player_choices_payload()
                ),
            )
            return
        player = self.controller.claim_saved_player(self, saved_player_number)
        if player is None:
            return
        self.send(
            "CLAIMED",
            tornado.escape.json_encode(
                {"token": player.token.hex(), "state": player.state()}
            ),
        )

    def buzz(self) -> None:
        """Forward a buzz action for the connected player.

        Returns:
            ``None``.
        """
        self.application.controller.buzz(self.player)

    def wager(self, text: str) -> None:
        """Parse and forward a wager from the connected player.

        Args:
            text: String representation of the wager amount.

        Returns:
            ``None``.
        """
        self.application.controller.wager(self.player, int(text))
        self.player.page = "null"

    def toolate(self) -> None:
        """Send a too-late notification to this player client.

        Returns:
            ``None``.
        """
        self.send("TOOLATE")

    def on_close(self) -> None:
        """Handle websocket closure for a player client.

        Returns:
            ``None``.
        """
        self.controller.unregister_socket(self)
        if self.player is not None:
            self.player.connected = False
        return None


class LecternHandler(tornado.web.RequestHandler):
    """Serve the lectern display page for a specific player slot."""

    def get(self) -> None:
        """Render the lectern page for the requested player slot.

        Returns:
            ``None``.
        """
        player_number = self.get_argument("player", "0")
        self.render("lectern.html", player_number=player_number)


class LecternSocketHandler(tornado.websocket.WebSocketHandler):
    """Handle live websocket traffic for host-side lectern displays."""

    application: Application
    controller: BuzzerController
    player_number: int | None

    def initialize(self) -> None:
        """Attach controller references for this lectern websocket.

        Returns:
            ``None``.
        """
        self.controller = self.application.controller
        self.player_number = None

    def get_compression_options(self) -> dict[str, Any]:
        """Enable default websocket compression support.

        Returns:
            Empty dict enabling Tornado's default compression behavior.
        """
        return {}

    def open(self) -> None:
        """Register the lectern connection and send its initial state.

        Returns:
            ``None``.
        """
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

    def send(self, msg: str, text: str = "") -> None:
        """Send a structured websocket message to the lectern client.

        Args:
            msg: Message type identifier.
            text: Optional serialized payload text.

        Returns:
            ``None``.
        """
        data = {"message": msg, "text": text}
        try:
            self.write_message(data)
        except Exception:
            logging.error(
                "Error sending message to lectern %s", self.player_number, exc_info=True
            )

    def send_initial_state(self) -> None:
        """Send the current player-state payload for this lectern slot.

        Returns:
            ``None``.
        """
        if self.player_number is None or not self.controller.game:
            return
        player = self.controller.get_player_by_number(self.player_number)
        if player:
            state = self.controller.get_player_state_dict(player)
            self.send("PLAYER_STATE", tornado.escape.json_encode(state))
        else:
            self.send("NO_PLAYER", "")

    def on_message(self, message: str) -> None:
        """Ignore inbound lectern websocket messages.

        Args:
            message: Raw websocket message string, unused by this handler.

        Returns:
            ``None``.
        """
        return None

    def on_close(self) -> None:
        """Remove the lectern connection from the controller registry.

        Returns:
            ``None``.
        """
        if self.player_number in self.controller.lectern_connections:
            del self.controller.lectern_connections[self.player_number]
