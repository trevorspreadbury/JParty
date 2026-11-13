"""Import-order checks that need a fresh interpreter."""

import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "module",
    ["jparty.services", "jparty.domain", "jparty.domain.models", "jparty.app.config"],
)
def test_package_imports_first_in_fresh_interpreter(module: str) -> None:
    """Each package should import cleanly as the very first import."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_domain_still_exports_game_lazily() -> None:
    """``from jparty.domain import Game`` should keep working."""
    from jparty.domain import Game
    from jparty.domain.game_engine import Game as EngineGame

    assert Game is EngineGame
