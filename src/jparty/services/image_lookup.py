"""Look up representative thumbnail images for clue-related topics.

This module builds and parses a small Wikimedia API query that resolves a page
title into a thumbnail URL. The request itself is issued asynchronously by the
host image-review widget so a slow or missing network never blocks the UI
thread.
"""

import json
from urllib.parse import urlencode

WIKIMEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
WIKIMEDIA_USER_AGENT = "J-NoChance/0.1 (trevorspreadbury@gmail.com)"
NO_IMAGE_FOUND = "No image found."
REQUEST_TIMEOUT_SECONDS = 10
THUMBNAIL_SIZE = 500


def wikimedia_image_search_url(query: object) -> str:
    """Build the Wikimedia API URL that looks up a page thumbnail.

    Args:
        query: Page title or search phrase sent to the Wikipedia API.

    Returns:
        The full request URL, including the encoded query string.
    """
    params = {
        "action": "query",
        "format": "json",
        "prop": "pageimages",
        "titles": query,
        "pithumbsize": THUMBNAIL_SIZE,
    }
    return f"{WIKIMEDIA_API_URL}?{urlencode(params)}"


def parse_wikimedia_image_response(body: object) -> str:
    """Extract the thumbnail URL from a Wikimedia API response body.

    Args:
        body: Raw JSON response body as ``bytes`` or ``str``.

    Returns:
        The thumbnail image URL when one is available, otherwise
        ``"No image found."`` (including when the body is not valid JSON).
    """
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return NO_IMAGE_FOUND
    if not isinstance(data, dict):
        return NO_IMAGE_FOUND
    pages = data.get("query", {}).get("pages", {})
    for page_data in pages.values():
        thumbnail = page_data.get("thumbnail") if isinstance(page_data, dict) else None
        if thumbnail and thumbnail.get("source"):
            return thumbnail["source"]
    return NO_IMAGE_FOUND
