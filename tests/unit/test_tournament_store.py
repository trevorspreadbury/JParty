"""Unit tests for tournament folders: stable player ids and all-or-nothing saves."""

from pathlib import Path

import pytest

from jparty.domain.tournament.dropouts import DROP_SLIDE, Dropout
from jparty.domain.tournament.play import GameResult
from jparty.domain.tournament.roster import PlayerSlot
from jparty.domain.tournament.setup import BracketSettings, TournamentBoard
from jparty.domain.tournament.store import (
    DROPOUTS_FILE,
    PLAYERS_FILE,
    RESULTS_FILE,
    TOURNAMENT_FILE,
    VOIDED_RESULTS_FILE,
    TournamentData,
    TournamentFileError,
    TournamentSettings,
    load_tournament,
    load_tournament_data,
    save_results,
    save_tournament,
    save_tournament_data,
)
from jparty.services import game_cache

pytestmark = pytest.mark.unit

QF1 = "Quarterfinals: QF 1"


def result(player_id: str, score: int, won: bool) -> GameResult:
    """Return one QF 1 result row."""
    return GameResult(
        QF1,
        player_id,
        player_id.upper(),
        score,
        None,
        "Fun-1",
        "win" if won else "loss",
    )


def test_hand_made_roster_gets_ids_that_stay_put(temp_dir: Path) -> None:
    """Ids made for rows without one are saved, so every load agrees."""
    save_tournament(temp_dir, TournamentSettings("Fun"), [PlayerSlot("Ann")])
    players = temp_dir / "Fun" / PLAYERS_FILE
    players.write_text("actual_name,player_id\nAnn,\nBob,abc\nBobby,abc\n", "utf-8")

    first = [slot.player_id for slot in load_tournament(temp_dir / "Fun")[1]]
    second = [slot.player_id for slot in load_tournament(temp_dir / "Fun")[1]]

    assert first == second
    assert first[1] == "abc"
    assert len(set(first)) == 3
    text = players.read_text("utf-8")
    assert all(player_id in text for player_id in first)


def test_roster_with_every_id_is_not_rewritten(temp_dir: Path) -> None:
    """A players.csv that already has its ids is left as it is."""
    save_tournament(temp_dir, TournamentSettings("Fun"), [PlayerSlot("Ann")])
    players = temp_dir / "Fun" / PLAYERS_FILE
    players.write_text("actual_name,player_id\nAnn,a1\n", "utf-8")

    load_tournament(temp_dir / "Fun")

    assert players.read_text("utf-8") == "actual_name,player_id\nAnn,a1\n"


def test_unwritable_new_ids_are_an_error(
    temp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ids that can't be saved would change next time, so loading fails."""
    save_tournament(temp_dir, TournamentSettings("Fun"), [PlayerSlot("Ann")])
    (temp_dir / "Fun" / PLAYERS_FILE).write_text("actual_name\nAnn\n", "utf-8")

    def locked(source: Path, destination: Path) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(game_cache, "_replace_with_retry", locked)
    with pytest.raises(TournamentFileError, match="new player ids"):
        load_tournament(temp_dir / "Fun")


@pytest.mark.parametrize("locked", [RESULTS_FILE, TOURNAMENT_FILE])
def test_failed_dropout_save_leaves_every_file_as_it_was(
    temp_dir: Path, monkeypatch: pytest.MonkeyPatch, locked: str
) -> None:
    """A locked file mid-save puts the other files, and the boards, back too.

    tournament.json is written last, after the in-memory boards have been
    changed, so locking it checks that they're put back as well.
    """
    slots = [PlayerSlot(name, player_id=name) for name in ("a", "b", "c")]
    settings = TournamentSettings(
        "Fun",
        boards={
            QF1: TournamentBoard("B", ({"game_id": "1", "source_round_index": 0},))
        },
    )
    folder = save_tournament(temp_dir, settings, slots)
    rows = [result("a", 900, True), result("b", 500, False), result("c", 100, False)]
    save_results(folder, rows)
    names = (
        VOIDED_RESULTS_FILE,
        DROPOUTS_FILE,
        RESULTS_FILE,
        PLAYERS_FILE,
        TOURNAMENT_FILE,
    )
    before = {
        name: (folder / name).read_bytes() for name in names if (folder / name).exists()
    }

    settings, data = load_tournament_data(folder)
    changed = TournamentData(
        BracketSettings(),
        data.slots[:2],
        tuple(rows[:2]),
        dropouts=(Dropout("c", "Quarterfinals", DROP_SLIDE),),
        voided=(rows[2],),
    )
    real_replace = game_cache._replace_with_retry

    def lock(source: Path, destination: Path) -> None:
        if destination.name == locked:
            raise PermissionError(f"{locked} is open in another program")
        real_replace(source, destination)

    monkeypatch.setattr(game_cache, "_replace_with_retry", lock)
    with pytest.raises(TournamentFileError, match="nothing changed"):
        save_tournament_data(folder, settings, changed)

    after = {
        name: (folder / name).read_bytes() for name in names if (folder / name).exists()
    }
    assert after == before
    assert list(settings.boards) == [QF1]
    assert not list(folder.glob("*.tmp"))
