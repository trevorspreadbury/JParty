"""Shared fixtures for Qt widget tests."""

import json
from pathlib import Path

import pytest
from jparty.services import image_lookup
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor, QPixmap

# Nothing listens on the discard port, so requests fail like an offline machine.
UNREACHABLE_API_URL = "http://127.0.0.1:9/w/api.php"


@pytest.fixture
def unreachable_api_url() -> str:
    """Return a lookup URL that fails with a connection error."""
    return UNREACHABLE_API_URL


@pytest.fixture
def offline_image_lookup(monkeypatch: object, unreachable_api_url: str) -> None:
    """Make Wikimedia image lookups fail with a connection error."""
    monkeypatch.setattr(image_lookup, "WIKIMEDIA_API_URL", unreachable_api_url)


@pytest.fixture
def local_image_lookup(monkeypatch: object, temp_dir: Path) -> Path:
    """Serve Wikimedia image lookups from local files.

    Returns:
        Path of the thumbnail image the lookup resolves to.
    """
    thumbnail_path = temp_dir / "thumbnail.png"
    pixmap = QPixmap(30, 20)
    pixmap.fill(QColor("blue"))
    assert pixmap.save(str(thumbnail_path))
    api_path = temp_dir / "api.json"
    thumbnail_url = QUrl.fromLocalFile(str(thumbnail_path)).toString()
    api_path.write_text(
        json.dumps(
            {"query": {"pages": {"1": {"thumbnail": {"source": thumbnail_url}}}}}
        ),
        encoding="utf-8",
    )
    api_url = QUrl.fromLocalFile(str(api_path)).toString()
    monkeypatch.setattr(image_lookup, "WIKIMEDIA_API_URL", api_url)
    return thumbnail_path
