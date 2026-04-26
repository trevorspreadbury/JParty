"""Tests for local question-media detection and import helpers."""

from pathlib import Path
from zipfile import ZipFile

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
