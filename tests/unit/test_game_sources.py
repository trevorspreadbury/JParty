"""Tests for the HTTP fetchers in ``jparty.services.game_sources``.

Every request is answered by ``requests-mock``, so these tests stay offline.
"""

import re

import pytest
import requests

from jparty.app import bootstrap
from jparty.services import archive_client
from jparty.services.game_loader import find_random_game
from jparty.services.game_parser import GameParser
from jparty.services.game_sources import GameSourceFetcher

pytestmark = pytest.mark.unit

CDX_URL = re.compile(r"^http://web\.archive\.org/cdx/search/cdx\?")
SNAPSHOT_URL = re.compile(r"^http://web\.archive\.org/web/")
JARCHIVE_GAME_URL = "http://www.j-archive.com/showgame.php?game_id=4453"
BAD_JARCHIVE_GAME_URL = "http://www.j-archive.com/showgame.php?game_id=9999"
SHEET_URL = re.compile(r"^https://docs\.google\.com/spreadsheet/ccc\?")
CDX_HEADER = ["urlkey", "timestamp", "original", "mimetype", "statuscode"]
CDX_ROW = [
    "com,j-archive)/showgame.php?game_id=4453",
    "20240101000000",
    "http://www.j-archive.com/showgame.php?game_id=4453",
    "text/html",
    "200",
]


@pytest.fixture
def no_saved_games(temp_dir: object, monkeypatch: object) -> None:
    """Start each load with an empty disk cache and nothing held in memory."""
    monkeypatch.setattr(archive_client, "SAVED_GAMES", temp_dir / "missing")
    monkeypatch.setattr(archive_client, "_LOADED_GAME_HTML_CACHE", {})


def test_wayback_query_only_asks_for_successful_snapshots(
    requests_mock: object, fixture_dir: object
) -> None:
    """The CDX query must skip snapshots of J-Archive error pages."""
    html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    requests_mock.get(CDX_URL, json=[CDX_HEADER, CDX_ROW])
    requests_mock.get(SNAPSHOT_URL, text=html)

    assert GameSourceFetcher().get_wayback_game_html(4453) == html

    cdx_request = requests_mock.request_history[0]
    assert "filter=statuscode:200" in cdx_request.url


def test_wayback_header_only_reply_means_no_snapshot(requests_mock: object) -> None:
    """A CDX reply with only the header row has no snapshot to fetch."""
    requests_mock.get(CDX_URL, json=[CDX_HEADER])

    with pytest.raises(ValueError, match="no games found"):
        GameSourceFetcher().get_wayback_game_html(4453)
    assert requests_mock.call_count == 1


@pytest.mark.parametrize("failing", ["cdx", "snapshot"])
def test_wayback_http_errors_raise(requests_mock: object, failing: str) -> None:
    """A Wayback rate limit must raise rather than return the error page."""
    if failing == "cdx":
        requests_mock.get(CDX_URL, status_code=429, text="Too Many Requests")
    else:
        requests_mock.get(CDX_URL, json=[CDX_HEADER, CDX_ROW])
        requests_mock.get(SNAPSHOT_URL, status_code=429, text="Too Many Requests")

    with pytest.raises(requests.HTTPError):
        GameSourceFetcher().get_wayback_game_html(4453)


def test_jarchive_http_error_raises(requests_mock: object) -> None:
    """A J-Archive error status must raise rather than return the error page."""
    requests_mock.get(JARCHIVE_GAME_URL, status_code=503, text="Unavailable")

    with pytest.raises(requests.HTTPError):
        GameSourceFetcher().get_jarchive_game_html(4453)


def test_random_game_http_error_raises(requests_mock: object) -> None:
    """A J-Archive homepage error status must raise a clear HTTP error."""
    requests_mock.get("http://j-archive.com/", status_code=429)

    with pytest.raises(requests.HTTPError):
        GameSourceFetcher().get_random_game()


def test_google_sheet_http_error_raises(requests_mock: object) -> None:
    """A Google Sheets error page must not be parsed as CSV rows."""
    requests_mock.get(SHEET_URL, status_code=404, text="<html>Not found</html>")

    with pytest.raises(requests.HTTPError):
        GameSourceFetcher().get_google_sheet_rows("abcdefg")


