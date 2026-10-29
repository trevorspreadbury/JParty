"""Test reordering and releasing players in the resume lobby (issue #55)."""

import json
from pathlib import Path

import pytest
from jparty.domain.input import index_to_key
from jparty.domain.state import read_history_file
from jparty.web import controller as controller_module
from jparty.web.controller import BuzzerController

pytestmark = pytest.mark.integration

SAVED_PLAYERS = [("Alice", 0, 2400), ("Bob", 1, 600), ("Cara", 2, -200)]


class FakeSocket:
    """Stand-in for a phone's websocket connection."""

    def __init__(self) -> None:
        """Start with no player and no messages."""
        self.player = None
        self.sent = []
        self.closed = False

    def send(self, msg: str, text: str = "") -> None:
        """Record an outgoing message."""
        self.sent.append(msg)

    def close(self) -> None:
        """Record that the socket was closed."""
        self.closed = True


def _write_save(saved_dir: Path) -> None:
    """Write a save where Alice=$2400, Bob=$600, and Cara=-$200."""
    saved_dir.mkdir()
    (saved_dir / "general.json").write_text(
        json.dumps(
            {
                "game_id": "4453",
                "players": [
                    {"name": name, "player_number": number}
                    for name, number, _ in SAVED_PLAYERS
                ],
            }
        ),
        encoding="utf-8",
    )
    lines = []
    for question_number, (_, number, score) in enumerate(SAVED_PLAYERS, start=1):
        lines.append(
            json.dumps(
                {
                    "question_index": [0, [number, 0]],
                    "question_number": question_number,
                    "round_index": 0,
                    "category": f"Cat {number}",
                    "value": abs(score),
                    "is_daily_double": False,
                    "buzz_phases": [],
                    "answer_attempts": [
                        {
                            "player_index": number,
                            "answer_correct": score > 0,
                            "timestamp": 1700000000.0 + question_number,
                            "score_before": 0,
                            "score_after": score,
                        }
                    ],
                    "completed_at": 1700000000.5 + question_number,
                }
            )
        )
    (saved_dir / "question_history.jsonl").write_text(
        "".join(line + "\n" for line in lines), encoding="utf-8"
    )


@pytest.fixture
def saved_dir(temp_dir: Path) -> Path:
    """Return a saved three-player game folder."""
    path = temp_dir / "saved_game"
    _write_save(path)
    return path


@pytest.fixture
def lobby(game: object, monkeypatch: object, saved_dir: Path) -> object:
    """Load the save into ``game`` with a real controller in reclaim mode."""
    from jparty.services import game_loader

    monkeypatch.setattr(
        controller_module.tornado.options, "parse_command_line", lambda: None
    )
    monkeypatch.setattr(game_loader, "get_game", lambda game_id: game.data)
    monkeypatch.setattr(game, "_update_all_lecterns", lambda: None)
    monkeypatch.setattr(game, "_update_lectern_for_player", lambda *args, **kw: None)
    controller = BuzzerController(game)
    game.buzzer_controller = controller
    game.prepare_resume_from_dir(saved_dir)
    return controller


def _claim_all(controller: BuzzerController) -> dict[str, tuple]:
    """Have one phone claim each saved player; return name -> (socket, player)."""
    claimed = {}
    for name, number, _ in SAVED_PLAYERS:
        socket = FakeSocket()
        controller.register_socket(socket)
        claimed[name] = (socket, controller.claim_saved_player(socket, number))
    return claimed


def _seats(game: object) -> list[tuple]:
    """Return ``(name, player_number, score)`` for every player in order."""
    return [
        (player.name, player.player_number, player.score) for player in game.players
    ]


def _assert_numbers_are_seats(game: object) -> None:
    """Assert numbers are unique, match list position, and drive the keys."""
    numbers = [player.player_number for player in game.players]
    assert numbers == list(range(len(numbers)))
    assert [player.key for player in game.players] == [
        index_to_key[number] for number in numbers
    ]


def test_no_lobby_changes_resume_as_saved(
    game: object, lobby: BuzzerController
) -> None:
    """Test the baseline: everyone keeps their own slot and score."""
    _claim_all(lobby)
    game.start_game()
    assert _seats(game) == [("Alice", 0, 2400), ("Bob", 1, 600), ("Cara", 2, -200)]
    lines = (game._game_state_dir / "question_history.jsonl").read_text().splitlines()
    assert all(json.loads(line).get("type") != "player_renumber" for line in lines)


