"""Image lookup module."""

import requests

REQUEST_TIMEOUT_SECONDS = 10
OK_STATUS_CODE = 200


def search_wikimedia_image(query: object) -> object:
    """Run search wikimedia image."""
    url = "https://en.wikipedia.org/w/api.php"
    headers = {"User-Agent": "J-NoChance/0.1 (trevorspreadbury@gmail.com)"}
    params = {
        "action": "query",
        "format": "json",
        "prop": "pageimages",
        "titles": query,
        "pithumbsize": 500,
    }
    response = requests.get(
        url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code == OK_STATUS_CODE:
        data = response.json()
        pages = data.get("query", {}).get("pages", {})
        for page_data in pages.values():
            if "thumbnail" in page_data:
                return page_data["thumbnail"]["source"]
        return "No image found."
    return f"Error: {response.status_code}"
