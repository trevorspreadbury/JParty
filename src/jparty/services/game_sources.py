"""Remote source fetchers for JParty game data."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

REQUEST_TIMEOUT_SECONDS = 10
# A CDX JSON reply is a header row followed by one row per snapshot.
CDX_MIN_ROWS_WITH_SNAPSHOT = 2
GOOGLE_SHEETS_HOST = "docs.google.com"
_SHEET_PATH = re.compile(r"^/spreadsheets/d/(e/)?([A-Za-z0-9_-]+)")
_BARE_SHEET_ID = re.compile(r"^[A-Za-z0-9_-]{20,}$")


class SheetAccessError(ValueError):
    """Raised when a Google Sheet link can't be read as CSV."""


def google_sheet_csv_url(link: str) -> str:
    """Return the CSV export URL for a Google Sheet link.

    Accepts a sheet's browser link (``.../spreadsheets/d/<id>/edit#gid=<n>``),
    a "Publish to the web" link (``.../spreadsheets/d/e/<id>/pubhtml``), or a
    bare sheet id. The tab named by ``gid`` is exported; without one, Google
    exports the first tab.

    Args:
        link: Link or id as pasted by the host.

    Returns:
        A URL that downloads the tab as CSV.

    Raises:
        SheetAccessError: If ``link`` isn't a Google Sheet link.
    """
    link = link.strip()
    if _BARE_SHEET_ID.match(link):
        return f"https://{GOOGLE_SHEETS_HOST}/spreadsheets/d/{link}/export?format=csv"
    parsed = urlparse(link if "//" in link else f"https://{link}")
    match = _SHEET_PATH.match(parsed.path)
    if parsed.hostname != GOOGLE_SHEETS_HOST or match is None:
        raise SheetAccessError("That doesn't look like a Google Sheets link.")
    published, sheet_id = match.groups()
    query = parse_qs(parsed.query)
    fragment = parse_qs(parsed.fragment)
    gid = (query.get("gid") or fragment.get("gid") or [None])[0]
    gid_part = f"&gid={gid}" if gid and gid.isdigit() else ""
    if published:
        return (
            f"https://{GOOGLE_SHEETS_HOST}/spreadsheets/d/e/{sheet_id}/pub"
            f"?output=csv{gid_part}"
        )
    return (
        f"https://{GOOGLE_SHEETS_HOST}/spreadsheets/d/{sheet_id}/export"
        f"?format=csv{gid_part}"
    )


class GameSourceFetcher:
    """Fetch raw game source payloads from remote services."""

    def get_google_sheet_rows(self, file_id: object) -> list[list[str]]:
        """Fetch a Google Sheets CSV export as row data.

        The whole body is decoded before parsing, so line endings and line
        breaks inside quoted cells are handled by ``csv`` rather than split
        at arbitrary network chunk boundaries.
        """
        csv_url = f"https://docs.google.com/spreadsheet/ccc?key={file_id}&output=csv"
        response = requests.get(csv_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        text = response.content.decode("utf-8-sig")
        return list(csv.reader(io.StringIO(text, newline="")))

    def get_sheet_rows_from_link(self, link: str) -> list[list[str]]:
        """Fetch the rows of a Google Sheet tab from a pasted link.

        Args:
            link: Sheet link or id, as accepted by :func:`google_sheet_csv_url`.

        Returns:
            The tab's rows, header first.

        Raises:
            SheetAccessError: If the link is not a sheet, or Google answers
                with a sign-in page because the sheet isn't shared.
            requests.RequestException: If the request fails.
        """
        response = requests.get(
            google_sheet_csv_url(link), timeout=REQUEST_TIMEOUT_SECONDS
        )
        if response.status_code in (401, 403, 404) or "text/html" in (
            response.headers.get("Content-Type", "")
        ):
            raise SheetAccessError(
                "Google didn't share that sheet. In the sheet, choose Share and set"
                ' General access to "Anyone with the link".'
            )
        response.raise_for_status()
        text = response.content.decode("utf-8-sig")
        return list(csv.reader(io.StringIO(text, newline="")))

    def get_jarchive_game_html(self, game_id: object) -> str:
        """Fetch raw game HTML directly from J-Archive."""
        game_url = f"http://www.j-archive.com/showgame.php?game_id={game_id}"
        response = requests.get(game_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text

    def get_wayback_game_html(self, game_id: object) -> str:
        """Fetch the latest Wayback snapshot for a J-Archive game.

        Only snapshots that J-Archive served with HTTP 200 are considered. An
        HTTP error from Wayback itself, such as a 429 rate limit, raises
        ``requests.HTTPError``.
        """
        archive_url = f"j-archive.com/showgame.php?game_id={str(game_id)}"
        url = (
            "http://web.archive.org/cdx/search/cdx?"
            f"url={archive_url}&collapse=digest&limit=-2&fastLatest=true&output=json"
            "&filter=statuscode:200"
        )
        cdx_response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        cdx_response.raise_for_status()
        parsed = json.loads(cdx_response.text)
        # The first row is the column header, so a lone header means no hits.
        if len(parsed) < CDX_MIN_ROWS_WITH_SNAPSHOT:
            logging.info("No games found in Wayback for %s", game_id)
            raise ValueError("no games found in wayback")
        latest_snapshot = parsed[-1]
        final_url = (
            f"http://web.archive.org/web/{latest_snapshot[1]}/{latest_snapshot[2]}"
        )
        snapshot_response = requests.get(final_url, timeout=REQUEST_TIMEOUT_SECONDS)
        snapshot_response.raise_for_status()
        return snapshot_response.text

    def get_random_game(self) -> int:
        """Return a random J-Archive game id discovered from the homepage."""
        response = requests.get(
            "http://j-archive.com/", timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        link = soup.find_all(class_="splash_clue_footer")[1].find("a")["href"]
        return int(link[21:])