def test_swapping_players_keeps_each_score_and_logs_new_numbers(
    game: object, lobby: BuzzerController, saved_dir: Path
) -> None:
    """Test moving Bob up swaps seats, not scores, and records the mapping."""
    claimed = _claim_all(lobby)
    bob = claimed["Bob"][1]

    game.move_player_up(bob)
    assert [(player.name, player.player_number) for player in game.players] == [
        ("Bob", 0),
        ("Alice", 1),
        ("Cara", 2),
    ]
    _assert_numbers_are_seats(game)

    game.start_game()
    assert _seats(game) == [("Bob", 0, 600), ("Alice", 1, 2400), ("Cara", 2, -200)]
    history_file = saved_dir / "question_history.jsonl"
    renumber = json.loads(history_file.read_text().splitlines()[-1])
    assert renumber["type"] == "player_renumber"
    assert renumber["mapping"] == {"0": 1, "1": 0, "2": 2}
    general = json.loads((saved_dir / "general.json").read_text())
    assert [(p["name"], p["player_number"]) for p in general["players"]] == [
        ("Bob", 0),
        ("Alice", 1),
        ("Cara", 2),
    ]

    # The next clue is logged under Bob's new number and continues his score.
    question = game.current_round.get_question(3, 0)
    game.load_question(question)
    game.open_responses()
    game.buzz(0)
    game.correct_answer()
    entries = read_history_file(history_file)
    attempt = entries[-1]["answer_attempts"][0]
    assert attempt["player_index"] == 0
    assert attempt["score_before"] == 600
    assert game.players[0].score == 600 + question.value


def test_resuming_a_renumbered_save_again_keeps_scores(
    game: object, lobby: BuzzerController, saved_dir: Path
) -> None:
    """Test a second resume reads the mapping line and restores the same scores."""
    claimed = _claim_all(lobby)
    game.move_player_up(claimed["Bob"][1])
    game.start_game()

    game.prepare_resume_from_dir(saved_dir)
    for name, number in (("Bob", 0), ("Alice", 1), ("Cara", 2)):
        socket = FakeSocket()
        lobby.register_socket(socket)
        assert lobby.claim_saved_player(socket, number).name == name
    game.start_game()

    assert _seats(game) == [("Bob", 0, 600), ("Alice", 1, 2400), ("Cara", 2, -200)]
    lines = (saved_dir / "question_history.jsonl").read_text().splitlines()
    renumber_lines = [
        line for line in lines if json.loads(line).get("type") == "player_renumber"
    ]
    assert len(renumber_lines) == 1


def test_releasing_a_middle_slot_frees_it_without_renumbering(
    game: object, lobby: BuzzerController
) -> None:
    """Test X on Bob frees his slot for another phone and blocks Start."""
    claimed = _claim_all(lobby)
    bob_socket, bob = claimed["Bob"]
    bob_token = bob.token.hex()

    game.remove_player(bob)

    assert [(player.name, player.player_number) for player in game.players] == [
        ("Alice", 0),
        ("Cara", 2),
    ]
    assert bob_socket.sent[-2:] == ["LOGOUT", "SHOW_CHOOSER"]
    assert bob_socket.player is None
    assert bob_socket.closed is False
    assert lobby.player_with_token(bob_token) is None
    assert game.startable() is False
    assert lobby.claimed_saved_players() == [claimed["Alice"][1], claimed["Cara"][1]]

    new_socket = FakeSocket()
    lobby.register_socket(new_socket)
    new_bob = lobby.claim_saved_player(new_socket, 1)
    assert (new_bob.name, new_bob.player_number) == ("Bob", 1)
    assert game.startable() is True
    game.start_game()
    assert _seats(game) == [("Alice", 0, 2400), ("Bob", 1, 600), ("Cara", 2, -200)]


def test_release_after_swap_then_reclaim_keeps_the_seat_number(
    game: object, lobby: BuzzerController
) -> None:
    """Test a released seat keeps its number for whoever claims it next."""
    claimed = _claim_all(lobby)
    game.move_player_up(claimed["Bob"][1])
    alice = claimed["Alice"][1]
    assert alice.player_number == 1

    game.remove_player(alice)
    new_socket = FakeSocket()
    lobby.register_socket(new_socket)
    new_alice = lobby.claim_saved_player(new_socket, 0)

    assert (new_alice.name, new_alice.player_number) == ("Alice", 1)
    _assert_numbers_are_seats(game)
    game.start_game()
    assert _seats(game) == [("Bob", 0, 600), ("Alice", 1, 2400), ("Cara", 2, -200)]


def test_other_phones_can_claim_a_released_slot(
    game: object, lobby: BuzzerController
) -> None:
    """Test the chooser offers the released slot instead of PLAYER_TAKEN."""
    claimed = _claim_all(lobby)
    game.remove_player(claimed["Cara"][1])
    waiting = FakeSocket()
    lobby.register_socket(waiting)
    payload = lobby.saved_player_choices_payload()
    assert [choice["claimed"] for choice in payload["players"]] == [True, True, False]
    player = lobby.claim_saved_player(waiting, 2)
    assert player is not None
    assert "PLAYER_TAKEN" not in waiting.sent
