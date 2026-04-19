"""Application-wide configuration constants.

This module centralizes the small set of static values that shape JParty's
runtime behavior, including clue timing, score values, networking defaults, and
the computed project root. The constants defined here are imported broadly
across the app, domain, and UI layers.
"""

from pathlib import Path

APP_NAME = "JParty"
FJTIME = 31
QUESTIONTIME = 4
MONIES = [[200, 400, 600, 800, 1000], [400, 800, 1200, 1600, 2000]]
MAXPLAYERS = 8
PORT = 8080
EARLY_BUZZ_PENALTY = 0.25
DEBUG_MODE = True
PROJECT_ROOT = Path(__file__).resolve().parents[3]
