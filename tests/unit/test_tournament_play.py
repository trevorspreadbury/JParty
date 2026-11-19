"""Tests for playing tournament games: eligibility, results, introductions."""

import pytest

from jparty.domain.roster import PlayerSlot, SignUp
from jparty.domain.tournament import TournamentOptions, plan_tournament
from jparty.domain.tournament_play import (
    INTRO_HEADING,
    SAVED_PLAYER_ID,
    SAVED_PLAYER_NAME,
    GameResult,
    PlayerOutcome,
    TournamentGameRef,
    already_recorded,
    eligible_players,
    game_results,
    introduction_line,
    introduction_lines,
    record_results,
    seating_problem,
)
from jparty.domain.tournament_setup import TournamentBoard
from jparty.domain.tournament_store import (
    RESULTS_FILE,
    TournamentFileError,
    load_results,
    parse_results_csv,
    record_game_results,
    results_csv_text,
    save_results,
)

QF1 = "Quarterfinals: QF 1"
QF2 = "Quarterfinals: QF 2"
CHASE = "Quarterfinals: Chase 1"
SF1 = "Semifinals: SF 1"


def roster(count: int) -> list[PlayerSlot]:
    """Return ``count`` named players with ids ``p0``, ``p1``, ..."""
    return [PlayerSlot(f"P{index}", player_id=f"p{index}") for index in range(count)]


def result(key: str, player_id: str, won: bool = False, score: int = 0) -> GameResult:
    """Return a result row for ``player_id`` in ``key``."""
    return GameResult(
        key,
        player_id,
        player_id.upper(),
        score,
        None,
        "Fun-1",
        "win" if won else "loss",
    )


def played(key: str, *player_ids: str) -> list[GameResult]:
    """Return a game's rows; the first player won."""
    return [
        result(key, player_id, won=index == 0)
        for index, player_id in enumerate(player_ids)
    ]


# Introductions


def slot(
    actual: str, full: str = "", occupation: str = "", hometown: str = ""
) -> object:
    """Return a slot linked to a sign-up, or unlinked when ``full`` is blank."""
    sign_up = SignUp("t", full, occupation, hometown) if full else None
    return PlayerSlot(actual, sign_up)


@pytest.mark.parametrize(
    ("player", "expected"),
    [
        (
            slot("Ziggy", "Jane Smith", "teacher", "Chicago"),
            "A teacher from Chicago, Jane Smith (Ziggy)",
        ),
        (
            slot("Jane Smith", "jane  smith", "engineer", "Austin"),
            "An engineer from Austin, jane  smith",
        ),
        (slot("Sam"), "Sam"),
        (slot("Sam", "Sam Lee", "", "Boston"), "From Boston, Sam Lee (Sam)"),
        (slot("Sam", "Sam Lee", "pilot", ""), "A pilot, Sam Lee (Sam)"),
        (slot("Sam", "Sam"), "Sam"),
    ],
)
def test_introduction_line(player: PlayerSlot, expected: str) -> None:
    """Each player gets the issue's line, with blanks and repeats left out."""
    assert introduction_line(player) == expected


def test_introduction_lines_start_with_the_heading() -> None:
    """The heading comes first, then players in podium order."""
    assert introduction_lines([slot("A"), slot("B")]) == [INTRO_HEADING, "A", "B"]


# Eligibility


def test_first_round_is_open_to_players_who_have_not_played_it() -> None:
    """Players who played a Quarterfinal can't play another one."""
    plan = plan_tournament(TournamentOptions(11))
    results = played(QF1, "p0", "p1", "p2")
    eligibility = eligible_players(plan, QF2, roster(11), results)
    assert eligibility.entrants == tuple(f"p{index}" for index in range(3, 11))
    assert eligibility.chasers == ()
    assert not eligibility.chase


def test_cant_play_and_blank_names_are_never_eligible() -> None:
    """A board's Can't Play list and unnamed slots are left out."""
    plan = plan_tournament(TournamentOptions(9))
    slots = [*roster(8), PlayerSlot("  ", player_id="blank")]
    board = TournamentBoard("b", ({"game_id": "1"},), cant_play=("p1",))
    eligibility = eligible_players(plan, SF1, slots, [], board)
    assert "p1" not in eligibility.entrants
    assert "blank" not in eligibility.entrants
    assert len(eligibility.entrants) == 7


