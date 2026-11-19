"""Tests for what the host's phone page shows about tournament players."""

from jparty.domain.roster import PlayerSlot, SignUp
from jparty.domain.tournament_host import HostPlayer, host_page
from jparty.domain.tournament_play import GameResult
from jparty.domain.tournament_store import (
    TournamentSettings,
    save_results,
    save_tournament,
)

SF1 = "Semifinals: SF 1"


def write_tournament(root: object) -> object:
    """Save a nine-player tournament where SF 1 has been played."""
    slots = [PlayerSlot(f"P{index}", player_id=f"p{index}") for index in range(9)]
    slots[0] = PlayerSlot(
        "Ziggy",
        SignUp("t", "Jane Smith", "teacher", "Chicago", ("Has a cat", "", "Sings")),
        player_id="p0",
    )
    slots[8] = PlayerSlot("  ", player_id="blank")
    folder = save_tournament(root, TournamentSettings("Fun"), slots)
    save_results(
        folder,
        [
            GameResult(SF1, "p1", "P1", 900, 700, "Fun-1", "win"),
            GameResult(SF1, "p2", "P2", 100, 100, "Fun-1", "loss"),
            GameResult(SF1, "p3", "P3", 0, 0, "Fun-1", "loss"),
        ],
    )
    return folder


def test_no_tournament_shows_nothing() -> None:
    """Outside tournament mode the page has no tournament."""
    page = host_page(None)
    assert (page.tournament, page.players, page.problem) == ("", (), "")


def test_players_show_their_introduction_prompts_and_status(tmp_path: object) -> None:
    """Each named player has the host screen's intro and their sign-up answers."""
    page = host_page(write_tournament(tmp_path))
    assert page.tournament == "Fun"
    assert [player.name for player in page.players] == [
        "Ziggy",
        *(f"P{index}" for index in range(1, 8)),
    ]
    assert page.players[0] == HostPlayer(
        "p0",
        "Ziggy",
        "A teacher from Chicago, Jane Smith (Ziggy)",
        "",
        ("Has a cat", "Sings"),
    )
    by_id = {player.player_id: player for player in page.players}
    assert by_id["p1"].status == "played the Semifinals"
    assert by_id["p4"].introduction == "P4"
    assert by_id["p4"].prompts == ()


def test_players_on_stage_come_first_in_podium_order(tmp_path: object) -> None:
    """The game in progress's players lead the list, in podium order."""
    page = host_page(write_tournament(tmp_path), ["p6", "p4", "p5"])
    assert [player.player_id for player in page.players[:4]] == ["p6", "p4", "p5", "p0"]
    assert [player.on_stage for player in page.players[:4]] == [True, True, True, False]


def test_unreadable_tournament_says_why(tmp_path: object) -> None:
    """A missing tournament folder is reported, not raised."""
    page = host_page(tmp_path / "Gone")
    assert page.tournament == "Gone"
    assert page.players == ()
    assert page.problem.startswith("Couldn't read the tournament:")
