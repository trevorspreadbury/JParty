"""Test retrieve module."""

import csv
from pathlib import Path

import pytest

from jparty.services import archive_client as retrieve

pytestmark = pytest.mark.unit


def test_get_game_html_prefers_saved_local_html(
    temp_dir: object, monkeypatch: object
) -> None:
    """Test test get game html prefers saved local html."""
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    expected_html = "<html>saved</html>"
    (saved_dir / "1234.html").write_text(expected_html)
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(
        retrieve,
        "get_wayback_game_html",
        lambda game_id: pytest.fail("wayback should not be called"),
    )
    monkeypatch.setattr(
        retrieve,
        "get_jarchive_game_html",
        lambda game_id: pytest.fail("j-archive should not be called"),
    )
    assert retrieve.get_game_html(1234) == expected_html


def test_get_game_html_falls_back_to_wayback(
    temp_dir: object, monkeypatch: object
) -> None:
    """Test test get game html falls back to wayback."""
    monkeypatch.setattr(retrieve, "SAVED_GAMES", temp_dir / "missing")
    monkeypatch.setattr(
        retrieve, "get_wayback_game_html", lambda game_id: "<html>wayback</html>"
    )
    assert retrieve.get_game_html(1234) == "<html>wayback</html>"


def test_get_game_html_falls_back_to_jarchive_when_wayback_fails(
    temp_dir: object, monkeypatch: object
) -> None:
    """Test test get game html falls back to jarchive when wayback fails."""
    monkeypatch.setattr(retrieve, "SAVED_GAMES", temp_dir / "missing")
    monkeypatch.setattr(
        retrieve,
        "get_wayback_game_html",
        lambda game_id: (_ for _ in ()).throw(RuntimeError("wayback failed")),
    )
    monkeypatch.setattr(
        retrieve, "get_jarchive_game_html", lambda game_id: "<html>jarchive</html>"
    )
    assert retrieve.get_game_html(1234) == "<html>jarchive</html>"


def test_list_to_game_parses_custom_game_csv(
    sample_custom_game_csv_text: object,
) -> None:
    """Test test list to game parses custom game csv."""
    rows = list(csv.reader(sample_custom_game_csv_text.splitlines()))
    game = retrieve.list_to_game(rows)
    assert len(game.rounds) == 3
    assert game.rounds[0].categories[0] == "VIDEO GAMES"
    assert game.rounds[0].get_question(0, 0).text == "Mario's first console"
    assert game.rounds[0].get_question(0, 0).dd is True
    assert game.rounds[1].get_question(1, 1).text == "US Civil War ended"
    assert game.rounds[2].question.answer == "Final response"
    assert game.date == "January 1, 2026"


def test_process_game_board_from_saved_html_parses_real_fixture() -> None:
    """Test test process game board from saved html parses real fixture."""
    html = (Path("tests") / "fixtures" / "4453.html").read_text(encoding="utf-8")
    game = retrieve.process_game_board_from_html(html, 4453)
    assert game is not None
    assert len(game.rounds) == 3
    assert len(game.rounds[0].questions) == 30
    assert len(game.rounds[1].questions) == 30
    assert game.rounds[2].category


