"""Unit tests for tournament rosters and tournament folders."""

import pytest

from jparty.domain.roster import (
    MATCH_ADD_PLAYER,
    MATCH_IGNORE,
    PlayerSlot,
    RosterError,
    SignUp,
    apply_matches,
    fill_blank_slots,
    new_sign_ups,
    open_slots,
    parse_sign_up_sheet,
    suggest_matches,
    title_case_name,
    update_linked_sign_ups,
)
from jparty.domain.tournament_store import (
    TournamentFileError,
    TournamentSettings,
    list_tournaments,
    load_tournament,
    parse_players_csv,
    players_csv_text,
    save_tournament,
    tournament_name_problem,
)
from jparty.services.game_sources import SheetAccessError, google_sheet_csv_url

pytestmark = pytest.mark.unit

HEADER = [
    "Timestamp",
    "Full Name",
    "Occupation",
    "Hometown",
    "Anecdote #1",
    "Anecdote #2",
    "Anecdote #3",
]


def sign_up(timestamp: str, name: str, **kwargs: str) -> SignUp:
    """Return a sign-up with the given timestamp and name."""
    return SignUp(timestamp=timestamp, full_name=name, **kwargs)


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("jane doe", "Jane Doe"),
        ("JOHN SMITH", "John Smith"),
        ("  mary   o'brien-smith ", "Mary O'Brien-Smith"),
        ("Ronald McDonald", "Ronald McDonald"),
        ("", ""),
    ],
)
def test_title_case_name(typed: str, expected: str) -> None:
    """Names are title cased without breaking names typed in mixed case."""
    assert title_case_name(typed) == expected


def test_parse_sign_up_sheet_reads_form_columns() -> None:
    """Each response row becomes a sign-up, in sheet order."""
    rows = [
        HEADER,
        ["1/1/2026 10:00", " Jane Doe ", "Pilot", "Boise", "a", "", "c"],
        ["", "No timestamp", "", "", "", "", ""],
        ["1/2/2026 9:00", "Bob", "Chef"],
    ]
    sign_ups = parse_sign_up_sheet(rows)
    assert sign_ups == [
        SignUp("1/1/2026 10:00", "Jane Doe", "Pilot", "Boise", ("a", "", "c")),
        SignUp("1/2/2026 9:00", "Bob", "Chef", "", ("", "", "")),
    ]


def test_parse_sign_up_sheet_matches_headers_loosely() -> None:
    """Column order and case don't matter, and only two columns are needed."""
    rows = [[" full name", "TIMESTAMP"], ["Ann", "t1"]]
    assert parse_sign_up_sheet(rows) == [SignUp("t1", "Ann")]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([], "empty"),
        ([["Timestamp", "Name"]], '"Full Name" column'),
        ([["Timestamp", "Full Name"], ["t", "A"], ["t", "B"]], "same Timestamp"),
    ],
)
def test_parse_sign_up_sheet_rejects_bad_sheets(rows: list, message: str) -> None:
    """Sheets that can't be matched on refresh are rejected with a reason."""
    with pytest.raises(RosterError, match=message):
        parse_sign_up_sheet(rows)


def test_first_fetch_fills_blank_slots_in_order() -> None:
    """With no typed names, sign-ups fill the slots without asking."""
    slots = [PlayerSlot() for _ in range(3)]
    rows = [sign_up("t1", "jane doe"), sign_up("t2", "Bob")]
    filled, remaining = fill_blank_slots(slots, rows)
    assert remaining == []
    assert [slot.actual_name for slot in filled] == ["Jane Doe", "Bob", ""]
    assert filled[0].sign_up == rows[0]


def test_more_sign_ups_than_slots_leaves_the_rest() -> None:
    """Sign-ups beyond the open slots are left for the host to place."""
    filled, remaining = fill_blank_slots([PlayerSlot()], [sign_up("t1", "A")] * 2)
    assert len(remaining) == 1
    assert filled[0].actual_name == "A"


def test_typed_names_send_every_sign_up_to_the_host() -> None:
    """Once any open slot has a typed name, nothing is filled automatically."""
    slots = [PlayerSlot("Jane Doe"), PlayerSlot()]
    filled, remaining = fill_blank_slots(slots, [sign_up("t1", "jane")])
    assert filled == slots
    assert len(remaining) == 1


def test_refresh_finds_only_new_sign_ups() -> None:
    """Linked and ignored rows are not new."""
    slots = [PlayerSlot("A", sign_up("t1", "A")), PlayerSlot("B")]
    rows = [sign_up("t1", "A"), sign_up("t2", "x"), sign_up("t3", "B")]
    assert new_sign_ups(slots, rows, ignored=["t2"]) == [rows[2]]


def test_refresh_updates_linked_answers_but_keeps_the_name() -> None:
    """Edited form answers replace the old ones; the Actual Name stays."""
    slots = [PlayerSlot("Jane", sign_up("t1", "jd", occupation="Pilot"))]
    updated = update_linked_sign_ups(slots, [sign_up("t1", "jd", occupation="Chef")])
    assert updated[0].actual_name == "Jane"
    assert updated[0].sign_up.occupation == "Chef"


