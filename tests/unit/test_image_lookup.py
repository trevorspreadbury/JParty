"""Test Wikimedia image lookup module."""

from types import SimpleNamespace

import pytest
import requests
from jparty.services import image_lookup

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("offline"),
        requests.exceptions.Timeout("slow"),
    ],
)
def test_search_wikimedia_image_returns_no_image_when_request_fails(
    monkeypatch: object, error: Exception
) -> None:
    """Test network failures degrade to the no-image result instead of raising."""

    def fail(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(image_lookup.requests, "get", fail)
    assert image_lookup.search_wikimedia_image("Gateway Arch") == "No image found."


def test_search_wikimedia_image_returns_no_image_for_invalid_json(
    monkeypatch: object,
) -> None:
    """Test an unparseable response body degrades to the no-image result."""

    def bad_json() -> None:
        raise requests.exceptions.JSONDecodeError("bad", "", 0)

    response = SimpleNamespace(status_code=200, json=bad_json)
    monkeypatch.setattr(image_lookup.requests, "get", lambda *a, **k: response)
    assert image_lookup.search_wikimedia_image("Gateway Arch") == "No image found."


def test_search_wikimedia_image_returns_thumbnail_source(monkeypatch: object) -> None:
    """Test a successful lookup returns the page thumbnail URL."""
    payload = {
        "query": {"pages": {"1": {"thumbnail": {"source": "https://x/arch.png"}}}}
    }
    response = SimpleNamespace(status_code=200, json=lambda: payload)
    monkeypatch.setattr(image_lookup.requests, "get", lambda *a, **k: response)
    assert image_lookup.search_wikimedia_image("Gateway Arch") == "https://x/arch.png"
