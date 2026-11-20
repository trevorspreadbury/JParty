"""Tests for finding the saves of half-played tournament games."""

import json
from pathlib import Path

from jparty.domain.tournament_play import TournamentGameRef
from jparty.domain.tournament_saves import find_tournament_saves

SF1 = "Semifinals: SF 1"
SF2 = "Semifinals: SF 2"


def write_save(
    states_dir: Path,
    folder: str,
    game_id: str,
    game_key: str | None = SF1,
    tournament: str = "Fun",
    updated: float = 100.0,
    players: tuple[str, ...] = ("Ann", "Bob", "Cat"),
) -> Path:
    """Write a saved game's ``general.json`` and return its folder."""
    path = states_dir / folder
    path.mkdir(parents=True)
    state = {
        "game_id": game_id,
        "players": [
            {"name": f"Phone {index}", "tournament_player_name": name}
            for index, name in enumerate(players)
        ],
        "last_updated": updated,
    }
    if game_key is not None:
        state["tournament"] = TournamentGameRef(tournament, game_key).to_json()
    (path / "general.json").write_text(json.dumps(state), encoding="utf-8")
    return path


def test_finds_the_newest_save_of_each_game(temp_dir: Path) -> None:
    """Each game gets its newest save; other games and tournaments don't count."""
    write_save(temp_dir, "1111-20261119T1500", "1111", updated=100)
    newest = write_save(temp_dir, "1111-20261119T1500-2", "1111", updated=200)
    write_save(temp_dir, "1111-20261119T1600", "1111", tournament="Other")
    write_save(temp_dir, "1111-20261119T1700", "1111", game_key=None, updated=300)
    write_save(temp_dir, "11112-20261119T1500", "11112", updated=900)
    sf2 = write_save(
        temp_dir, "frankenstein-1-2-20261119T1500", "frankenstein-1-2", game_key=SF2
    )
    saves = find_tournament_saves(
        temp_dir, "Fun", {SF1: "1111", SF2: "frankenstein-1-2"}
    )
    assert set(saves) == {SF1, SF2}
    assert saves[SF1].path == newest
    assert saves[SF1].players == ("Ann", "Bob", "Cat")
    assert saves[SF2].path == sf2


def test_skips_saves_for_another_game_or_board(temp_dir: Path) -> None:
    """A save for a different bracket game or board id isn't offered."""
    write_save(temp_dir, "1111-20261119T1500", "1111", game_key=SF2)
    write_save(temp_dir, "2222-20261119T1500", "2222", game_key=SF1)
    assert find_tournament_saves(temp_dir, "Fun", {SF1: "1111"}) == {}


def test_skips_damaged_and_empty_saves(temp_dir: Path) -> None:
    """Unreadable files and saves without players are left out."""
    broken = temp_dir / "1111-20261119T1500"
    broken.mkdir()
    (broken / "general.json").write_text("{not json", encoding="utf-8")
    write_save(temp_dir, "1111-20261119T1600", "1111", players=())
    (temp_dir / "1111-20261119T1700").mkdir()
    assert find_tournament_saves(temp_dir, "Fun", {SF1: "1111"}) == {}


def test_a_missing_folder_has_no_saves(temp_dir: Path) -> None:
    """No saved games folder means no saves."""
    assert find_tournament_saves(temp_dir / "missing", "Fun", {SF1: "1111"}) == {}