def test_suggestions_pair_similar_names_with_typed_slots() -> None:
    """Typed names get the sign-up with the closest Full Name."""
    slots = [PlayerSlot("Jane Doe"), PlayerSlot("Robert Smith"), PlayerSlot()]
    rows = [sign_up("t1", "bob smith"), sign_up("t2", "jane doe"), sign_up("t3", "Z")]
    matches = suggest_matches(slots, rows)
    assert [match.suggested_slot for match in matches] == [1, 0, 2]


def test_suggestions_fall_back_to_a_new_slot() -> None:
    """With no close name and no blank slot, suggest adding a player."""
    slots = [PlayerSlot("Jane Doe")]
    matches = suggest_matches(slots, [sign_up("t1", "Quentin")])
    assert matches[0].suggested_slot is None


def test_slot_whose_row_left_the_sheet_is_open() -> None:
    """A deleted and resubmitted response can be relinked to its slot."""
    slots = [PlayerSlot("Jane", sign_up("old", "Jane")), PlayerSlot("Bob")]
    assert open_slots(slots) == [1]
    assert open_slots(slots, [sign_up("new", "Jane")]) == [0, 1]


def test_apply_matches_links_adds_and_ignores() -> None:
    """Each choice links, appends, or ignores its sign-up."""
    slots = [PlayerSlot("Jane"), PlayerSlot()]
    choices = [
        (sign_up("t1", "jane doe"), 0),
        (sign_up("t2", "new person"), MATCH_ADD_PLAYER),
        (sign_up("t3", "test"), MATCH_IGNORE),
    ]
    updated, ignored = apply_matches(slots, choices)
    assert [slot.actual_name for slot in updated] == ["Jane", "", "New Person"]
    assert updated[0].sign_up.timestamp == "t1"
    assert ignored == ["t3"]


def test_apply_matches_rejects_a_slot_chosen_twice() -> None:
    """Two sign-ups can't share a slot."""
    with pytest.raises(ValueError, match="twice"):
        apply_matches([PlayerSlot()], [(sign_up("a", "A"), 0), (sign_up("b", "B"), 0)])


def test_players_csv_round_trips() -> None:
    """Linked and unlinked slots survive a save and load, commas included."""
    slots = [
        PlayerSlot("Jane", SignUp("t1", "j, d", "Pilot", "Boise", ("a", "", "c"))),
        PlayerSlot("Typed Name"),
        PlayerSlot(),
    ]
    assert parse_players_csv(players_csv_text(slots)) == slots


def test_players_csv_needs_actual_name_column() -> None:
    """A players.csv without actual_name can't be read."""
    with pytest.raises(TournamentFileError):
        parse_players_csv("name\nJane\n")


def test_save_and_load_tournament(temp_dir: object) -> None:
    """A saved tournament lists by name and loads back."""
    settings = TournamentSettings("Family Fun", "https://example", ["t9"])
    slots = [PlayerSlot("Jane"), PlayerSlot("Bob")]
    folder = save_tournament(temp_dir, settings, slots)
    (temp_dir / "not a tournament").mkdir()
    assert folder == temp_dir / "Family Fun"
    assert list_tournaments(temp_dir) == ["Family Fun"]
    assert load_tournament(folder) == (settings, slots)


def test_load_tournament_reports_missing_files(temp_dir: object) -> None:
    """A folder without both files can't be loaded."""
    (temp_dir / "Empty").mkdir()
    with pytest.raises(TournamentFileError, match="tournament.json"):
        load_tournament(temp_dir / "Empty")


@pytest.mark.parametrize(
    ("name", "ok"),
    [("Family Fun 2026", True), ("", False), (" x", False), ("a/b", False)],
)
def test_tournament_name_problem(name: str, ok: bool) -> None:
    """Names must work as folder names."""
    assert (tournament_name_problem(name) is None) is ok


def test_tournament_name_rejects_windows_reserved_names() -> None:
    """Windows can't create folders with reserved names."""
    assert "reserved" in tournament_name_problem("con")


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        (
            "https://docs.google.com/spreadsheets/d/abc_DEF-123/edit?usp=sharing",
            "https://docs.google.com/spreadsheets/d/abc_DEF-123/export?format=csv",
        ),
        (
            "https://docs.google.com/spreadsheets/d/abc/edit#gid=42",
            "https://docs.google.com/spreadsheets/d/abc/export?format=csv&gid=42",
        ),
        (
            "docs.google.com/spreadsheets/d/e/2PACX-x/pubhtml?gid=7",
            "https://docs.google.com/spreadsheets/d/e/2PACX-x/pub?output=csv&gid=7",
        ),
        (
            "1_vBBsWn-EVc7npamLnOKHs34Mc2iAmd9hOGSzxHQX0Y",
            "https://docs.google.com/spreadsheets/d/"
            "1_vBBsWn-EVc7npamLnOKHs34Mc2iAmd9hOGSzxHQX0Y/export?format=csv",
        ),
    ],
)
def test_google_sheet_csv_url(link: str, expected: str) -> None:
    """Pasted sheet links become CSV export URLs for the linked tab."""
    assert google_sheet_csv_url(link) == expected


@pytest.mark.parametrize("link", ["https://example.com/spreadsheets/d/abc", "hello"])
def test_google_sheet_csv_url_rejects_other_links(link: str) -> None:
    """Links that aren't Google Sheets are rejected."""
    with pytest.raises(SheetAccessError):
        google_sheet_csv_url(link)
