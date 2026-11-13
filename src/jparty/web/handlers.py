"""HTTP and websocket handlers for buzzers, lecterns, and landing pages.

This module contains Tornado request handlers for the join pages and websocket
handlers that maintain live communication with player buzzers and lectern
displays. Together they form the network-facing interface of JParty's web
layer.
"""

from __future__ import annotations

import binascii
import logging
from base64 import urlsafe_b64decode
from typing import TYPE_CHECKING, Any

import tornado.escape
import tornado.web
import tornado.websocket

from jparty.app.config import MAXPLAYERS
from jparty.domain.models import Player

if TYPE_CHECKING:
    from jparty.web.app import Application
    from jparty.web.controller import BuzzerController

SIGNATURE_PREFIX = "data:image/png;base64,"
MAX_NAME_LENGTH = 100
MAX_SIGNATURE_LENGTH = 2_000_000
MAX_ANSWER_LENGTH = 500


def clean_player_name(text: object) -> str | None:
    """Return a phone's name as it should be stored, or ``None`` to reject it.

    The host UI draws the name on the Qt thread. A name that is not a string,
    or a signature whose image data is not valid base64, would raise there,
    so it is rejected here instead.

    Args:
        text: ``text`` field of the phone's ``NAME`` message.

    Returns:
        The name with surrounding spaces removed and text names cut to
        ``MAX_NAME_LENGTH``, or ``None`` if the name is empty, not a string,
        or a bad signature.
    """
    if not isinstance(text, str):
        return None
    name = text.strip()
    if not name:
        return None
    # The host widgets treat anything starting with the prefix (without the
    # comma) as a signature, so check all of those.
    if name.startswith(SIGNATURE_PREFIX[:-1]):
        if len(name) > MAX_SIGNATURE_LENGTH or not name.startswith(SIGNATURE_PREFIX):
            return None
        try:
            # Decode the same way the host widgets do.
            data = urlsafe_b64decode(name[len(SIGNATURE_PREFIX) :])
        except (binascii.Error, ValueError):
            return None
        return name if data else None
    return name[:MAX_NAME_LENGTH]


def clean_final_answer(text: object) -> str | None:
    """Return a phone's Final answer as text, or ``None`` to reject it.

    Args:
        text: ``text`` field of the phone's ``ANSWER`` message.

    Returns:
        The answer cut to ``MAX_ANSWER_LENGTH``, or ``None`` if it is not a
        string.
    """
    if not isinstance(text, str):
        return None
    return text[:MAX_ANSWER_LENGTH]


def parse_wager(text: object) -> int | None:
    """Read a phone's wager as a whole number of dollars.

    The phone's number box accepts forms like ``1e3`` and ``250.5``, so the
    text is read as a float and rounded toward zero. The controller clamps the
    result to what the player may bet.

    Args:
        text: ``text`` field of the phone's ``WAGER`` message.

    Returns:
        The wager, or ``None`` if it is not a finite number.
    """
    if isinstance(text, bool) or not isinstance(text, (str, int, float)):
        return None
    try:
        return int(float(text))
    except (ValueError, OverflowError):
        return None


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
        parsed = tornado.escape.json_decode(message)
        msg = parsed["message"]
        text = parsed["text"]
        if msg == "BUZZ":
            self.buzz()
        elif msg == "NAME":
            self.init_player(text)
        elif msg == "CHECK_IF_EXISTS":
            self.check_if_exists(text)
        elif msg == "CLAIM_PLAYER":
            self.claim_player(text)
        elif msg == "WAGER":
            self.wager(text)
        elif msg == "ANSWER":
            self.answer(text)
        else:
            raise Exception("Unknown message")

    def init_player(self, name: object) -> None:
        """Create and register a player from the submitted display name.

        A socket that already has a player gets that player's token again
        instead of a second player, so a double-tap on "Play!" can't add a
        ghost player. A name that ``clean_player_name`` rejects sends the phone
        back to the name page.

        Args:
            name: Player name provided by the client.

        Returns:
            ``None``.
        """
        if self.player is not None:
            self.send("TOKEN", self.player.token.hex())
            return
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
            self.send("GAMEFULL")
            return
        clean_name = clean_player_name(name)
        if clean_name is None:
            logging.warning("Rejecting invalid player name from a phone")
            self.send("NEW")
            return
        player_index = len(self.controller.connected_players)
        self.player = Player(clean_name, self, player_index)
        self.application.controller.new_player(self.player)
        self.send("TOKEN", self.player.token.hex())

    def claim_player(self, player_number: object) -> None:
        """Claim a saved player profile during resume setup.

        A socket that already has a player is sent that player again, so one
        phone can't claim several saved players.

        Args:
            player_number: Saved player slot requested by the client.

        Returns:
            ``None``.
        """
        if not self.controller.in_saved_player_reclaim_mode():
            self.send("NEW")
            return
        if self.player is not None:
            self.send_claimed(self.player)
            return
        if self.controller.saved_player_claims_complete():
            self.send("ALL_CLAIMED")
            return
        try:
            saved_player_number = int(player_number)
        except (TypeError, ValueError, OverflowError):
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
        self.send_claimed(player)

    def send_claimed(self, player: Player) -> None:
        """Tell the phone which saved player it holds.

        Args:
            player: Saved player claimed by this socket.

        Returns:
            ``None``.
        """
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

    def wager(self, text: object) -> None:
        """Parse and forward a wager from the connected player.

        Args:
            text: String representation of the wager amount.

        Returns:
            ``None``.

        The phone hides its wager box as soon as it sends, so a wager that
        ``parse_wager`` can't read prompts the phone again. Otherwise Final
        would wait for a wager that never comes. The controller checks the
        phase and clamps the amount.
        """
        amount = parse_wager(text)
        if amount is None:
            logging.warning("Ignoring invalid wager %r from %s", text, self.player)
            if self.player is not None and self.player.page == "wager":
                self.controller.open_wagers([self.player])
            return
        self.application.controller.wager(self.player, amount)

    def answer(self, text: object) -> None:
        """Forward a Final answer from the connected player.

        Args:
            text: Answer text from the phone.

        Returns:
            ``None``.

        An answer that is not a string is ignored, since the host could not
        show it for judging.
        """
        guess = clean_final_answer(text)
        if guess is None:
            logging.warning("Ignoring invalid answer from %s", self.player)
            return
        self.application.controller.answer(self.player, guess, self)

    def toolate(self) -> None:
        """Send a too-late notification to this player client.

        Returns:
            ``None``.
        """
        self.send("TOOLATE")

    def on_close(self) -> None:
        """Handle websocket closure for a player client.

        The player is only marked disconnected if this is still their socket.
        An old socket that closes after the phone reconnected leaves the
        player connected.

        Returns:
            ``None``.
        """
        self.controller.unregister_socket(self)
        if self.player is not None and self.player.waiter is self:
            self.player.connected = False
        return None


class LecternHandler(tornado.web.RequestHandler):
    """Serve the lectern display page for a specific player slot."""

    def get(self) -> None:
        """Render the lectern page for the requested player slot.

        The player number is written into a script on the page, so anything
        other than a valid slot number is rejected.

        Returns:
            ``None``.

        Raises:
            tornado.web.HTTPError: 400 when ``player`` is not a valid slot.
        """
        try:
            player_number = int(self.get_argument("player", "0"))
        except ValueError:
            raise tornado.web.HTTPError(400, "Invalid player number") from None
        if not 0 <= player_number < MAXPLAYERS:
            raise tornado.web.HTTPError(400, "Player number out of range")
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
