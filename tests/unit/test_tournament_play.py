"""Tests for playing tournament games: results and introductions."""

import pytest

from jparty.domain.tournament.advancement import Tiebreak
from jparty.domain.tournament.play import (
    INTRO_HEADING,
    SAVED_PLAYER_ID,
    SAVED_PLAYER_NAME,
    GameResult,
    PlayerOutcome,
    TournamentGameRef,
    already_recorded,
    game_results,
    introduction_line,
    introduction_lines,
    record_results,
)
from jparty.domain.tournament.roster import PlayerSlot, SignUp
from jparty.domain.tournament.store import (
    RESULTS_FILE,
    TIEBREAKS_FILE,
    TournamentFileError,
    load_results,
    load_tiebreaks,
    parse_results_csv,
    parse_tiebreaks_csv,
    record_game_results,
    record_tiebreak,
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


def test_results_header_with_spaces_after_commas_still_reads() -> None:
    """A header like "player, score, ..." keeps its rows instead of dropping them."""
    rows = [GameResult(QF1, "p0", "Ann", 1200, 800, "Fun-4453", "win", "save")]
    text = results_csv_text(rows).replace(",", ", ")
    assert parse_results_csv(text) == rows


def test_results_too_big_for_csv_are_refused() -> None:
    """A cell over the csv module's size limit is a TournamentFileError."""
    header = "player,score,coryat,game,result,player_id,game_key,saved_game"
    huge = '"' + "x" * 200_000 + '"'
    with pytest.raises(TournamentFileError, match="Couldn't read"):
        parse_results_csv(f"{header}\n{huge},1,,g,win,p0,QF,s\n")


# Tiebreaks file


def test_tiebreaks_csv_round_trips(temp_dir: object) -> None:
    """Saved tiebreakers read back, with the winner's name for people."""
    first = Tiebreak("Quarterfinals", frozenset({"e", "f"}), "f", "Fay")
    second = Tiebreak("Preliminaries", frozenset({"a", "b", "c"}), "a", "Ann")
    record_tiebreak(temp_dir, first)
    record_tiebreak(temp_dir, second)
    assert load_tiebreaks(temp_dir) == [first, second]
    assert [t.winner_name for t in load_tiebreaks(temp_dir)] == ["Fay", "Ann"]
    text = (temp_dir / TIEBREAKS_FILE).read_text(encoding="utf-8")
    assert text.splitlines()[0] == "round,winner_name,winner,players"
    assert "Quarterfinals,Fay,f,e f" in text


def test_playing_a_tie_again_replaces_its_winner(temp_dir: object) -> None:
    """The same players' tie in the same round keeps only the latest win."""
    record_tiebreak(temp_dir, Tiebreak("Quarterfinals", frozenset("ef"), "f"))
    record_tiebreak(temp_dir, Tiebreak("Semifinals", frozenset("ef"), "e"))
    record_tiebreak(temp_dir, Tiebreak("Quarterfinals", frozenset("ef"), "e"))
    assert [(t.round_name, t.winner) for t in load_tiebreaks(temp_dir)] == [
        ("Semifinals", "e"),
        ("Quarterfinals", "e"),
    ]


def test_no_tiebreaks_file_means_none_played(temp_dir: object) -> None:
    """A tournament with no tiebreakers has none."""
    assert load_tiebreaks(temp_dir) == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("round;winner;players\nQ;a;a b\n", "no round, winner, players column"),
        ("round,winner,players\nQ,z,a b\n", "line 2"),
        ("round,winner,players\n,a,a b\n", "line 2"),
    ],
)
def test_bad_tiebreaks_file_is_refused(text: str, message: str) -> None:
    """A hand-edited tiebreaks.csv that doesn't make sense says why."""
    with pytest.raises(TournamentFileError, match=message):
        parse_tiebreaks_csv(text)


def test_tiebreaks_not_saved_as_utf8_are_refused(temp_dir: object) -> None:
    """Excel's ANSI CSV is a clear error, as with results.csv."""
    (temp_dir / TIEBREAKS_FILE).write_bytes(
        "round,winner,players\nQ,é,é\n".encode("cp1252")
    )
    with pytest.raises(TournamentFileError, match="CSV UTF-8"):
        load_tiebreaks(temp_dir)
