from pathlib import Path

FJTIME = 31
QUESTIONTIME = 4
MONIES = [[200, 400, 600, 800, 1000], [400, 800, 1200, 1600, 2000]]
MAXPLAYERS = 8
PORT = 8080
REPO_ROOT = Path(__file__).resolve().parent.parent
SAVED_GAMES = REPO_ROOT / "jparty" / "data" / "saved_games"
SAVED_GAMES.mkdir(parents=True, exist_ok=True)
QUESTION_MEDIA = REPO_ROOT / "jparty" / "data" / "question_media"
QUESTION_MEDIA.mkdir(parents=True, exist_ok=True)
GAME_STATES_DIR = REPO_ROOT / "jparty" / "data" / "game_states"
GAME_STATES_DIR.mkdir(parents=True, exist_ok=True)
<<<<<<< HEAD
EARLY_BUZZ_PENALTY = 0.25
DEBUG_MODE = True
=======
EARLY_BUZZ_PENALTY = 0.25
>>>>>>> a00e223 (first pass of game state tracking)
