"""Controller for the Tornado-based buzzer and lectern server.

This module contains the bridge between the game engine and the web-facing
player interfaces. The controller starts the Tornado server, tracks connected
players and lecterns, and translates websocket events into game actions.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Thread
from typing import TYPE_CHECKING, TypedDict

import tornado.escape
import tornado.ioloop

from jparty.app.config import PORT
from jparty.domain.input import index_to_key
from jparty.domain.models import Player
from jparty.web.app import Application

if TYPE_CHECKING:
    from jparty.domain.game_engine import Game
    from jparty.web.handlers import BuzzerSocketHandler, LecternSocketHandler

MAX_PORT_TRIES = 10
DEFAULT_HTTP_PORT = 80
# Seconds after ``TOOLATE`` during which a phone may resubmit its answer box.
# Phones reply at once, so this only needs to cover a slow local network.
LATE_ANSWER_GRACE_SECONDS = 3.0


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
    """Represent one saved player profile that can be reclaimed.

    ``player_number`` is the number the player was saved under; it identifies
    the profile in the saved history. The claimed ``player`` may sit in a
    different seat (see ``BuzzerController.seat_order``).
    """

    name: str
    player_number: int
    claimed_token: str | None = None
    player: Player | None = None


class BuzzerController:
    """Manage player, lectern, and websocket interactions for the game."""

    thread: Thread | None
    loop: tornado.ioloop.IOLoop | None
    game: Game
    app: Application
    port: int
    connected_players: list[Player]
    accepting_players: bool
    lectern_connections: dict[int, LecternSocketHandler]
    active_buzzer_sockets: set[BuzzerSocketHandler]
    saved_player_profiles: dict[int, SavedPlayerProfile]
    seat_order: list[int]
    resume_mode_active: bool
    late_answer_players: dict[Player, BuzzerSocketHandler]
    late_answer_deadline: float

    def __init__(self, game: Game) -> None:
        """Initialize the buzzer controller and its Tornado application.

        Args:
            game: Active game instance that should receive buzz, wager, and
                answer events.

        Returns:
            ``None``.
        """
        self.thread = None
        self.loop = None
        self._loop_thread_id: int | None = None
        self.game = game
        # The port comes from config, not ``tornado.options``. Parsing
        # Tornado's options would read ``sys.argv`` (and reject JParty's own
        # flags such as ``--debug``) and reconfigure root logging.
        self.app = Application(self)
        self.port = PORT
        self.connected_players = []
        self.accepting_players = True
        self.lectern_connections = {}
        self.active_buzzer_sockets = set()
        self.saved_player_profiles = {}
        self.seat_order = []
        self.resume_mode_active = False
        # Players whose phone still had the answer box open when time ran
        # out, mapped to the socket they were on. Each may send one last
        # answer from that socket before ``late_answer_deadline`` (the phone
        # resubmits its box on ``TOOLATE``); see ``toolate`` and ``answer``.
        self.late_answer_players = {}
        self.late_answer_deadline = 0.0

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
        self.loop = tornado.ioloop.IOLoop.current()
        if threaded:
            self.thread = Thread(target=self.loop.start)
            self.thread.setDaemon(True)
            self.thread.start()
            self._loop_thread_id = self.thread.ident
        else:
            self._loop_thread_id = threading.get_ident()
            self.loop.start()

    def run_on_loop(self, callback: Callable[..., object], *args: object) -> None:
        """Run ``callback`` on the Tornado loop thread.

        Websocket writes and closes are not thread-safe, so calls made from
        the Qt thread are handed to the loop with ``add_callback``. Calls made
        on the loop thread, or before the loop has started (tests and fakes),
        run right away.

        Args:
            callback: Function to run.
            *args: Positional arguments forwarded to ``callback``.

        Returns:
            ``None``.
        """
        loop = self.loop
        if loop is None or threading.get_ident() == self._loop_thread_id:
            callback(*args)
        else:
            loop.add_callback(callback, *args)

    def send_to(
        self,
        socket_handler: BuzzerSocketHandler | LecternSocketHandler,
        msg: str,
        text: str = "",
    ) -> None:
        """Send a websocket message from the Tornado loop thread.

        Args:
            socket_handler: Player or lectern socket to write to.
            msg: Message type identifier.
            text: Optional message payload text.

        Returns:
            ``None``.
        """
        self.run_on_loop(socket_handler.send, msg, text)

    def close_socket(
        self, socket_handler: BuzzerSocketHandler | LecternSocketHandler
    ) -> None:
        """Close a websocket from the Tornado loop thread.

        Args:
            socket_handler: Player or lectern socket to close.

        Returns:
            ``None``.
        """
        self.run_on_loop(socket_handler.close)

    def restart(self) -> None:
        """Disconnect all players and reset lobby acceptance state.

        Returns:
            ``None``.
        """
        for p in self.connected_players:
            if p.waiter is not None:
                self.close_socket(p.waiter)
        self.connected_players = []
        self.accepting_players = True
        self.late_answer_players = {}
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
        self.seat_order = []
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
                self.send_to(socket_handler, "SHOW_CHOOSER", payload)

    def begin_saved_player_reclaim(
        self, saved_players: Iterable[dict[str, object]]
    ) -> None:
        """Switch the lobby into saved-player reclaim mode.

        Args:
            saved_players: Serialized player entries loaded from ``general.json``.

        Returns:
            ``None``.

        The Tornado thread may read the reclaim state at any time, so the new
        profiles are built first and then swapped in whole, never changed in
        place. Work on the open sockets runs on the Tornado loop.
        """
        profiles = {}
        for saved_player in saved_players:
            try:
                player_number = int(saved_player["player_number"])
                name = str(saved_player["name"])
            except (KeyError, TypeError, ValueError):
                continue
            profiles[player_number] = SavedPlayerProfile(
                name=name, player_number=player_number
            )
        # Turn off claims while the profiles and seats are swapped.
        self.resume_mode_active = False
        self.saved_player_profiles = profiles
        self.seat_order = sorted(profiles)
        self.connected_players = []
        self.resume_mode_active = bool(profiles)
        current_sockets = list(self.active_buzzer_sockets)
        self.game.new_player_trigger.emit()
        if not self.resume_mode_active:
            return
        if len(current_sockets) > self.saved_player_total_count():
            self.run_on_loop(self._log_out_sockets, current_sockets)
            return
        payload = tornado.escape.json_encode(self.saved_player_choices_payload())
        self.run_on_loop(self._show_chooser_on_sockets, current_sockets, payload)

    def _log_out_sockets(self, sockets: list[BuzzerSocketHandler]) -> None:
        """Ask phones to reconnect, then close them. Runs on the Tornado loop.

        Args:
            sockets: Open player sockets to close.

        Returns:
            ``None``.
        """
        for socket_handler in sockets:
            socket_handler.send("LOGOUT", "Saved game loaded. Please reconnect.")
            socket_handler.close()

    def _show_chooser_on_sockets(
        self, sockets: list[BuzzerSocketHandler], payload: str
    ) -> None:
        """Detach phones and show them the chooser. Runs on the Tornado loop.

        Args:
            sockets: Open player sockets to reset.
            payload: Encoded saved-player chooser payload.

        Returns:
            ``None``.
        """
        for socket_handler in sockets:
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
            self.send_to(
                socket_handler,
                "SHOW_CHOOSER",
                tornado.escape.json_encode(self.saved_player_choices_payload()),
            )
            return None
        if profile.player is not None and profile.player.waiter is not socket_handler:
            self.send_to(socket_handler, "PLAYER_TAKEN")
            self.send_to(
                socket_handler,
                "SHOW_CHOOSER",
                tornado.escape.json_encode(self.saved_player_choices_payload()),
            )
            return None
        if profile.player is None:
            player = Player(profile.name, socket_handler, self.seat_number(profile))
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
        """Return claimed saved players ordered by their seat.

        Returns:
            Claimed player objects in seat (current ``player_number``) order.
        """
        return [
            profile.player
            for profile in sorted(
                self.saved_player_profiles.values(), key=self.seat_number
            )
            if profile.player is not None
        ]

    def seat_number(self, profile: SavedPlayerProfile) -> int:
        """Return the seat, and so the current player number, of a profile.

        Args:
            profile: Saved player profile.

        Returns:
            The profile's position in ``seat_order``.
        """
        return self.seat_order.index(profile.player_number)

    def saved_profile_for_player(self, player: Player) -> SavedPlayerProfile | None:
        """Return the saved profile a player has claimed.

        Args:
            player: Claimed player.

        Returns:
            The matching profile, or ``None`` when the player claimed none.
        """
        for profile in self.saved_player_profiles.values():
            if profile.player is player:
                return profile
        return None

    def _renumber_claimed_players(self) -> None:
        """Give each claimed player their seat's number and buzzer key."""
        for profile in self.saved_player_profiles.values():
            if profile.player is not None:
                seat = self.seat_number(profile)
                profile.player.player_number = seat
                profile.player.key = index_to_key[seat]
        # Sort in place: the game shares this list and indexes it by number.
        self.connected_players.sort(
            key=lambda current_player: current_player.player_number
        )

    def move_saved_player(self, player: Player, offset: int) -> bool:
        """Move a claimed player to a neighboring seat in the resume lobby.

        Only the two seats involved change, so every other player keeps their
        number.

        Args:
            player: Claimed player to move.
            offset: ``-1`` to move one seat earlier, ``1`` to move one later.

        Returns:
            ``True`` when the player moved.
        """
        profile = self.saved_profile_for_player(player)
        if profile is None:
            return False
        seat = self.seat_number(profile)
        other_seat = seat + offset
        if not 0 <= other_seat < len(self.seat_order):
            return False
        self.seat_order[seat], self.seat_order[other_seat] = (
            self.seat_order[other_seat],
            self.seat_order[seat],
        )
        self._renumber_claimed_players()
        return True

    def release_saved_player(self, player: Player) -> bool:
        """Free a claimed saved-player slot so another phone can claim it.

        The seat keeps its place in ``seat_order``, so whoever claims the
        profile next gets the same number and nobody else is renumbered. The
        released phone's token stops working and it returns to the chooser.

        Args:
            player: Claimed player to release.

        Returns:
            ``True`` when a slot was released.
        """
        profile = self.saved_profile_for_player(player)
        if profile is None:
            return False
        profile.player = None
        profile.claimed_token = None
        if player in self.connected_players:
            self.connected_players.remove(player)
        socket_handler = player.waiter
        if socket_handler is not None:
            if getattr(socket_handler, "player", None) is player:
                socket_handler.player = None
            self.send_to(socket_handler, "LOGOUT", "")
        self.push_saved_player_choices()
        return True

    def saved_player_renumbering(self) -> dict[int, int]:
        """Return how saved player numbers map to the current seats.

        Returns:
            Mapping of saved ``player_number`` to current seat number.
        """
        return {
            profile.player_number: self.seat_number(profile)
            for profile in self.saved_player_profiles.values()
        }

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

    def wager(self, player: Player | None, amount: int) -> None:
        """Forward a player's Final Jeopardy wager into the game engine.

        The wager is ignored unless the player's wager prompt is open, so a
        phone can wager only once. The amount is clamped to what the player
        may bet (``Player.clamp_final_wager``) before it reaches the game.

        Args:
            player: Player object submitting the wager, or ``None`` for a
                socket that never joined.
            amount: Numeric wager amount from the client.

        Returns:
            ``None``.
        """
        if player is None or player.page != "wager":
            logging.warning("Ignoring wager from %s outside the wager phase", player)
            return
        player.page = "null"
        i_player = self.game.players.index(player)
        self.game.wager_trigger.emit(i_player, player.clamp_final_wager(amount))

    def answer(
        self,
        player: Player | None,
        guess: str,
        source: BuzzerSocketHandler | None = None,
    ) -> None:
        """Forward a player's Final Jeopardy response into the game engine.

        The answer is ignored unless the player's answer box is open, or time
        has just run out and this is the phone resubmitting its box after
        ``TOOLATE``. A late answer is only taken from the socket the player
        was on when time ran out, and only within
        ``LATE_ANSWER_GRACE_SECONDS``, so a phone that reconnects (or ignores
        ``TOOLATE``) can't answer while answers are being judged. Either way
        each player answers at most once.

        Args:
            player: Player object submitting the response, or ``None`` for a
                socket that never joined.
            guess: Final response text from the client.
            source: Socket the answer arrived on. Defaults to the player's
                current socket.

        Returns:
            ``None``.
        """
        if player is None or not self.game:
            return
        if source is None:
            source = player.waiter
        if player.page != "answer" and not self._is_late_answer(player, source):
            logging.warning("Ignoring answer from %s outside the answer phase", player)
            return
        self.late_answer_players.pop(player, None)
        player.page = "null"
        self.game.answer(player, guess)

    def _is_late_answer(
        self, player: Player, source: BuzzerSocketHandler | None
    ) -> bool:
        """Return whether an answer is the phone's resubmit after ``TOOLATE``.

        Args:
            player: Player submitting the answer.
            source: Socket the answer arrived on.

        Returns:
            ``True`` if ``player`` had the answer box open when time ran out,
            the answer came from that same socket, and the grace period has
            not ended.
        """
        late_socket = self.late_answer_players.get(player)
        if late_socket is None or source is not late_socket:
            return False
        return time.monotonic() <= self.late_answer_deadline

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
        s.connect(("8.8.8.8", PORT))
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
            self.send_to(p.waiter, "PROMPTWAGER", str(max(p.score, 0)))
            p.page = "wager"

    def prompt_answers(self) -> None:
        """Prompt all connected players to enter Final Jeopardy answers.

        Returns:
            ``None``.
        """
        self.late_answer_players = {}
        for p in self.connected_players:
            self.send_to(p.waiter, "PROMPTANSWER")
            p.page = "answer"

    def toolate(self) -> None:
        """Notify all connected players that the response window has closed.

        Each phone replies to ``TOOLATE`` by submitting whatever is in its
        answer box, so players who had not answered yet may send one last
        answer. That answer is only accepted from the socket the player is on
        now, and only for ``LATE_ANSWER_GRACE_SECONDS``. A player whose phone
        is disconnected when time runs out gets no late answer. Pages are set
        to ``"null"`` so a phone that reconnects does not show the answer box
        again.

        Returns:
            ``None``.
        """
        late_answer_players = {}
        for p in self.connected_players:
            if p.page == "answer":
                if p.waiter is not None and p.connected:
                    late_answer_players[p] = p.waiter
                p.page = "null"
        self.late_answer_deadline = time.monotonic() + LATE_ANSWER_GRACE_SECONDS
        self.late_answer_players = late_answer_players
        for p in self.connected_players:
            self.send_to(p.waiter, "TOOLATE")

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

    def get_player_state_dict(
        self, player: Player, show_final_answer: bool = False
    ) -> PlayerStateDict:
        """Build the serialized lectern state for a player.

        Lecterns are not authenticated, so the Final Jeopardy answer is left
        out unless the host is revealing it.

        Args:
            player: Player object whose state should be exposed.
            show_final_answer: Whether to include the player's Final Jeopardy
                answer.

        Returns:
            Dictionary containing the player's lectern-facing state fields.
        """
        return {
            "name": player.name,
            "score": player.score,
            "player_number": player.player_number,
            "active": False,
            "buzzed": False,
            "finalanswer": (
                getattr(player, "finalanswer", None) if show_final_answer else None
            ),
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
                self.send_to(
                    lectern, "PLAYER_STATE", tornado.escape.json_encode(state_dict)
                )
            except Exception:
                logging.error(
                    f"Error broadcasting to lectern {player_number}", exc_info=True
                )
