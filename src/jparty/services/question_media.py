"""Helpers for detecting, importing, and previewing local question media."""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from jparty.app.paths import QUESTION_MEDIA

SUPPORTED_IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}

# Serializes extraction so two parser workers never race on one game folder.
_EXTRACT_LOCK = threading.Lock()
# Zip path -> (zip mtime_ns, zip size, error text) for zips that failed to
# extract. A zip is retried only after it changes on disk.
_EXTRACT_FAILURES: dict[str, tuple[int, int, str]] = {}
# Errors that mean the zip itself is damaged or unsupported. Only these are
# recorded in ``_EXTRACT_FAILURES``; file-system errors (for example a
# Windows file lock) may clear up, so they are retried on the next load.
_ZIP_CONTENT_ERRORS = (
    BadZipFile,
    EOFError,
    NotImplementedError,
    RuntimeError,
    zlib.error,
)
# Pauses, in seconds, between attempts to move freshly written files. On
# Windows, antivirus or the search indexer can briefly hold a handle on new
# files, which makes a rename fail with ``PermissionError``. The worst case
# adds 0.5 s before giving up.
_MOVE_RETRY_DELAYS = (0.05, 0.1, 0.15, 0.2)


@dataclass(frozen=True)
class QuestionMediaStatus:
    """Describe which local-media artifacts exist for a game id."""

    directory: Path | None
    zip_file: Path | None
    error: str | None = None

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
        if self.error:
            return (
                "Question media status: zip archive could not be extracted "
                f"({self.error}). Playing without question media."
            )
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
    has_directory = media_dir.is_dir()
    has_zip = media_zip.is_file()
    error = None
    if has_zip and not has_directory:
        error = _recorded_extract_failure(media_zip)
    return QuestionMediaStatus(
        directory=media_dir if has_directory else None,
        zip_file=media_zip if has_zip else None,
        error=error,
    )


def is_supported_media_file(path: Path) -> bool:
    """Return whether the file extension is a supported image type."""
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def find_question_media_file(
    game_id: object, board_index: int, index: tuple
) -> str | bool:
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
    """Import supported media from a folder or zip into the game media directory.

    Files are staged in a temporary folder first, so a damaged zip raises
    without leaving an empty game folder behind.
    """
    source = Path(source_path)
    destination = question_media_dir(game_id)
    if source.is_dir():
        stage = _copy_media_dir
    elif source.is_file() and source.suffix.lower() == ".zip":
        stage = _extract_media_zip
    else:
        raise ValueError("Question media must be a directory or .zip file")
    with _EXTRACT_LOCK:
        staging = _make_staging_dir(game_id)
        try:
            stage(source, staging)
            destination.mkdir(parents=True, exist_ok=True)
            for staged_file in staging.iterdir():
                target = destination / staged_file.name
                _retry_on_permission_error(
                    lambda staged=staged_file, target=target: staged.replace(target)
                )
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        _EXTRACT_FAILURES.pop(str(question_media_zip(game_id)), None)
    return destination


def ensure_question_media_dir(game_id: object) -> Path | None:
    """Return a game-media directory, extracting a same-name zip when needed.

    The zip is extracted into a temporary folder that is renamed into place
    only once extraction finishes, under a lock. Other workers therefore never
    see a half-extracted folder, and a damaged zip never leaves an empty
    folder that would hide the problem on the next load. If the zip itself is
    damaged, the error is logged and recorded for ``detect_question_media``
    so the host is told, and ``None`` is returned so parsing continues. A
    file-system error, such as a file briefly locked by antivirus, also
    returns ``None`` but is not recorded, so the next load tries again.
    """
    status = detect_question_media(game_id)
    if status.has_directory:
        return status.directory
    if not status.has_zip or status.error:
        return None
    with _EXTRACT_LOCK:
        destination = question_media_dir(game_id)
        if destination.is_dir():
            return destination
        try:
            _extract_zip_into_place(status.zip_file, destination, game_id)
        except _ZIP_CONTENT_ERRORS as exc:
            _record_extract_failure(status.zip_file, exc)
            return None
        except OSError:
            logging.warning(
                "Could not extract question media zip %s; will retry on the next load",
                status.zip_file,
                exc_info=True,
            )
            return None
        _EXTRACT_FAILURES.pop(str(status.zip_file), None)
    return destination


def _make_staging_dir(game_id: object) -> Path:
    """Create a hidden temporary folder beside the game-media folders."""
    QUESTION_MEDIA.mkdir(parents=True, exist_ok=True)
    return Path(
        tempfile.mkdtemp(dir=QUESTION_MEDIA, prefix=f".{str(game_id).strip()}-")
    )


def _extract_zip_into_place(source: Path, destination: Path, game_id: object) -> None:
    """Extract ``source`` into a staging folder, then rename it to ``destination``."""
    staging = _make_staging_dir(game_id)
    try:
        _extract_media_zip(source, staging)
        try:
            _retry_on_permission_error(lambda: staging.rename(destination))
        except OSError:
            # Another process may have finished the same extraction first.
            if not destination.is_dir():
                raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _sleep(seconds: float) -> None:
    """Pause between move attempts. Tests patch this to avoid waiting."""
    time.sleep(seconds)


def _retry_on_permission_error(action: Callable[[], object]) -> None:
    """Run a file move, retrying briefly while it raises ``PermissionError``.

    The last ``PermissionError`` is re-raised if every attempt fails. Other
    errors are raised at once.
    """
    for delay in _MOVE_RETRY_DELAYS:
        try:
            action()
            return
        except PermissionError:
            _sleep(delay)
    action()


def _record_extract_failure(zip_file: Path, exc: Exception) -> None:
    """Log and remember that ``zip_file`` could not be extracted."""
    logging.error(
        "Could not extract question media zip %s; playing without media",
        zip_file,
        exc_info=True,
    )
    try:
        stat = zip_file.stat()
    except OSError:
        return
    message = str(exc) or type(exc).__name__
    _EXTRACT_FAILURES[str(zip_file)] = (
        stat.st_mtime_ns,
        stat.st_size,
        message,
    )


def _recorded_extract_failure(zip_file: Path) -> str | None:
    """Return the recorded extraction error if ``zip_file`` has not changed."""
    failure = _EXTRACT_FAILURES.get(str(zip_file))
    if failure is None:
        return None
    try:
        stat = zip_file.stat()
    except OSError:
        return None
    mtime_ns, size, message = failure
    if (stat.st_mtime_ns, stat.st_size) != (mtime_ns, size):
        return None
    return message


def local_media_questions(
    game: object, round_indices: object
) -> list[tuple[int, object]]:
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
