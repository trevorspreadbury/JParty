"""Controller for the Tornado-based buzzer and lectern server.

This module contains the bridge between the game engine and the web-facing
player interfaces. The controller starts the Tornado server, tracks connected
players and lecterns, and translates websocket events into game actions.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from threading import Thread
from typing import TYPE_CHECKING, TypedDict

import tornado.escape
import tornado.ioloop
from tornado.options import define, options

from jparty.app.config import PORT
from jparty.domain.models import Player
from jparty.web.app import Application

if TYPE_CHECKING:
    from jparty.domain.game_engine import Game
    from jparty.web.handlers import BuzzerSocketHandler, LecternSocketHandler

define("port", default=PORT, help="run on the given port", type=int)

MAX_PORT_TRIES = 10
DEFAULT_HTTP_PORT = 80


class PlayerStateDict(TypedDict):
    """Typed payload describing lectern-visible player state."""

    name: str
    score: int
    player_number: int
    active: bool
    buzzed: bool
    finalanswer: str | None


class SavedPlayerChoiceDict(TypedDict):
    """Typed payload describing one reclaimable saved-player profile."""

    name: str
    player_number: int
    claimed: bool


class SavedPlayerChoicesPayload(TypedDict):
    """Typed payload sent to phones when choosing a saved player."""

    players: list[SavedPlayerChoiceDict]
    claimed_count: int
    total_count: int


@dataclass
class SavedPlayerProfile:
    """Represent one saved player profile that can be reclaimed."""

    name: str
    player_number: int
    claimed_token: str | None = None
    player: Player | None = None


class BuzzerController:
    """Manage player, lectern, and websocket interactions for the game."""

    thread: Thread | None
    game: Game
    app: Application
    port: int
    connected_players: list[Player]
    accepting_players: bool
    lectern_connections: dict[int, LecternSocketHandler]
    active_buzzer_sockets: set[BuzzerSocketHandler]
    saved_player_profiles: dict[int, SavedPlayerProfile]
    resume_mode_active: bool

    def __init__(self, game: Game) -> None:
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
        self.active_buzzer_sockets = set()
        self.saved_player_profiles = {}
        self.resume_mode_active = False

    def start(self, threaded: bool = True, tries: int = 0) -> None:
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
            if p.waiter is not None:
                p.waiter.close()
        self.connected_players = []
        self.accepting_players = True
        self.clear_saved_player_reclaim()

    def register_socket(self, socket_handler: BuzzerSocketHandler) -> None:
        """Track an open player websocket connection.

        Args:
            socket_handler: Buzzer websocket handler for the new connection.

        Returns:
            ``None``.
        """
        self.active_buzzer_sockets.add(socket_handler)

    def unregister_socket(self, socket_handler: BuzzerSocketHandler) -> None:
        """Stop tracking a player websocket connection.

        Args:
            socket_handler: Buzzer websocket handler being removed.

        Returns:
            ``None``.
        """
        self.active_buzzer_sockets.discard(socket_handler)

    def clear_saved_player_reclaim(self) -> None:
        """Discard saved-game reclaim state and chooser metadata.

        Returns:
            ``None``.
        """
        self.saved_player_profiles = {}
        self.resume_mode_active = False

    def in_saved_player_reclaim_mode(self) -> bool:
        """Return whether the lobby is currently reclaiming saved players.

        Returns:
            ``True`` when a saved-game chooser is active.
        """
        return self.resume_mode_active

    def saved_player_claim_count(self) -> int:
        """Return the number of saved profiles that have been claimed.

        Returns:
            Count of claimed saved-player profiles.
        """
        return sum(
            1
            for profile in self.saved_player_profiles.values()
            if profile.player is not None
        )

    def saved_player_total_count(self) -> int:
        """Return the number of saved profiles available to claim.

        Returns:
            Count of reclaimable saved-player profiles.
        """
        return len(self.saved_player_profiles)

    def saved_player_claims_complete(self) -> bool:
        """Return whether every saved profile has been claimed.

        Returns:
            ``True`` when all saved profiles have active claimed players.
        """
        return bool(self.saved_player_profiles) and (
            self.saved_player_claim_count() == self.saved_player_total_count()
        )

    def saved_player_choices_payload(self) -> SavedPlayerChoicesPayload:
        """Build the chooser payload for saved-player reclaim mode.

        Returns:
            Typed payload listing saved players and claim progress.
        """
        players = [
            {
                "name": profile.name,
                "player_number": profile.player_number,
                "claimed": profile.player is not None,
            }
            for profile in sorted(
                self.saved_player_profiles.values(),
                key=lambda profile: profile.player_number,
            )
        ]
        return {
            "players": players,
            "claimed_count": self.saved_player_claim_count(),
            "total_count": self.saved_player_total_count(),
        }

    def push_saved_player_choices(self) -> None:
        """Send the latest saved-player chooser state to open unclaimed phones.

        Returns:
            ``None``.
        """
        if not self.in_saved_player_reclaim_mode():
            return
        payload = tornado.escape.json_encode(self.saved_player_choices_payload())
        for socket_handler in list(self.active_buzzer_sockets):
            if socket_handler.player is None:
                socket_handler.send("SHOW_CHOOSER", payload)

    def begin_saved_player_reclaim(
        self, saved_players: Iterable[dict[str, object]]
    ) -> None:
        """Switch the lobby into saved-player reclaim mode.

        Args:
            saved_players: Serialized player entries loaded from ``general.json``.

        Returns:
            ``None``.
        """
        self.saved_player_profiles = {}
        for saved_player in saved_players:
            try:
                player_number = int(saved_player["player_number"])
                name = str(saved_player["name"])
            except (KeyError, TypeError, ValueError):
                continue
            self.saved_player_profiles[player_number] = SavedPlayerProfile(
                name=name, player_number=player_number
            )
        self.resume_mode_active = bool(self.saved_player_profiles)
        current_sockets = list(self.active_buzzer_sockets)
        self.connected_players = []
        self.game.new_player_trigger.emit()
        if not self.resume_mode_active:
            return
        if len(current_sockets) > self.saved_player_total_count():
            for socket_handler in current_sockets:
                socket_handler.send("LOGOUT", "Saved game loaded. Please reconnect.")
                socket_handler.close()
            return
        payload = tornado.escape.json_encode(self.saved_player_choices_payload())
        for socket_handler in current_sockets:
            socket_handler.player = None
            socket_handler.send("LOGOUT", "")
            socket_handler.send("SHOW_CHOOSER", payload)

    def claim_saved_player(
        self, socket_handler: BuzzerSocketHandler, player_number: int
    ) -> Player | None:
        """Claim one saved-player profile for a phone in resume mode.

        Args:
            socket_handler: Socket requesting the claim.
            player_number: Saved player slot being claimed.

        Returns:
            Claimed player object, or ``None`` when the claim is invalid.
        """
        if not self.in_saved_player_reclaim_mode():
            return None
        profile = self.saved_player_profiles.get(player_number)
        if profile is None:
            socket_handler.send(
                "SHOW_CHOOSER",
                tornado.escape.json_encode(self.saved_player_choices_payload()),
            )
            return None
        if profile.player is not None and profile.player.waiter is not socket_handler:
            socket_handler.send("PLAYER_TAKEN")
            socket_handler.send(
                "SHOW_CHOOSER",
                tornado.escape.json_encode(self.saved_player_choices_payload()),
            )
            return None
        if profile.player is None:
            player = Player(profile.name, socket_handler, profile.player_number)
            profile.player = player
            profile.claimed_token = player.token.hex()
            self.connected_players.append(player)
        else:
            player = profile.player
            player.waiter = socket_handler
            player.connected = True
        socket_handler.player = player
        player.page = "buzz"
        self.connected_players.sort(
            key=lambda current_player: current_player.player_number
        )
        self.game.new_player_trigger.emit()
        self.push_saved_player_choices()
        return player

    def player_with_saved_token(self, token: str) -> Player | None:
        """Look up a claimed saved player by reconnect token.

        Args:
            token: Hex-encoded reconnect token from the client cookie.

        Returns:
            Matching claimed saved player, or ``None``.
        """
        for profile in self.saved_player_profiles.values():
            if profile.claimed_token == token:
                return profile.player
        return None

    def claimed_saved_players(self) -> list[Player]:
        """Return claimed saved players ordered by their saved slot.

        Returns:
            Claimed player objects in saved ``player_number`` order.
        """
        return [
            profile.player
            for profile in sorted(
                self.saved_player_profiles.values(),
                key=lambda profile: profile.player_number,
            )
            if profile.player is not None
        ]

    def buzz(self, player: Player) -> None:
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

    def wager(self, player: Player, amount: int) -> None:
        """Forward a player's Final Jeopardy wager into the game engine.

        Args:
            player: Player object submitting the wager.
            amount: Numeric wager amount from the client.

        Returns:
            ``None``.
        """
        i_player = self.game.players.index(player)
        self.game.wager_trigger.emit(i_player, amount)

    def answer(self, player: Player, guess: str) -> None:
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

    def new_player(self, player: Player) -> None:
        """Register a newly connected player and notify the game.

        Args:
            player: Player object created for the new connection.

        Returns:
            ``None``.
        """
        self.connected_players.append(player)
        self.game.new_player_trigger.emit()

    @classmethod
    def localip(cls) -> str:
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

    def player_with_token(self, token: str) -> Player | None:
        """Look up a connected player by their reconnect token.

        Args:
            token: Hex-encoded player token received from the client.

        Returns:
            Matching player object, or ``None`` if no player matches.
        """
        player = self.player_with_saved_token(token)
        if player is not None:
            return player
        for p in self.connected_players:
            logging.info(f"{p.token}, {token}")
            if p.token.hex() == token:
                logging.info("MATCH")
                return p
        return None

    def open_wagers(self, players: Iterable[Player] | None = None) -> None:
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

    def get_player_by_number(self, player_number: int) -> Player | None:
        """Return the current game player assigned to a lectern slot.

        Args:
            player_number: Zero-based player slot number.

        Returns:
            Matching player object, or ``None`` when the slot is empty.
        """
        if self.game and player_number < len(self.game.players):
            return self.game.players[player_number]
        return None

    def get_player_state_dict(self, player: Player) -> PlayerStateDict:
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

    def broadcast_to_lecterns(
        self, player_number: int, state_dict: PlayerStateDict
    ) -> None:
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