def test_process_game_board_from_html_keeps_third_standard_round() -> None:
    """Test HTML parsing keeps extra standard rounds before Final Jeopardy."""
    html = """
    <html>
      <div id="game_title"><h1>Show #7447 - Celebrity Jeopardy!, January 1, 2026</h1></div>
      <div id="game_comments">Celebrity game</div>
      <table class="round" id="round_1">
        <td class="category"><td class="category_name">Round 1</td></td>
        <td class="category"><td class="category_name">Round 1</td></td>
        <td class="category"><td class="category_name">Round 1</td></td>
        <td class="category"><td class="category_name">Round 1</td></td>
        <td class="category"><td class="category_name">Round 1</td></td>
        <td class="category"><td class="category_name">Round 1</td></td>
        <td class="clue"><td class="clue_text" id="clue_J_1_1">Q1</td><td class="clue_value">$200</td><em class="correct_response">A1</em></td>
      </table>
      <table class="round" id="round_2">
        <td class="category"><td class="category_name">Round 2</td></td>
        <td class="category"><td class="category_name">Round 2</td></td>
        <td class="category"><td class="category_name">Round 2</td></td>
        <td class="category"><td class="category_name">Round 2</td></td>
        <td class="category"><td class="category_name">Round 2</td></td>
        <td class="category"><td class="category_name">Round 2</td></td>
        <td class="clue"><td class="clue_text" id="clue_DJ_1_1">Q2</td><td class="clue_value">$400</td><em class="correct_response">A2</em></td>
      </table>
      <table class="round" id="round_3">
        <td class="category"><td class="category_name">Round 3</td></td>
        <td class="category"><td class="category_name">Round 3</td></td>
        <td class="category"><td class="category_name">Round 3</td></td>
        <td class="category"><td class="category_name">Round 3</td></td>
        <td class="category"><td class="category_name">Round 3</td></td>
        <td class="category"><td class="category_name">Round 3</td></td>
        <td class="clue"><td class="clue_text" id="clue_TJ_1_1">Q3</td><td class="clue_value">$600</td><em class="correct_response">A3</em></td>
      </table>
      <table class="final_round">
        <td class="category"><td class="category_name">Final Category</td></td>
        <td class="clue"><td class="clue_text">Final clue</td><em class="correct_response">Final answer</em></td>
      </table>
    </html>
    """
    game = retrieve.process_game_board_from_html(html, 7447)
    assert game is not None
    assert len(game.rounds) == 4
    assert game.rounds[2].get_question(0, 0).value == 600
    assert game.rounds[3].category == "Final Category"


def test_process_game_board_from_html_allows_missing_standard_clues() -> None:
    """Test parsing keeps a game playable when a standard clue is missing."""
    html = """
    <html>
      <div id="game_title"><h1>Show #9999 - Jeopardy!, January 1, 2026</h1></div>
      <div id="game_comments">Incomplete game</div>
      <table class="round" id="round_1">
        <td class="category"><td class="category_name">Cat 1</td></td>
        <td class="category"><td class="category_name">Cat 2</td></td>
        <td class="category"><td class="category_name">Cat 3</td></td>
        <td class="category"><td class="category_name">Cat 4</td></td>
        <td class="category"><td class="category_name">Cat 5</td></td>
        <td class="category"><td class="category_name">Cat 6</td></td>
        <td class="clue"><td class="clue_text" id="clue_J_1_1">Q1</td><td class="clue_value">$200</td><em class="correct_response">A1</em></td>
        <td class="clue"><td class="clue_value">$400</td></td>
      </table>
      <table class="round" id="round_2">
        <td class="category"><td class="category_name">Cat 1</td></td>
        <td class="category"><td class="category_name">Cat 2</td></td>
        <td class="category"><td class="category_name">Cat 3</td></td>
        <td class="category"><td class="category_name">Cat 4</td></td>
        <td class="category"><td class="category_name">Cat 5</td></td>
        <td class="category"><td class="category_name">Cat 6</td></td>
        <td class="clue"><td class="clue_text" id="clue_DJ_1_1">Q2</td><td class="clue_value">$400</td><em class="correct_response">A2</em></td>
      </table>
      <table class="final_round">
        <td class="category"><td class="category_name">Final Category</td></td>
        <td class="clue"><td class="clue_text">Final clue</td><em class="correct_response">Final answer</em></td>
      </table>
    </html>
    """
    game = retrieve.process_game_board_from_html(html, 9999)
    assert game is not None
    assert len(game.rounds) == 3
    assert game.missing_question_count() == 58


def test_process_game_board_from_invalid_html_returns_none(fixture_dir: object) -> None:
    """Test test process game board from invalid html returns none."""
    invalid_html = (fixture_dir / "invalid_game.html").read_text()
    assert retrieve.process_game_board_from_html(invalid_html, 9999) is None


def test_find_question_media_returns_matching_file(
    temp_dir: object, monkeypatch: object
) -> None:
    """Test test find question media returns matching file."""
    media_root = temp_dir / "question_media"
    game_media_dir = media_root / "1234"
    game_media_dir.mkdir(parents=True)
    media_file = game_media_dir / "1-0-0.png"
    media_file.write_bytes(b"fake")
    monkeypatch.setattr(retrieve, "QUESTION_MEDIA", media_root)
    assert retrieve.find_question_media(1234, 1, (0, 0)) == str(media_file)


