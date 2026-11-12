"""Tests for local question-media detection and import helpers."""

import threading
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pytest

from jparty.services import question_media


def test_detect_question_media_reports_directory_and_zip(
    temp_dir: object, monkeypatch: object
) -> None:
    """Detection should distinguish directory and zip presence."""
    media_root = temp_dir / "question_media"
    media_root.mkdir()
    game_dir = media_root / "4453"
    game_dir.mkdir()
    game_zip = media_root / "4453.zip"
    game_zip.write_bytes(b"zip")
    monkeypatch.setattr(question_media, "QUESTION_MEDIA", media_root)
    status = question_media.detect_question_media("4453")
    assert status.has_directory is True
    assert status.has_zip is True
    assert (
        status.summary_text() == "Question media status: found folder and zip archive."
    )


def test_import_question_media_directory_copies_supported_files(
    temp_dir: object, monkeypatch: object
) -> None:
    """Directory import should flatten supported image files into the target."""
    media_root = temp_dir / "question_media"
    source_dir = temp_dir / "source"
    nested_dir = source_dir / "nested"
    nested_dir.mkdir(parents=True)
    (source_dir / "0-0-0.png").write_bytes(b"png")
    (nested_dir / "1-2-3.jpg").write_bytes(b"jpg")
    (nested_dir / "notes.txt").write_text("ignore me", encoding="utf-8")
    monkeypatch.setattr(question_media, "QUESTION_MEDIA", media_root)
    destination = question_media.import_question_media(source_dir, "4453")
    copied_files = sorted(path.name for path in destination.iterdir())
    assert copied_files == ["0-0-0.png", "1-2-3.jpg"]


def test_import_question_media_zip_extracts_supported_files(
    temp_dir: object, monkeypatch: object
) -> None:
    """Zip import should flatten supported image files into the target."""
    media_root = temp_dir / "question_media"
    source_zip = temp_dir / "4453.zip"
    with ZipFile(source_zip, "w") as archive:
        archive.writestr("0-0-0.webp", b"webp")
        archive.writestr("nested/1-2-3.jpeg", b"jpeg")
        archive.writestr("nested/readme.md", b"ignore")
    monkeypatch.setattr(question_media, "QUESTION_MEDIA", media_root)
    destination = question_media.import_question_media(source_zip, "4453")
    copied_files = sorted(path.name for path in destination.iterdir())
    assert copied_files == ["0-0-0.webp", "1-2-3.jpeg"]


def test_find_question_media_file_matches_supported_extensions(
    temp_dir: object, monkeypatch: object
) -> None:
    """Lookup should match by filename stem across supported extensions."""
    media_root = temp_dir / "question_media"
    game_dir = media_root / "4453"
    game_dir.mkdir(parents=True)
    expected_path = game_dir / "1-0-0.webp"
    expected_path.write_bytes(b"image")
    monkeypatch.setattr(question_media, "QUESTION_MEDIA", media_root)
    assert question_media.find_question_media_file("4453", 1, (0, 0)) == str(
        expected_path
    )


def test_find_question_media_file_extracts_same_name_zip_when_needed(
    temp_dir: object, monkeypatch: object
) -> None:
    """Lookup should extract an existing same-name zip when the directory is absent."""
    media_root = temp_dir / "question_media"
    media_root.mkdir()
    source_zip = media_root / "4453.zip"
    with ZipFile(source_zip, "w") as archive:
        archive.writestr("0-1-2.png", b"png")
    monkeypatch.setattr(question_media, "QUESTION_MEDIA", media_root)
    resolved = question_media.find_question_media_file("4453", 0, (1, 2))
    assert resolved == str(media_root / "4453" / "0-1-2.png")
    assert Path(resolved).exists()


def _media_root_with_corrupt_zip(temp_dir: Path, monkeypatch: object) -> Path:
    """Point media lookups at a folder holding a damaged ``4453.zip``."""
    media_root = temp_dir / "question_media"
    media_root.mkdir()
    (media_root / "4453.zip").write_bytes(b"this is not a zip archive")
    monkeypatch.setattr(question_media, "QUESTION_MEDIA", media_root)
    monkeypatch.setattr(question_media, "_EXTRACT_FAILURES", {})
    return media_root


