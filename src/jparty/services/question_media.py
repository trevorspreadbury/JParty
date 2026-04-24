"""Helpers for detecting, importing, and previewing local question media."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from jparty.app.paths import QUESTION_MEDIA

SUPPORTED_IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}


@dataclass(frozen=True)
class QuestionMediaStatus:
    """Describe which local-media artifacts exist for a game id."""

    directory: Path | None
    zip_file: Path | None

    @property
    def has_directory(self) -> bool:
        """Return whether a game-media directory exists."""
        return self.directory is not None

    @property
    def has_zip(self) -> bool:
        """Return whether a game-media zip exists."""
        return self.zip_file is not None

    @property
    def has_any(self) -> bool:
        """Return whether any local-media artifact exists."""
        return self.has_directory or self.has_zip

    def summary_text(self) -> str:
        """Return a user-facing summary of media detection."""
        if self.has_directory and self.has_zip:
            return "Question media status: found folder and zip archive."
        if self.has_directory:
            return "Question media status: found folder."
        if self.has_zip:
            return "Question media status: found zip archive."
        return "Question media status: no folder or zip archive found."


def question_media_dir(game_id: object) -> Path:
    """Return the expected local-media directory for a game id."""
    return QUESTION_MEDIA / str(game_id).strip()


def question_media_zip(game_id: object) -> Path:
    """Return the expected local-media zip path for a game id."""
    return QUESTION_MEDIA / f"{str(game_id).strip()}.zip"


def detect_question_media(game_id: object) -> QuestionMediaStatus:
    """Detect local-media artifacts for a game id."""
    media_dir = question_media_dir(game_id)
    media_zip = question_media_zip(game_id)
    return QuestionMediaStatus(
        directory=media_dir if media_dir.is_dir() else None,
        zip_file=media_zip if media_zip.is_file() else None,
    )


def is_supported_media_file(path: Path) -> bool:
    """Return whether the file extension is a supported image type."""
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def find_question_media_file(game_id: object, board_index: int, index: tuple) -> str | bool:
    """Return a local media path for a clue, if one exists."""
    media_dir = ensure_question_media_dir(game_id)
    if media_dir is None:
        return False
    target_stem = f"{board_index}-{index[0]}-{index[1]}"
    for media_file in media_dir.iterdir():
        if media_file.is_file() and is_supported_media_file(media_file):
            if media_file.stem == target_stem:
                return str(media_file)
    return False


def import_question_media(source_path: object, game_id: object) -> Path:
    """Import supported media from a folder or zip into the game media directory."""
    source = Path(source_path)
    destination = question_media_dir(game_id)
    destination.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        _copy_media_dir(source, destination)
    elif source.is_file() and source.suffix.lower() == ".zip":
        _extract_media_zip(source, destination)
    else:
        raise ValueError("Question media must be a directory or .zip file")
    return destination


def ensure_question_media_dir(game_id: object) -> Path | None:
    """Return a game-media directory, extracting a same-name zip when needed."""
    status = detect_question_media(game_id)
    if status.has_directory:
        return status.directory
    if status.has_zip:
        destination = question_media_dir(game_id)
        destination.mkdir(parents=True, exist_ok=True)
        _extract_media_zip(status.zip_file, destination)
        return destination
    return None


def local_media_questions(game: object, round_indices: object) -> list[tuple[int, object]]:
    """Return selected-round questions backed by local media files."""
    if not getattr(game, "data", None):
        return []
    selected = {int(index) for index in round_indices}
    preview_questions = []
    for round_index, round_data in enumerate(game.data.rounds):
        if round_index not in selected:
            continue
        for question in getattr(round_data, "questions", []):
            image_url = getattr(question, "image_url", None)
            if image_url and is_local_media_path(image_url):
                preview_questions.append((round_index, question))
    return preview_questions


def is_local_media_path(path_or_url: object) -> bool:
    """Return whether a question image path points to an existing local file."""
    if not path_or_url:
        return False
    try:
        path = Path(path_or_url)
    except TypeError:
        return False
    return path.exists() and path.is_file()


def _copy_media_dir(source: Path, destination: Path) -> None:
    """Copy supported top-level or nested media files into a flat destination."""
    for path in source.rglob("*"):
        if not path.is_file() or not is_supported_media_file(path):
            continue
        shutil.copy2(path, destination / path.name)


def _extract_media_zip(source: Path, destination: Path) -> None:
    """Extract supported media files from a zip into a flat destination."""
    with ZipFile(source) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            member_path = Path(member.filename)
            if not is_supported_media_file(member_path):
                continue
            extracted = archive.open(member)
            try:
                with (destination / member_path.name).open("wb") as output_file:
                    shutil.copyfileobj(extracted, output_file)
            finally:
                extracted.close()