def test_get_game_uses_gsheet_for_long_ids(monkeypatch: object) -> None:
    """Test test get game uses gsheet for long ids."""
    called = {}

    def fake_get_gsheet_game(file_id: object) -> str:
        """Test fake get gsheet game."""
        called["id"] = file_id
        return "sentinel"

    monkeypatch.setattr(retrieve, "get_Gsheet_game", fake_get_gsheet_game)
    result = retrieve.get_game("1234567")
    assert called["id"] == "1234567"
    assert result == "sentinel"


def test_save_game_html_uses_cached_html_and_writes_file(
    temp_dir: object, monkeypatch: object
) -> None:
    """Test test save game html uses cached html and writes file."""
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(
        retrieve,
        "_LOADED_GAME_HTML_CACHE",
        {"4453": "<html>cached game</html>"},
    )
    monkeypatch.setattr(
        retrieve,
        "get_game_html",
        lambda game_id: pytest.fail("cached HTML should be used"),
    )
    saved_path = retrieve.save_game_html(4453)
    assert saved_path == saved_dir / "4453.html"
    assert saved_path.read_text(encoding="utf-8") == "<html>cached game</html>"


def _block_network(monkeypatch: object) -> None:
    """Make any remote fetch fail the test."""
    monkeypatch.setattr(
        retrieve,
        "get_wayback_game_html",
        lambda game_id: pytest.fail("wayback should not be called"),
    )
    monkeypatch.setattr(
        retrieve,
        "get_jarchive_game_html",
        lambda game_id: pytest.fail("j-archive should not be called"),
    )


def test_get_game_parses_cached_html_without_network(
    temp_dir: object, monkeypatch: object, fixture_dir: object
) -> None:
    """A good cached copy should be parsed without any remote fetch."""
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    (saved_dir / "4453.html").write_text(html, encoding="utf-8")
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {})
    _block_network(monkeypatch)

    game = retrieve.get_game("4453")

    assert game is not None
    assert len(game.rounds) == 3


def test_get_game_reparses_html_fetched_this_session_without_network(
    temp_dir: object, monkeypatch: object, fixture_dir: object
) -> None:
    """An unsaved game fetched earlier is reparsed from memory, not refetched (#66)."""
    html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    monkeypatch.setattr(retrieve, "SAVED_GAMES", temp_dir / "missing")
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {"4453": html})
    _block_network(monkeypatch)

    game = retrieve.get_game("4453")

    assert game is not None
    assert len(game.rounds) == 3


def test_get_game_fetches_when_html_in_memory_is_not_a_game(
    temp_dir: object, monkeypatch: object, fixture_dir: object
) -> None:
    """A non-game page held in memory falls back to a network fetch."""
    html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    calls = []

    def fake_wayback(game_id: object) -> str:
        calls.append(game_id)
        return html

    monkeypatch.setattr(retrieve, "SAVED_GAMES", temp_dir / "missing")
    monkeypatch.setattr(
        retrieve, "_LOADED_GAME_HTML_CACHE", {"4453": "<html>rate limited</html>"}
    )
    monkeypatch.setattr(retrieve, "get_wayback_game_html", fake_wayback)

    game = retrieve.get_game("4453")

    assert calls == ["4453"]
    assert game is not None
    assert retrieve._LOADED_GAME_HTML_CACHE["4453"] == html


def test_get_game_returns_none_for_unparseable_remote_html(
    temp_dir: object, monkeypatch: object, fixture_dir: object
) -> None:
    """A fetched page that is not a game should return ``None``, not raise."""
    invalid_html = (fixture_dir / "invalid_game.html").read_text(encoding="utf-8")
    monkeypatch.setattr(retrieve, "SAVED_GAMES", temp_dir / "missing")
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {})
    monkeypatch.setattr(retrieve, "get_wayback_game_html", lambda game_id: invalid_html)

    assert retrieve.get_game("9999") is None


