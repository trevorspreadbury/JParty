"""Test that every history reader and writer handles a damaged history file."""

import json
from pathlib import Path

import pytest

from jparty.app import bootstrap
from jparty.domain.state import (
    HistoryFileError,
    build_end_game_summary,
    history_score_totals,
    read_history_file,
)

pytestmark = pytest.mark.integration


def _cut_off_last_line(saved_dir: Path) -> Path:
    """Truncate the history file partway through its last line."""
    history_file = saved_dir / "question_history.jsonl"
    lines = history_file.read_text(encoding="utf-8").splitlines()
    history_file.write_text(
        "\n".join(lines[:-1]) + "\n" + lines[-1][:60], encoding="utf-8"
    )
    return history_file


@pytest.fixture
def broken_saved_game_dir(sample_saved_game_dir: Path) -> Path:
    """Return a saved game whose last history line was cut off."""
    _cut_off_last_line(sample_saved_game_dir)
    return sample_saved_game_dir


@pytest.fixture
def warnings_shown(game: object, monkeypatch: object) -> list[tuple[str, str]]:
    """Capture host warning dialogs instead of showing them."""
    shown = []
    monkeypatch.setattr(
        game, "show_host_warning", lambda title, text: shown.append((title, text))
    )
    return shown


def _patch_get_game(monkeypatch: object, data: object) -> None:
    """Serve ``data`` for every game id lookup."""
    from jparty.services import game_loader

    monkeypatch.setattr(game_loader, "get_game", lambda game_id: data)


def test_resume_reports_cut_off_history(
    game: object, monkeypatch: object, broken_saved_game_dir: Path
) -> None:
    """Test Load Saved fails with the history error instead of resetting scores."""
    _patch_get_game(monkeypatch, game.data)
    with pytest.raises(HistoryFileError) as excinfo:
        game.prepare_resume_from_dir(broken_saved_game_dir)
    assert excinfo.value.line_number == 3
    assert "Fix or delete that line" in str(excinfo.value)
    assert game._resume_state is None


def test_resume_checks_history_before_fetching_the_game(
    game: object, monkeypatch: object, broken_saved_game_dir: Path
) -> None:
    """Test a damaged save fails before the game is fetched or state changes."""
    from jparty.services import game_loader

    fetched = []
    monkeypatch.setattr(game_loader, "get_game", fetched.append)
    data_before = game.data
    with pytest.raises(HistoryFileError):
        game.prepare_resume_from_dir(broken_saved_game_dir)
    assert fetched == []
    assert game.data is data_before


def test_end_game_summary_reports_cut_off_history(
    game: object, broken_saved_game_dir: Path, warnings_shown: list
) -> None:
    """Test the summary warns the host and still lets them close the game."""
    game._game_state_dir = broken_saved_game_dir
    with pytest.raises(HistoryFileError):
        build_end_game_summary(game)

    game.generate_final_score_graphs()

    assert warnings_shown and warnings_shown[0][0] == "Saved Clue History Error"
    assert "Line 3:" in warnings_shown[0][1]
    assert game.main_display.loaded_end_game_summaries == []
    assert game.keystroke_manager._events["CLOSE_GAME"].active


def test_summary_cli_reports_cut_off_history(
    game: object, monkeypatch: object, broken_saved_game_dir: Path, capsys: object
) -> None:
    """Test ``jparty summary`` prints the error and exits with code 1."""
    _patch_get_game(monkeypatch, game.data)
    exit_code = bootstrap.main(
        ["summary", "--game-state-directory", str(broken_saved_game_dir)]
    )
    assert exit_code == 1
    error_output = capsys.readouterr().err
    assert error_output.startswith("Could not read saved clue history.")
    assert "Line 3:" in error_output


def test_score_editor_button_stays_enabled_to_show_history_error(
    game: object, broken_saved_game_dir: Path
) -> None:
    """Test a damaged file does not crash the score-editor refresh."""
    game._game_state_dir = broken_saved_game_dir
    assert game.can_open_score_editor() is True
    with pytest.raises(HistoryFileError):
        game.get_recent_score_corrections()


def _play_two_clues(game: object) -> tuple:
    """Play two clues: Alice right on the first, wrong on the second."""
    first = game.current_round.get_question(0, 0)
    second = game.current_round.get_question(1, 0)
    game.load_question(first)
    game.open_responses()
    game.buzz(0)
    game.correct_answer()
    game.load_question(second)
    game.open_responses()
    game.buzz(0)
    game.incorrect_answer()
    game.stumped()
    game.back_to_board()
    return first, second