def test_corrupt_zip_is_reported_and_leaves_no_empty_folder(
    temp_dir: object, monkeypatch: object
) -> None:
    """A damaged zip should not raise, leave a folder, or hide the failure."""
    media_root = _media_root_with_corrupt_zip(temp_dir, monkeypatch)

    assert question_media.find_question_media_file("4453", 0, (1, 2)) is False

    assert sorted(path.name for path in media_root.iterdir()) == ["4453.zip"]
    status = question_media.detect_question_media("4453")
    assert status.has_directory is False
    assert status.error
    assert "could not be extracted" in status.summary_text()


def test_corrupt_zip_is_not_reopened_for_every_clue(
    temp_dir: object, monkeypatch: object
) -> None:
    """After one failure, later lookups should skip the unchanged zip."""
    _media_root_with_corrupt_zip(temp_dir, monkeypatch)
    opened = []
    real_extract = question_media._extract_media_zip

    def counting_extract(source: Path, destination: Path) -> None:
        """Count extraction attempts."""
        opened.append(source)
        real_extract(source, destination)

    monkeypatch.setattr(question_media, "_extract_media_zip", counting_extract)

    for column in range(3):
        question_media.find_question_media_file("4453", 0, (column, 0))

    assert len(opened) == 1


def test_replacing_corrupt_zip_retries_extraction(
    temp_dir: object, monkeypatch: object
) -> None:
    """A fixed zip should be extracted even after an earlier failure."""
    media_root = _media_root_with_corrupt_zip(temp_dir, monkeypatch)
    question_media.find_question_media_file("4453", 0, (1, 2))
    with ZipFile(media_root / "4453.zip", "w") as archive:
        archive.writestr("0-1-2.png", b"png fixed and a bit longer")

    resolved = question_media.find_question_media_file("4453", 0, (1, 2))

    assert resolved == str(media_root / "4453" / "0-1-2.png")
    assert question_media.detect_question_media("4453").error is None


def test_parser_continues_when_media_zip_is_corrupt(
    temp_dir: object, monkeypatch: object, fixture_dir: object
) -> None:
    """Parsing a game should still succeed, just without local media."""
    from jparty.services import game_parser

    media_root = _media_root_with_corrupt_zip(temp_dir, monkeypatch)
    monkeypatch.setattr(game_parser, "QUESTION_MEDIA", media_root)
    html = (fixture_dir / "4453.html").read_text(encoding="utf-8")

    game = game_parser.GameParser().process_game_board_from_html(html, "4453")

    assert game is not None
    assert question_media.detect_question_media("4453").error


def test_concurrent_lookups_never_see_a_partial_folder(
    temp_dir: object, monkeypatch: object
) -> None:
    """Parallel workers should all see the fully extracted folder."""
    media_root = temp_dir / "question_media"
    media_root.mkdir()
    names = [f"0-{column}-{row}.png" for column in range(6) for row in range(5)]
    with ZipFile(media_root / "4453.zip", "w") as archive:
        for name in names:
            archive.writestr(name, b"png")
    monkeypatch.setattr(question_media, "QUESTION_MEDIA", media_root)
    monkeypatch.setattr(question_media, "_EXTRACT_FAILURES", {})
    barrier = threading.Barrier(4)
    results = []

    def worker() -> None:
        """Look up the last clue's media at the same moment as other workers."""
        barrier.wait()
        results.append(question_media.find_question_media_file("4453", 0, (5, 4)))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [str(media_root / "4453" / "0-5-4.png")] * 4
    assert sorted(path.name for path in (media_root / "4453").iterdir()) == sorted(
        names
    )
    assert sorted(path.name for path in media_root.iterdir()) == ["4453", "4453.zip"]


def test_import_corrupt_zip_raises_without_creating_folder(
    temp_dir: object, monkeypatch: object
) -> None:
    """A failed import should not leave an empty folder behind."""
    media_root = temp_dir / "question_media"
    source_zip = temp_dir / "upload.zip"
    source_zip.write_bytes(b"not a zip")
    monkeypatch.setattr(question_media, "QUESTION_MEDIA", media_root)

    with pytest.raises(BadZipFile):
        question_media.import_question_media(source_zip, "4453")

    assert not (media_root / "4453").exists()
    assert list(media_root.iterdir()) == []