@pytest.mark.parametrize("failing", ["cdx", "snapshot"])
def test_get_game_falls_back_to_jarchive_when_wayback_rate_limits(
    requests_mock: object,
    fixture_dir: object,
    no_saved_games: None,
    failing: str,
) -> None:
    """An HTTP 429 from Wayback should load the game from J-Archive instead."""
    html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    if failing == "cdx":
        requests_mock.get(CDX_URL, status_code=429, text="Too Many Requests")
    else:
        requests_mock.get(CDX_URL, json=[CDX_HEADER, CDX_ROW])
        requests_mock.get(SNAPSHOT_URL, status_code=429, text="Too Many Requests")
    requests_mock.get(JARCHIVE_GAME_URL, text=html)

    game = archive_client.get_game("4453")

    assert game is not None
    assert len(game.rounds) == 3
    assert requests_mock.request_history[-1].url == JARCHIVE_GAME_URL
    assert archive_client._LOADED_GAME_HTML_CACHE["4453"] == html


def test_get_game_returns_none_when_both_sources_send_errors(
    requests_mock: object, fixture_dir: object, no_saved_games: None
) -> None:
    """With Wayback rate limited and J-Archive sending a non-game, give ``None``.

    The J-Archive page is a normal 200 response that isn't a game, such as
    the page J-Archive shows for an unknown game id.
    """
    invalid_html = (fixture_dir / "invalid_game.html").read_text(encoding="utf-8")
    requests_mock.get(CDX_URL, status_code=429)
    requests_mock.get(JARCHIVE_GAME_URL, text=invalid_html)

    assert archive_client.get_game("4453") is None
    assert archive_client._LOADED_GAME_HTML_CACHE == {}


def test_download_skips_an_id_jarchive_errors_on_and_keeps_going(
    requests_mock: object,
    fixture_dir: object,
    no_saved_games: None,
    temp_dir: object,
    monkeypatch: object,
    capsys: object,
) -> None:
    """``jparty download`` should skip an id that errors and save the next one."""
    saved_dir = temp_dir / "saved_games"
    saved_dir.mkdir()
    monkeypatch.setattr(bootstrap, "SAVED_GAMES", saved_dir)
    html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    requests_mock.get(CDX_URL, status_code=429, text="Too Many Requests")
    requests_mock.get(BAD_JARCHIVE_GAME_URL, status_code=503, text="Unavailable")
    requests_mock.get(JARCHIVE_GAME_URL, text=html)

    downloaded = bootstrap.download_games(["9999", "4453"], delay_seconds=0)

    assert downloaded == ["4453"]
    assert "Skipping 9999" in capsys.readouterr().out
    assert not (saved_dir / "9999.html").exists()
    assert (saved_dir / "4453.html").read_text(encoding="utf-8") == html


def test_random_search_treats_a_jarchive_http_error_as_one_failed_try(
    requests_mock: object, fixture_dir: object, no_saved_games: None
) -> None:
    """An HTTP error for one random game should cost a try, not end the search."""
    html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    requests_mock.get(CDX_URL, status_code=429, text="Too Many Requests")
    requests_mock.get(BAD_JARCHIVE_GAME_URL, status_code=503, text="Unavailable")
    requests_mock.get(JARCHIVE_GAME_URL, text=html)
    game_ids = iter(["9999", "4453"])

    game_id, data = find_random_game(
        lambda data: True,
        max_attempts=2,
        pick_game_id=lambda: next(game_ids),
        load_game=archive_client.get_game,
    )

    assert game_id == "4453"
    assert data is not None
    assert len(data.rounds) == 3


def test_google_sheet_rows_handle_crlf_and_multiline_cells(
    requests_mock: object,
) -> None:
    """CRLF endings and line breaks inside quoted cells must not shift rows.

    The body starts with a UTF-8 byte-order mark, as Sheets exports can, and
    the CRLF after the first row straddles a 512-byte boundary, where the old
    line-by-line reader split it and added an empty row.
    """
    first_cell = "x" * 506
    content = (
        b"\xef\xbb\xbf"
        + (
            f'{first_cell},a\r\n200,"What is\r\na two-line clue?",b\r\n400,plain,c\r\n'
        ).encode()
    )
    assert content[511:513] == b"\r\n"
    requests_mock.get(SHEET_URL, content=content)

    rows = GameSourceFetcher().get_google_sheet_rows("abcdefg")

    assert rows == [
        [first_cell, "a"],
        ["200", "What is\r\na two-line clue?", "b"],
        ["400", "plain", "c"],
    ]


def test_findanswer_returns_blank_for_a_clue_with_no_response() -> None:
    """A clue without a recorded response should not raise ``IndexError``."""
    clue = '<td class="clue"><div class="clue_text">No answer here</div></td>'

    assert GameParser().findanswer(clue) == ""
