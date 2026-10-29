"""Test strict question-history reading and score-correction replay."""

import json
from pathlib import Path

import pytest
from jparty.domain.state import (
    HistoryFileError,
    corrected_history_entries,
    history_score_totals,
    read_history_file,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def fixture_lines(fixture_dir: Path) -> list[str]:
    """Return the fixture history file's lines without line endings."""
    return (fixture_dir / "question_history.jsonl").read_text().splitlines()


def _write_history(temp_dir: Path, text: str) -> Path:
    """Write ``text`` as a history file and return its path."""
    path = temp_dir / "question_history.jsonl"
    path.write_bytes(text.encode("utf-8"))
    return path


def _read_error(path: Path) -> HistoryFileError:
    """Return the error raised when reading ``path``."""
    with pytest.raises(HistoryFileError) as excinfo:
        read_history_file(path)
    return excinfo.value


def test_read_history_file_returns_entries_and_leaves_legacy_saves_unchanged(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test a valid file without correction lines reads exactly as stored."""
    path = _write_history(temp_dir, "\n".join(fixture_lines) + "\n")
    entries = read_history_file(path)
    assert entries == [json.loads(line) for line in fixture_lines]
    assert corrected_history_entries(entries) == entries
    assert history_score_totals(entries) == {0: 0, 1: 400}


def test_read_history_file_accepts_windows_line_endings(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test files written in text mode on Windows still load."""
    path = _write_history(temp_dir, "\r\n".join(fixture_lines) + "\r\n")
    assert len(read_history_file(path)) == len(fixture_lines)


def test_missing_history_file_reads_as_empty(temp_dir: Path) -> None:
    """Test a game with no clues played yet has no history."""
    assert read_history_file(temp_dir / "question_history.jsonl") == []


def test_cut_off_last_line_reports_its_line_number(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test a partly written last line raises instead of returning []."""
    text = "\n".join(fixture_lines[:2]) + "\n" + fixture_lines[2][:73]
    error = _read_error(_write_history(temp_dir, text))
    assert error.line_number == 3
    assert error.reason.startswith("not valid JSON (")


def test_valid_last_line_without_newline_is_reported_as_cut_off(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test a missing final newline is caught even if the JSON parses."""
    error = _read_error(_write_history(temp_dir, "\n".join(fixture_lines)))
    assert error.line_number == 3
    assert error.reason.startswith("no newline at the end of the line")


def test_invalid_middle_line_reports_its_line_number(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test a corrupt line in the middle of the file is reported."""
    text = "\n".join([fixture_lines[0], '{"question_number": 2,', fixture_lines[2]])
    error = _read_error(_write_history(temp_dir, text + "\n"))
    assert error.line_number == 2
    assert error.reason.startswith("not valid JSON (")


def test_missing_line_breaks_the_score_chain(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test deleting a line is caught by the next score that depended on it."""
    text = "\n".join([fixture_lines[0], fixture_lines[2]]) + "\n"
    error = _read_error(_write_history(temp_dir, text))
    assert error.line_number == 2
    assert "player 1's score starts at 200, but their previous score was 0" in (
        error.reason
    )


def test_edited_score_breaks_the_score_chain(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test a hand-edited score is caught on the following line."""
    first = json.loads(fixture_lines[0])
    first["answer_attempts"][0]["score_after"] = 1000
    text = "\n".join([json.dumps(first), *fixture_lines[1:]]) + "\n"
    error = _read_error(_write_history(temp_dir, text))
    assert error.line_number == 3
    assert "player 0's score starts at 200" in error.reason


def test_history_file_error_message_names_file_line_and_fix(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test every reader shows the same actionable message."""
    path = _write_history(temp_dir, fixture_lines[0] + "\n" + "not json\n")
    error = _read_error(path)
    assert str(error) == (
        "Could not read saved clue history.\n"
        f"File: {path}\n"
        "Line 2: not valid JSON (expecting value, column 1).\n"
        "Fix or delete that line, then try again."
    )
    assert isinstance(error, ValueError)


def test_invalid_utf8_reports_its_line_number(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test undecodable bytes are reported on the right line."""
    path = temp_dir / "question_history.jsonl"
    path.write_bytes(fixture_lines[0].encode() + b"\n\xff\xfe\n")
    assert _read_error(path).line_number == 2


def _correction(question_number: int, states: dict, adjustments: list) -> str:
    """Return one serialized ``score_correction`` line."""
    return json.dumps(
        {
            "type": "score_correction",
            "question_number": question_number,
            "timestamp": 1700000400.0,
            "player_states": states,
            "adjustments": adjustments,
        }
    )


def test_corrections_replay_as_they_should_have_been(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test corrected rulings flow through every later score."""
    correction = _correction(
        1,
        {"0": "incorrect", "1": "no answer"},
        [{"player_index": 0, "score_before": 0, "score_after": -400}],
    )
    path = _write_history(temp_dir, "\n".join([*fixture_lines, correction]) + "\n")
    entries = read_history_file(path)
    corrected = corrected_history_entries(entries)

    assert history_score_totals(entries) == {0: -400, 1: 400}
    assert len(corrected) == 3
    first_attempt = corrected[0]["answer_attempts"][0]
    assert first_attempt["answer_correct"] is False
    assert first_attempt["score_after"] == -200
    assert corrected[2]["answer_attempts"][0]["score_before"] == -200
    assert corrected[2]["answer_attempts"][0]["score_after"] == -400
    assert history_score_totals(corrected) == history_score_totals(entries)


def test_latest_correction_for_a_clue_wins(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test a second correction to the same clue replaces the first."""
    first = _correction(
        1,
        {"0": "incorrect", "1": "no answer"},
        [{"player_index": 0, "score_before": 0, "score_after": -400}],
    )
    second = _correction(
        1,
        {"0": "no answer", "1": "no answer"},
        [{"player_index": 0, "score_before": -400, "score_after": -200}],
    )
    text = "\n".join([*fixture_lines, first, second]) + "\n"
    entries = read_history_file(_write_history(temp_dir, text))
    corrected = corrected_history_entries(entries)
    assert corrected[0]["answer_attempts"] == []
    assert history_score_totals(corrected) == {0: -200, 1: 400}
    assert history_score_totals(entries) == {0: -200, 1: 400}


def test_manual_override_replays_as_its_recorded_change(
    temp_dir: Path, fixture_lines: list[str]
) -> None:
    """Test corrected totals match the ledger across a manual override."""
    manual = json.dumps(
        {
            "type": "manual_score_adjustment",
            "player_index": 0,
            "timestamp": 1700000350.0,
            "score_before": 0,
            "score_after": 1000,
            "new_score": 1000,
        }
    )
    correction = _correction(
        1,
        {"0": "incorrect", "1": "no answer"},
        [{"player_index": 0, "score_before": 1000, "score_after": 600}],
    )
    text = "\n".join([*fixture_lines, manual, correction]) + "\n"
    entries = read_history_file(_write_history(temp_dir, text))
    corrected = corrected_history_entries(entries)
    assert corrected[3]["score_before"] == -400
    assert corrected[3]["score_after"] == 600
    assert history_score_totals(corrected) == history_score_totals(entries)
