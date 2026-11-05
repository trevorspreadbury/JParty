"""Test Wikimedia image lookup module."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from jparty.services import image_lookup

pytestmark = pytest.mark.unit


def test_wikimedia_image_search_url_encodes_query() -> None:
    """Test the lookup URL targets the API and encodes the page title."""
    url = image_lookup.wikimedia_image_search_url("What is the Gateway Arch?")
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        image_lookup.WIKIMEDIA_API_URL
    )
    params = parse_qs(parts.query)
    assert params["titles"] == ["What is the Gateway Arch?"]
    assert params["prop"] == ["pageimages"]
    assert params["format"] == ["json"]


def test_parse_wikimedia_image_response_returns_thumbnail_source() -> None:
    """Test a response with a page thumbnail yields its URL."""
    body = json.dumps(
        {"query": {"pages": {"1": {"thumbnail": {"source": "https://x/arch.png"}}}}}
    ).encode()
    assert image_lookup.parse_wikimedia_image_response(body) == "https://x/arch.png"


@pytest.mark.parametrize(
    "body",
    [
        b'{"query": {"pages": {"-1": {"missing": ""}}}}',
        b"{}",
        b"[]",
        b"not json",
        b"",
    ],
)
def test_parse_wikimedia_image_response_returns_no_image_otherwise(
    body: bytes,
) -> None:
    """Test missing thumbnails and unparseable bodies yield the no-image result."""
    assert image_lookup.parse_wikimedia_image_response(body) == "No image found."