def test_correction_updates_totals_stats_and_graph(game_with_players: object) -> None:
    """Test one appended correction is reflected by every reader."""
    game = game_with_players
    first, _ = _play_two_clues(game)
    history_file = game._game_state_dir / "question_history.jsonl"
    played_lines = history_file.read_text(encoding="utf-8")

    changed = game.apply_question_history_corrections(
        [
            {
                "question_number": 1,
                "player_states": {0: "incorrect", 1: "correct", 2: "no answer"},
                "value": first.value,
            }
        ]
    )

    assert changed is True
    contents = history_file.read_text(encoding="utf-8")
    assert contents.startswith(played_lines)
    assert len(contents.splitlines()) == len(played_lines.splitlines()) + 1
    entries = read_history_file(history_file)
    assert history_score_totals(entries) == {0: -400, 1: 200}
    assert [player.score for player in game.players[:2]] == [-400, 200]

    summary = build_end_game_summary(game)
    alice, bob = summary.current_players[0], summary.current_players[1]
    assert (alice.right_count, alice.wrong_count, alice.coryat) == (0, 2, -400)
    assert (bob.right_count, bob.wrong_count, bob.coryat) == (1, 0, 200)
    assert summary.game_stats.triple_stumpers == 1
    assert game._reconstruct_score_history()[0] == [0, -200, -400]
    assert game._reconstruct_score_history()[1] == [0, 200, 200]


def test_resume_after_correction_restores_corrected_totals(
    game_with_players: object, monkeypatch: object
) -> None:
    """Test a resumed game uses the ledger totals after a correction."""
    game = game_with_players
    first, _ = _play_two_clues(game)
    game.apply_question_history_corrections(
        [
            {
                "question_number": 1,
                "player_states": {0: "incorrect", 1: "no answer", 2: "no answer"},
                "value": first.value,
            }
        ]
    )
    saved_dir = game._game_state_dir
    (saved_dir / "general.json").write_text(
        json.dumps(
            {
                "game_id": "4453",
                "players": [
                    {"name": player.name, "player_number": player.player_number}
                    for player in game.players
                ],
            }
        ),
        encoding="utf-8",
    )
    players = list(game.players)
    for player in players:
        player.score = 0
    _patch_get_game(monkeypatch, game.data)
    game.prepare_resume_from_dir(saved_dir)
    game.buzzer_controller.claimed_saved_players = lambda: players
    game._start_resumed_game()
    assert players[0].score == -400
    assert game.question_number == 3
    assert game.current_round.get_question(0, 0).complete is True


