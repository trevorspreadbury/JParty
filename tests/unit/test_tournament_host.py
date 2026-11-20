"""Tests for what the host's phone page shows about tournament players."""

from jparty.domain.roster import PlayerSlot, SignUp
from jparty.domain.tournament_host import (
    HostPlayer,
    HostPrompt,
    host_page,
    mark_prompt,
)
from jparty.domain.tournament_store import (
    TournamentSettings,
    load_used_prompts,
    save_tournament,
)


def write_tournament(root: object) -> object:
    """Save a nine-player tournament; Ziggy and P2 have sign-up answers."""
    slots = [PlayerSlot(f"P{index}", player_id=f"p{index}") for index in range(9)]
    slots[0] = PlayerSlot(
        "Ziggy",
        SignUp("t", "Jane Smith", "teacher", "Chicago", ("Has a cat", "", "Sings")),
        player_id="p0",
    )
    slots[2] = PlayerSlot(
        "P2", SignUp("u", "P2", "chef", "Austin", ("Juggles",)), player_id="p2"
    )
    slots[8] = PlayerSlot("  ", player_id="blank")
    return save_tournament(root, TournamentSettings("Fun"), slots)


def test_no_tournament_shows_nothing() -> None:
    """Outside tournament mode the page has no tournament."""
    page = host_page(None)
    assert (page.tournament, page.players, page.problem) == ("", (), "")


def test_with_no_game_every_named_player_is_shown_in_roster_order(
    tmp_path: object,
) -> None:
    """Each player has the host screen's intro and their numbered prompts."""
    page = host_page(write_tournament(tmp_path))
    assert page.tournament == "Fun"
    assert not page.in_game
    assert [player.name for player in page.players] == [
        "Ziggy",
        *(f"P{index}" for index in range(1, 8)),
    ]
    # Blank anecdotes are left out, but the others keep their numbers.
    assert page.players[0] == HostPlayer(
        "p0",
        "Ziggy",
        "A teacher from Chicago, Jane Smith (Ziggy)",
        (HostPrompt(1, "Has a cat"), HostPrompt(3, "Sings")),
    )
    assert page.players[4].prompts == ()


def test_during_a_game_only_its_players_show_in_reverse_seat_order(
    tmp_path: object,
) -> None:
    """Podium 3 first, then 2, then 1, the order a host introduces them."""
    page = host_page(write_tournament(tmp_path), ["p6", "p0", "p2"])
    assert page.in_game
    assert [(player.player_id, player.seat) for player in page.players] == [
        ("p2", 3),
        ("p0", 2),
        ("p6", 1),
    ]


def test_a_podium_with_no_tournament_player_keeps_the_seat_numbers(
    tmp_path: object,
) -> None:
    """An empty or untracked podium doesn't shift the others' seats."""
    page = host_page(write_tournament(tmp_path), [None, "p0", "p2"])
    assert [(player.player_id, player.seat) for player in page.players] == [
        ("p2", 3),
        ("p0", 2),
    ]


def test_ticked_prompts_stay_used_until_unticked(tmp_path: object) -> None:
    """A tick is saved in used_prompts.csv and shows on the next page load."""
    folder = write_tournament(tmp_path)
    assert mark_prompt(folder, "p0", 3, True) == ""
    assert load_used_prompts(folder) == [("p0", 3, "Sings")]
    ziggy = host_page(folder).players[0]
    assert ziggy.prompts == (HostPrompt(1, "Has a cat"), HostPrompt(3, "Sings", True))

    assert mark_prompt(folder, "p0", 3, False) == ""
    assert load_used_prompts(folder) == []
    assert not any(prompt.used for prompt in host_page(folder).players[0].prompts)


def test_ticking_a_prompt_that_isnt_there_is_refused(tmp_path: object) -> None:
    """Unknown players, blank anecdotes, and missing numbers aren't saved."""
    folder = write_tournament(tmp_path)
    assert mark_prompt(folder, "p0", 2, True) == "That player has no such prompt."
    assert mark_prompt(folder, "p0", 4, True) == "That player has no such prompt."
    assert mark_prompt(folder, "nobody", 1, True) == "That player has no such prompt."
    assert mark_prompt(None, "p0", 1, True) == "No tournament is being played."
    assert load_used_prompts(folder) == []


def test_unreadable_tournament_says_why(tmp_path: object) -> None:
    """A missing tournament folder is reported, not raised."""
    page = host_page(tmp_path / "Gone")
    assert page.tournament == "Gone"
    assert page.players == ()
    assert page.problem.startswith("Couldn't read the tournament:")
