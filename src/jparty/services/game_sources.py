"""Remote source fetchers for JParty game data."""

from __future__ import annotations

import csv
import io
import json
import logging

import requests
from bs4 import BeautifulSoup

REQUEST_TIMEOUT_SECONDS = 10
# A CDX JSON reply is a header row followed by one row per snapshot.
CDX_MIN_ROWS_WITH_SNAPSHOT = 2


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