def test_get_game_propagates_google_sheet_failures(monkeypatch: object) -> None:
    """Sheet fetch errors should reach the caller so the UI can report them."""

    def failing_rows(file_id: object) -> object:
        """Simulate a failed Google Sheets download."""
        raise RuntimeError("sheets failed")

    monkeypatch.setattr(retrieve._FETCHER, "get_google_sheet_rows", failing_rows)
    with pytest.raises(RuntimeError, match="sheets failed"):
        retrieve.get_game("abcdefg")


def test_get_game_refetches_and_overwrites_truncated_cache(
    temp_dir: object, monkeypatch: object, fixture_dir: object
) -> None:
    """A cut-off cache file should be fetched again and replaced."""
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    full_html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    cut_off_html = full_html[: len(full_html) // 2]
    (saved_dir / "4453.html").write_text(cut_off_html, encoding="utf-8")
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {})
    fetched = []

    def fake_wayback(game_id: object) -> str:
        """Return the full page and record the fetch."""
        fetched.append(game_id)
        return full_html

    monkeypatch.setattr(retrieve, "get_wayback_game_html", fake_wayback)

    game = retrieve.get_game("4453")

    assert fetched == ["4453"]
    assert game is not None
    assert len(game.rounds) == 3
    assert (saved_dir / "4453.html").read_text(encoding="utf-8") == full_html


def test_get_game_refetches_cache_that_does_not_parse(
    temp_dir: object, monkeypatch: object, fixture_dir: object
) -> None:
    """A cached copy that does not parse should be replaced by the network copy."""
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    full_html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    (saved_dir / "4453.html").write_text("<html>junk</html>", encoding="utf-8")
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {})
    monkeypatch.setattr(retrieve, "get_wayback_game_html", lambda game_id: full_html)

    game = retrieve.get_game("4453")

    assert game is not None
    assert (saved_dir / "4453.html").read_text(encoding="utf-8") == full_html


def test_get_game_keeps_damaged_cache_when_refetch_fails(
    temp_dir: object, monkeypatch: object
) -> None:
    """If the network is down, a damaged cache file is left untouched."""
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    (saved_dir / "4453.html").write_text("<html>junk</html>", encoding="utf-8")
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {})

    def offline(game_id: object) -> str:
        """Simulate no network."""
        raise ConnectionError("offline")

    monkeypatch.setattr(retrieve, "get_wayback_game_html", offline)
    monkeypatch.setattr(retrieve, "get_jarchive_game_html", offline)

    assert retrieve.get_game("4453") is None
    assert (saved_dir / "4453.html").read_text(encoding="utf-8") == (
        "<html>junk</html>"
    )


def _cache_without_closing_tag(fixture_dir: object, saved_dir: object) -> str:
    """Write a cached 4453 page that parses but is missing ``</html>``."""
    full_html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    head, _, tail = full_html.rpartition("</html>")
    cached_html = head + tail
    (saved_dir / "4453.html").write_text(cached_html, encoding="utf-8")
    return cached_html


def test_get_game_keeps_cached_game_when_refetch_is_not_a_game(
    temp_dir: object, monkeypatch: object, fixture_dir: object
) -> None:
    """A refetch that returns a non-game page must not lose a cache that parsed.

    J-Archive rate-limit and error pages come back as normal responses, so the
    fetch succeeds but the page isn't a game.
    """
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    cached_html = _cache_without_closing_tag(fixture_dir, saved_dir)
    invalid_html = (fixture_dir / "invalid_game.html").read_text(encoding="utf-8")
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {})
    monkeypatch.setattr(retrieve, "get_wayback_game_html", lambda game_id: invalid_html)

    game = retrieve.get_game("4453")

    assert game is not None
    assert len(game.rounds) == 3
    assert (saved_dir / "4453.html").read_text(encoding="utf-8") == cached_html
    assert retrieve._LOADED_GAME_HTML_CACHE["4453"] == cached_html