def test_chase_game_offers_new_players_and_this_rounds_losers() -> None:
    """The chaser seat is for a player who lost earlier in the round."""
    plan = plan_tournament(TournamentOptions(11))
    results = played(QF1, "p0", "p1", "p2") + played(QF2, "p3", "p4", "p5")
    eligibility = eligible_players(plan, CHASE, roster(11), results)
    assert eligibility.chase
    assert eligibility.entrants == ("p6", "p7", "p8", "p9", "p10")
    assert eligibility.chasers == ("p1", "p2", "p4", "p5")


def test_later_round_is_open_to_the_previous_rounds_players() -> None:
    """A Semifinal takes players who played a Quarterfinal, once each."""
    plan = plan_tournament(TournamentOptions(11))
    results = (
        played(QF1, "p0", "p1", "p2")
        + played(QF2, "p3", "p4", "p5")
        + played(SF1, "p0", "p3", "p1")
    )
    eligibility = eligible_players(plan, "Semifinals: SF 2", roster(11), results)
    assert eligibility.entrants == ("p2", "p4", "p5")


def test_byes_let_preliminary_players_into_the_semifinals() -> None:
    """With a second round and byes, prelim players can sit a Semifinal."""
    plan = plan_tournament(
        TournamentOptions(23, use_second_round=True, semifinal_byes=3)
    )
    results = played("Preliminaries: Prelim 1", "p0", "p1", "p2") + played(
        "Second Round: R2 1", "p3", "p4", "p5"
    )
    eligibility = eligible_players(plan, SF1, roster(23), results)
    assert eligibility.entrants == ("p0", "p1", "p2", "p3", "p4", "p5")


def test_unknown_game_has_no_one_eligible() -> None:
    """A key that isn't in the bracket offers nobody."""
    plan = plan_tournament(TournamentOptions(9))
    assert eligible_players(plan, "Nope", roster(9), []).player_ids == ()


def test_seating_problems() -> None:
    """Every podium needs a different, eligible player."""
    plan = plan_tournament(TournamentOptions(11))
    eligibility = eligible_players(plan, QF1, roster(11), [])
    assert "each of the 3 podiums" in seating_problem(eligibility, ["p0", None, "p1"])
    assert "different player" in seating_problem(eligibility, ["p0", "p0", "p1"])
    assert "can't play" in seating_problem(eligibility, ["p0", "p1", "ghost"])
    assert seating_problem(eligibility, ["p0", "p1", "p2"]) is None


def test_chase_game_needs_exactly_one_chaser() -> None:
    """Two new players and one player who already lost this round."""
    plan = plan_tournament(TournamentOptions(11))
    results = played(QF1, "p0", "p1", "p2")
    eligibility = eligible_players(plan, CHASE, roster(11), results)
    assert "one chaser" in seating_problem(eligibility, ["p3", "p4", "p5"])
    assert "one chaser" in seating_problem(eligibility, ["p1", "p2", "p5"])
    assert seating_problem(eligibility, ["p3", "p4", "p1"]) is None


# Results


def test_record_results_replaces_a_games_rows_in_place() -> None:
    """Logging a game again replaces its rows where they were."""
    first = played(QF1, "p0", "p1", "p2")
    second = played(QF2, "p3", "p4", "p5")
    again = played(QF1, "p2", "p1", "p0")
    assert record_results(first + second, again) == again + second
    assert record_results(first, second) == first + second
    assert record_results(first, []) == first


def test_game_results_follow_the_saved_players_current_seats() -> None:
    """Rows match players by their current seat, so reordering is kept."""
    ref = TournamentGameRef("Fun", QF1)
    # The host swapped the first two seats when resuming.
    saved_players = [
        {
            "name": "A",
            "player_number": 1,
            SAVED_PLAYER_ID: "ann",
            SAVED_PLAYER_NAME: "Ann",
        },
        {
            "name": "B",
            "player_number": 0,
            SAVED_PLAYER_ID: "bob",
            SAVED_PLAYER_NAME: "Bob",
        },
        {"name": "C", "player_number": 2},
    ]
    outcomes = [
        PlayerOutcome(0, 100, 50),
        PlayerOutcome(1, 900, 700),
        PlayerOutcome(2, 10, 10),
    ]
    rows = game_results(ref, saved_players, outcomes, [1], "4453", "save-1")
    assert rows == [
        GameResult(QF1, "bob", "Bob", 100, 50, "Fun-4453", "loss", "save-1"),
        GameResult(QF1, "ann", "Ann", 900, 700, "Fun-4453", "win", "save-1"),
    ]


