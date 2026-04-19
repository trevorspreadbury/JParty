import csv
from pathlib import Path

import pytest

from jparty.services import archive_client as retrieve

pytestmark = pytest.mark.unit


def test_get_game_html_prefers_saved_local_html(temp_dir, monkeypatch):
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


def test_get_game_html_falls_back_to_wayback(temp_dir, monkeypatch):
    monkeypatch.setattr(retrieve, "SAVED_GAMES", temp_dir / "missing")
    monkeypatch.setattr(
        retrieve, "get_wayback_game_html", lambda game_id: "<html>wayback</html>"
    )

    assert retrieve.get_game_html(1234) == "<html>wayback</html>"


def test_get_game_html_falls_back_to_jarchive_when_wayback_fails(temp_dir, monkeypatch):
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


def test_list_to_game_parses_custom_game_csv(sample_custom_game_csv_text):
    rows = list(csv.reader(sample_custom_game_csv_text.splitlines()))

    game = retrieve.list_to_game(rows)

    assert len(game.rounds) == 3
    assert game.rounds[0].categories[0] == "VIDEO GAMES"
    assert game.rounds[0].get_question(0, 0).text == "Mario's first console"
    assert game.rounds[0].get_question(0, 0).dd is True
    assert game.rounds[1].get_question(1, 1).text == "US Civil War ended"
    assert game.rounds[2].question.answer == "Final response"
    assert game.date == "January 1, 2026"


def test_process_game_board_from_saved_html_parses_real_fixture():
    html = (Path("tests") / "fixtures" / "4453.html").read_text(encoding="utf-8")

    game = retrieve.process_game_board_from_html(html, 4453)

    assert game is not None
    assert len(game.rounds) == 3
    assert len(game.rounds[0].questions) == 30
    assert len(game.rounds[1].questions) == 30
    assert game.rounds[2].category


def test_process_game_board_from_invalid_html_returns_none(fixture_dir):
    invalid_html = (fixture_dir / "invalid_game.html").read_text()

    assert retrieve.process_game_board_from_html(invalid_html, 9999) is None


def test_find_question_media_returns_matching_file(temp_dir, monkeypatch):
    media_root = temp_dir / "question_media"
    game_media_dir = media_root / "1234"
    game_media_dir.mkdir(parents=True)
    media_file = game_media_dir / "1-0-0.png"
    media_file.write_bytes(b"fake")
    monkeypatch.setattr(retrieve, "QUESTION_MEDIA", media_root)

    assert retrieve.find_question_media(1234, 1, (0, 0)) == str(media_file)


def test_get_game_uses_gsheet_for_long_ids(monkeypatch):
    called = {}

    def fake_get_gsheet_game(file_id):
        called["id"] = file_id
        return "sentinel"

    monkeypatch.setattr(retrieve, "get_Gsheet_game", fake_get_gsheet_game)

    result = retrieve.get_game("1234567")

    assert called["id"] == "1234567"
    assert result == "sentinel"
