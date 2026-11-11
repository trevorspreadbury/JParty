"""Application-wide configuration constants.

This module centralizes the small set of static values that shape JParty's
runtime behavior, including clue timing, score values, networking defaults, and
the computed project root. The constants defined here are imported broadly
across the app, domain, and UI layers.
"""

import os
from pathlib import Path

DEBUG_ENV_VAR = "JPARTY_DEBUG"
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def env_flag_enabled(name: str, env: object = None) -> bool:
    """Return whether an environment variable is set to a truthy value.

    Args:
        name: Environment variable name to read.
        env: Optional mapping to read from instead of ``os.environ``.

    Returns:
        ``True`` when the variable is ``1``, ``true``, ``yes`` or ``on``
        (case-insensitive), otherwise ``False``.
    """
    current_env = os.environ if env is None else env
    return str(current_env.get(name, "")).strip().lower() in _TRUTHY_ENV_VALUES


APP_NAME = "JParty"
FJTIME = 31
QUESTIONTIME = 4
MONIES = [[200, 400, 600, 800, 1000], [400, 800, 1200, 1600, 2000]]
MAXPLAYERS = 8
PORT = 8080
EARLY_BUZZ_PENALTY = 0.25
# Developer single-monitor mode. Off by default so shipped builds enforce the
# two-monitor check; enable with ``JPARTY_DEBUG=1`` or ``jparty --debug``.
DEBUG_MODE = env_flag_enabled(DEBUG_ENV_VAR)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