@pytest.fixture
def disk_full(monkeypatch: object) -> dict:
    """Make history appends fail partway while ``disk_full["on"]`` is true."""
    switch = {"on": True}
    real_open = Path.open

    def failing_open(
        self: Path, mode: str = "r", *args: object, **kwargs: object
    ) -> object:
        handle = real_open(self, mode, *args, **kwargs)
        if switch["on"] and self.name == "question_history.jsonl" and mode == "a":

            class DiskFull:
                def __enter__(self) -> object:
                    return self

                def __exit__(self, *exc: object) -> None:
                    handle.close()

                def write(self, text: str) -> None:
                    handle.write(text[: len(text) // 2])
                    handle.flush()
                    raise OSError(28, "No space left on device")

                def flush(self) -> None:
                    handle.flush()

            return DiskFull()
        return handle

    monkeypatch.setattr(Path, "open", failing_open)
    return switch


def _answer_correctly(game: object, row: int) -> None:
    """Have Alice answer the clue in ``row`` of the first category correctly."""
    game.load_question(game.current_round.get_question(row, 0))
    game.open_responses()
    game.buzz(0)
    game.correct_answer()


def _matches_live_scores(game: object, totals: dict[int, int]) -> bool:
    """Return whether history ``totals`` equal every player's in-memory score."""
    return all(
        totals.get(player.player_number, 0) == player.score for player in game.players
    )


def test_append_after_a_hand_repair_starts_a_new_line(
    game_with_players: object,
) -> None:
    """Test appending to a file whose last line lost its newline keeps it valid."""
    game = game_with_players
    _play_two_clues(game)
    history_file = game._game_state_dir / "question_history.jsonl"
    history_file.write_bytes(history_file.read_bytes().rstrip(b"\n"))

    _answer_correctly(game, 2)

    entries = read_history_file(history_file)
    assert [entry["question_number"] for entry in entries] == [1, 2, 3]
    assert history_file.read_bytes().endswith(b"}\n")
    assert _matches_live_scores(game, history_score_totals(entries))


def test_failed_append_leaves_the_file_exactly_as_before(
    game_with_players: object, disk_full: dict, warnings_shown: list
) -> None:
    """Test a write that fails partway rolls back and warns the host."""
    game = game_with_players
    _play_two_clues(game)
    history_file = game._game_state_dir / "question_history.jsonl"
    before = history_file.read_bytes()

    saved = game._append_history_entry({"type": "manual_score_adjustment"})

    assert saved is False
    assert history_file.read_bytes() == before
    assert len(warnings_shown) == 1
    title, text = warnings_shown[0]
    assert title == "Clue History Not Saved"
    assert text.startswith("Could not save clue history: No space left on device.")
    assert "still safe to load" in text


def test_failed_appends_are_saved_in_order_once_writing_works(
    game_with_players: object, disk_full: dict, warnings_shown: list
) -> None:
    """Test unsaved clues are written in front of the next one, keeping the chain."""
    game = game_with_players
    disk_full["on"] = False
    _play_two_clues(game)
    history_file = game._game_state_dir / "question_history.jsonl"
    saved_before_failure = history_file.read_bytes()

    disk_full["on"] = True
    _answer_correctly(game, 2)
    _answer_correctly(game, 3)

    assert history_file.read_bytes() == saved_before_failure
    assert len(warnings_shown) == 1
    # Readers during play see the queued clues, so totals and stats stay right.
    assert _matches_live_scores(
        game, history_score_totals(game._load_question_history())
    )
    assert build_end_game_summary(game).current_players[0].right_count == 3

    disk_full["on"] = False
    _answer_correctly(game, 4)

    entries = read_history_file(history_file)
    assert [entry["question_number"] for entry in entries] == [1, 2, 3, 4, 5]
    assert _matches_live_scores(game, history_score_totals(entries))
    assert game._pending_history_lines == []
    assert len(warnings_shown) == 1


def test_unsaved_lines_at_close_leave_a_loadable_save(
    game_with_players: object, disk_full: dict, warnings_shown: list
) -> None:
    """Test closing with unsaved clues warns the host and keeps the file valid."""
    game = game_with_players
    disk_full["on"] = False
    _play_two_clues(game)
    history_file = game._game_state_dir / "question_history.jsonl"
    saved_totals = history_score_totals(read_history_file(history_file))

    disk_full["on"] = True
    _answer_correctly(game, 2)
    game.close_game()

    assert len(warnings_shown) == 2
    assert warnings_shown[1] == (
        "Clue History Not Saved",
        "Could not save the last 1 clue history entries. The saved game will "
        "still load, but it resumes from before those clues.",
    )
    assert history_score_totals(read_history_file(history_file)) == saved_totals
    assert game._pending_history_lines == []


def test_corrections_that_fail_to_save_are_applied_and_saved_later(
    game_with_players: object, disk_full: dict, warnings_shown: list
) -> None:
    """Test a correction batch is kept in full when its write fails."""
    game = game_with_players
    disk_full["on"] = False
    first, second = _play_two_clues(game)
    history_file = game._game_state_dir / "question_history.jsonl"
    saved_before_failure = history_file.read_bytes()

    disk_full["on"] = True
    changed = game.apply_question_history_corrections(
        [
            {
                "question_number": 1,
                "player_states": {0: "incorrect", 1: "correct", 2: "no answer"},
                "value": first.value,
            },
            {
                "question_number": 2,
                "player_states": {0: "no answer", 1: "no answer", 2: "no answer"},
                "value": second.value,
            },
        ]
    )

    assert changed is True
    assert history_file.read_bytes() == saved_before_failure
    assert [player.score for player in game.players[:2]] == [
        -first.value,
        first.value,
    ]

    disk_full["on"] = False
    game.get_recent_score_corrections()

    entries = read_history_file(history_file)
    assert _matches_live_scores(game, history_score_totals(entries))
    assert game._pending_history_lines == []
