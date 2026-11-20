"""Tests for finding the saves of half-played tournament games."""

import json
from pathlib import Path

from jparty.domain.roster import PlayerSlot
from jparty.domain.tournament_advancement import Eligibility
from jparty.domain.tournament_dropouts import DROP_REPLACE, Dropout
from jparty.domain.tournament_play import GameResult, TournamentGameRef
from jparty.domain.tournament_saves import (
    TournamentSave,
    find_tournament_saves,
    resume_problem,
    saved_game_problem,
    tournament_save,
)
from jparty.domain.tournament_store import (
    TournamentSettings,
    save_results,
    save_tournament,
)

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
            {
                "name": f"Phone {index}",
                "tournament_player_id": f"id-{name}",
                "tournament_player_name": name,
            }
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
    assert saves[SF1].player_ids == ("id-Ann", "id-Bob", "id-Cat")
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


def _save(path: Path, ids: tuple[str, ...] = ("a", "b", "c")) -> TournamentSave:
    """Return a save of SF 1 whose players have ``ids``."""
    return TournamentSave(SF1, path, 1.0, tuple(i.upper() for i in ids), ids)


def _row(player_id: str, saved_game: str) -> GameResult:
    """Return one SF 1 result row from ``saved_game``."""
    return GameResult(
        SF1, player_id, player_id.upper(), 100, 100, "Fun-1", "win", saved_game
    )


ANYONE = Eligibility(("a", "b", "c", "d"))


def test_resume_problem_allows_eligible_players(temp_dir: Path) -> None:
    """A save whose players may all still play can be resumed."""
    assert resume_problem(_save(temp_dir / "s1"), ANYONE, (), {}) is None


def test_resume_problem_allows_a_save_whose_own_results_are_logged(
    temp_dir: Path,
) -> None:
    """A finished save ends again and keeps its rows, so it isn't refused."""
    results = [_row("a", "s1")]
    assert (
        resume_problem(_save(temp_dir / "s1"), Eligibility(), (), {}, results) is None
    )


def test_resume_problem_refuses_a_game_with_another_saves_results(
    temp_dir: Path,
) -> None:
    """Resuming would log over the results of the save that was finished."""
    problem = resume_problem(_save(temp_dir / "s1"), ANYONE, (), {}, [_row("a", "s2")])
    assert problem.startswith(f"{SF1} already has results from another saved game")
    assert "(s2)" in problem


def test_resume_problem_refuses_a_dropped_player(temp_dir: Path) -> None:
    """A saved player who dropped out stops the resume, named by roster name."""
    dropouts = [Dropout("b", "Semifinals", DROP_REPLACE, other_id="d")]
    problem = resume_problem(_save(temp_dir / "s1"), ANYONE, dropouts, {"b": "Bea"})
    assert problem.startswith("Bea dropped out")


def test_resume_problem_refuses_a_player_who_cant_play(temp_dir: Path) -> None:
    """A saved player no longer eligible for the game stops the resume."""
    problem = resume_problem(_save(temp_dir / "s1"), Eligibility(("a", "b")), (), {})
    assert problem == (
        f"C can no longer play {SF1}, so this game can't be resumed. "
        "Start it again with new players."
    )


def test_resume_problem_reports_a_waiting_game(temp_dir: Path) -> None:
    """A game that can't be seated yet says why."""
    waiting = Eligibility(waiting="The Preliminaries aren't finished.")
    problem = resume_problem(_save(temp_dir / "s1"), waiting, (), {})
    assert problem == "The Preliminaries aren't finished."


def test_resume_problem_needs_player_ids(temp_dir: Path) -> None:
    """A save without tournament player ids can't be matched to the roster."""
    problem = resume_problem(_save(temp_dir / "s1", ("a", "", "c")), ANYONE, (), {})
    assert problem == "This save doesn't say which tournament players it has."


def test_saved_game_problem_checks_the_tournament_on_disk(temp_dir: Path) -> None:
    """The Load Saved check reads the tournament's results and dropouts."""
    slots = [PlayerSlot(name.upper(), player_id=name) for name in "abcdefghi"]
    folder = save_tournament(temp_dir, TournamentSettings("Fun"), slots)
    save = _save(temp_dir / "s1")
    assert saved_game_problem(folder, save) is None
    save_results(folder, [_row("d", "s2")])
    assert "already has results" in saved_game_problem(folder, save)


def test_saved_game_problem_skips_an_unreadable_tournament(temp_dir: Path) -> None:
    """A tournament that can't be read isn't checked; logging warns later."""
    assert saved_game_problem(temp_dir / "missing", _save(temp_dir / "s1")) is None


def test_tournament_save_reads_a_saves_players(temp_dir: Path) -> None:
    """A tournament game's general.json becomes a TournamentSave."""
    path = write_save(temp_dir, "1111-20260101T1200", "1111")
    state = json.loads((path / "general.json").read_text(encoding="utf-8"))
    save = tournament_save(path, state)
    assert save == TournamentSave(
        SF1, path, 100.0, ("Ann", "Bob", "Cat"), ("id-Ann", "id-Bob", "id-Cat")
    )
    del state["tournament"]
    assert tournament_save(path, state) is None