def test_already_recorded_only_matches_the_same_save() -> None:
    """A replay from a new save isn't 'already recorded'."""
    rows = [GameResult(QF1, "p0", "P0", 1, None, "Fun-1", "win", "save-1")]
    assert already_recorded(rows, QF1, "save-1")
    assert not already_recorded(rows, QF1, "save-2")
    assert not already_recorded(rows, QF2, "save-1")


def test_game_ref_round_trips_and_rejects_junk() -> None:
    """The general.json value reads back, and junk reads as no tournament."""
    ref = TournamentGameRef("Fun", QF1)
    assert TournamentGameRef.from_json(ref.to_json()) == ref
    for junk in (
        None,
        "Fun",
        {"name": "Fun"},
        {"game_key": QF1},
        {"name": " ", "game_key": QF1},
    ):
        assert TournamentGameRef.from_json(junk) is None


# results.csv


def test_results_csv_round_trips(temp_dir: object) -> None:
    """Saved results read back unchanged, with the issue's columns first."""
    rows = [
        GameResult(QF1, "p0", "Ann, Jr.", 1200, 800, "Fun-4453", "win", "save"),
        GameResult(QF1, "p1", "Bob", -200, None, "Fun-4453", "loss", "save"),
    ]
    text = results_csv_text(rows)
    assert text.splitlines()[0].startswith("player,score,coryat,game,result")
    assert parse_results_csv(text) == rows
    save_results(temp_dir, rows)
    assert load_results(temp_dir) == rows


def test_record_game_results_replaces_only_that_game(temp_dir: object) -> None:
    """Recording a game keeps other games' rows."""
    save_results(temp_dir, played(QF1, "p0", "p1", "p2"))
    record_game_results(temp_dir, played(QF2, "p3", "p4", "p5"))
    record_game_results(temp_dir, played(QF1, "p2", "p1", "p0"))
    assert load_results(temp_dir) == played(QF1, "p2", "p1", "p0") + played(
        QF2, "p3", "p4", "p5"
    )


def test_missing_results_file_means_nothing_played(temp_dir: object) -> None:
    """A tournament with no games played has no results."""
    assert load_results(temp_dir) == []


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("Ann,lots,,g,win,p0,QF,s", "score 'lots'"),
        ("Ann,1,x,g,win,p0,QF,s", "coryat 'x'"),
        ("Ann,1,,g,tie,p0,QF,s", "result 'tie'"),
    ],
)
def test_bad_results_rows_name_the_problem(row: str, message: str) -> None:
    """A hand-edited file with a bad cell says which line and cell."""
    header = "player,score,coryat,game,result,player_id,game_key,saved_game"
    with pytest.raises(TournamentFileError) as error:
        parse_results_csv(f"{header}\n{row}\n")
    assert message in str(error.value)
    assert f"{RESULTS_FILE} line 2" in str(error.value)


def test_rows_without_ids_are_skipped() -> None:
    """Rows nothing can match, such as a hand-added note, are ignored."""
    header = "player,score,coryat,game,result,player_id,game_key,saved_game"
    assert parse_results_csv(f"{header}\nNote,,,,,,,\n") == []


@pytest.mark.parametrize(
    "header",
    [
        "player;score;coryat;game;result;player_id;game_key;saved_game",
        "player,points,coryat,game,result,player_id,game_key,saved_game",
    ],
)
def test_unreadable_results_header_is_refused(temp_dir: object, header: str) -> None:
    """A header JParty can't read is an error, so the next game can't erase it."""
    (temp_dir / RESULTS_FILE).write_text(
        f"{header}\nAnn;1;;g;win;p0;QF;s\n", encoding="utf-8"
    )
    with pytest.raises(TournamentFileError, match="column"):
        load_results(temp_dir)
    with pytest.raises(TournamentFileError):
        record_game_results(temp_dir, played(QF2, "p3", "p4", "p5"))
    assert (temp_dir / RESULTS_FILE).read_text(encoding="utf-8").startswith(header)


def test_results_saved_by_excel_as_ansi_are_refused(temp_dir: object) -> None:
    """A results.csv that isn't UTF-8 says how to fix it instead of crashing."""
    rows = [GameResult(QF1, "p0", "José", 1200, 800, "Fun-4453", "win", "save")]
    (temp_dir / RESULTS_FILE).write_bytes(results_csv_text(rows).encode("cp1252"))
    with pytest.raises(TournamentFileError, match="CSV UTF-8"):
        load_results(temp_dir)
