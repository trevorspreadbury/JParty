"""Remote source fetchers for JParty game data."""

from __future__ import annotations

import csv
import json
import logging

import requests
from bs4 import BeautifulSoup

REQUEST_TIMEOUT_SECONDS = 10


class GameSourceFetcher:
    """Fetch raw game source payloads from remote services."""

    def get_google_sheet_rows(self, file_id: object) -> list[list[str]]:
        """Fetch a Google Sheets CSV export as row data."""
        csv_url = f"https://docs.google.com/spreadsheet/ccc?key={file_id}&output=csv"
        with requests.get(
            csv_url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            lines = (line.decode("utf-8") for line in response.iter_lines())
            return list(csv.reader(lines))

    def get_jarchive_game_html(self, game_id: object) -> str:
        """Fetch raw game HTML directly from J-Archive."""
        game_url = f"http://www.j-archive.com/showgame.php?game_id={game_id}"
        return requests.get(game_url, timeout=REQUEST_TIMEOUT_SECONDS).text

    def get_wayback_game_html(self, game_id: object) -> str:
        """Fetch the latest Wayback snapshot for a J-Archive game."""
        archive_url = f"j-archive.com/showgame.php?game_id={str(game_id)}"
        url = (
            "http://web.archive.org/cdx/search/cdx?"
            f"url={archive_url}&collapse=digest&limit=-2&fastLatest=true&output=json"
        )
        parsed = json.loads(requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS).text)
        if not parsed:
            logging.info("No games found in Wayback for %s", game_id)
            raise ValueError("no games found in wayback")
        latest_snapshot = parsed[-1]
        final_url = (
            f"http://web.archive.org/web/{latest_snapshot[1]}/{latest_snapshot[2]}"
        )
        return requests.get(final_url, timeout=REQUEST_TIMEOUT_SECONDS).text

    def get_random_game(self) -> int:
        """Return a random J-Archive game id discovered from the homepage."""
        response = requests.get(
            "http://j-archive.com/", timeout=REQUEST_TIMEOUT_SECONDS
        )
        soup = BeautifulSoup(response.text, "html.parser")
        link = soup.find_all(class_="splash_clue_footer")[1].find("a")["href"]
        return int(link[21:])