def test_get_game_keeps_cached_game_when_refetch_fails_to_parse(
    temp_dir: object, monkeypatch: object, fixture_dir: object
) -> None:
    """A refetched page that makes the parser raise falls back to the cache."""
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    cached_html = _cache_without_closing_tag(fixture_dir, saved_dir)
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {})
    monkeypatch.setattr(retrieve, "get_wayback_game_html", lambda game_id: "BROKEN")
    real_parse = retrieve.process_game_board_from_html

    def parse(game_html: object, game_id: object) -> object:
        """Raise for the refetched page only."""
        if game_html == "BROKEN":
            raise ValueError("unexpected page layout")
        return real_parse(game_html, game_id)

    monkeypatch.setattr(retrieve, "process_game_board_from_html", parse)

    game = retrieve.get_game("4453")

    assert game is not None
    assert (saved_dir / "4453.html").read_text(encoding="utf-8") == cached_html


def test_get_game_repairs_cache_that_is_not_valid_utf8(
    temp_dir: object, monkeypatch: object, fixture_dir: object
) -> None:
    """A cache file cut off mid-character is replaced after one good fetch.

    Before, the unreadable file looked like "no cache", so it was never
    overwritten and every later load needed the network.
    """
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    full_html = (fixture_dir / "4453.html").read_text(encoding="utf-8")
    full_bytes = full_html.encode("utf-8")
    # The first two bytes of an em dash: a multi-byte character cut in half.
    (saved_dir / "4453.html").write_bytes(
        full_bytes[: len(full_bytes) // 2] + b"\xe2\x80"
    )
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {})
    monkeypatch.setattr(retrieve, "get_wayback_game_html", lambda game_id: full_html)

    assert retrieve.get_game("4453") is not None
    assert (saved_dir / "4453.html").read_text(encoding="utf-8") == full_html

    # The repaired copy now loads offline.
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {})
    _block_network(monkeypatch)
    assert retrieve.get_game("4453") is not None


def test_get_game_leaves_unreadable_cache_when_offline(
    temp_dir: object, monkeypatch: object
) -> None:
    """With no network, an unreadable cache file gives ``None`` and is kept."""
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    damaged = b"<html>\xe2\x80"
    (saved_dir / "4453.html").write_bytes(damaged)
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {})

    def offline(game_id: object) -> str:
        """Simulate no network."""
        raise ConnectionError("offline")

    monkeypatch.setattr(retrieve, "get_wayback_game_html", offline)
    monkeypatch.setattr(retrieve, "get_jarchive_game_html", offline)

    assert retrieve.get_game("4453") is None
    assert (saved_dir / "4453.html").read_bytes() == damaged
    assert "4453" not in retrieve._LOADED_GAME_HTML_CACHE


def test_save_game_html_fetches_when_not_loaded(
    temp_dir: object, monkeypatch: object
) -> None:
    """Saving a game that was never loaded should fetch it, then write it."""
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(retrieve, "_LOADED_GAME_HTML_CACHE", {})
    monkeypatch.setattr(
        retrieve, "get_wayback_game_html", lambda game_id: "<html>wayback</html>"
    )

    saved_path = retrieve.save_game_html("4453")

    assert saved_path.read_text(encoding="utf-8") == "<html>wayback</html>"


def test_save_game_html_skips_google_sheet_ids(
    temp_dir: object, monkeypatch: object
) -> None:
    """Google Sheets ids have no HTML to cache."""
    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    _block_network(monkeypatch)

    assert retrieve.save_game_html("abcdefg") is None
    assert list(saved_dir.iterdir()) == []


def test_save_game_html_leaves_no_partial_file_when_write_fails(
    temp_dir: object, monkeypatch: object
) -> None:
    """A write that fails before the final rename leaves no file behind."""
    from jparty.services import game_cache

    saved_dir = temp_dir / "saved"
    saved_dir.mkdir()
    monkeypatch.setattr(retrieve, "SAVED_GAMES", saved_dir)
    monkeypatch.setattr(
        retrieve, "_LOADED_GAME_HTML_CACHE", {"4453": "<html>game</html>"}
    )

    def failing_replace(source: object, destination: object) -> None:
        """Simulate the process failing before the final rename."""
        raise OSError("disk full")

    monkeypatch.setattr(game_cache.os, "replace", failing_replace)

    with pytest.raises(OSError, match="disk full"):
        retrieve.save_game_html("4453")
    assert list(saved_dir.iterdir()) == []
