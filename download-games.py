"""Script to download games"""

import argparse
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jparty.app.paths import SAVED_GAMES
from jparty.services.archive_client import get_game_html, process_game_board_from_html

parser = argparse.ArgumentParser()
parser.add_argument(
    "game_ids", nargs="*", help="List of all game ids you'd like to download", default=None
)
args = parser.parse_args()

for game_id in args.game_ids:
    print(f"Working on {game_id}")
    game_html = get_game_html(game_id)
    game_obj = process_game_board_from_html(game_html, game_id)
    if (SAVED_GAMES / f"{game_id}.html").exists():
        print("Game already saved")
        continue
    with (SAVED_GAMES / f"{game_id}.html").open("w+", encoding="utf-8") as f:
        f.write(game_html)
    time.sleep(5)
