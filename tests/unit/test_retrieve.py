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
