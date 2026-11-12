"""Test main checks module."""

import pytest

from jparty.app import bootstrap as main
from jparty.app import config

pytestmark = pytest.mark.integration


def test_check_internet_exits_when_request_fails(monkeypatch: object) -> None:
    """Test test check internet exits when request fails."""
    critical_calls = []
    monkeypatch.setattr(
        main.requests,
        "get",
        lambda url, **kwargs: (_ for _ in ()).throw(
            main.requests.exceptions.ConnectionError()
        ),
    )
    monkeypatch.setattr(
        main.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "builtins.exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code))
    )
    with pytest.raises(SystemExit):
        main.check_internet()
    assert critical_calls


def test_check_second_monitor_skips_when_debug_enabled(monkeypatch: object) -> None:
    """Test test check second monitor skips when debug enabled."""
    monkeypatch.setattr(main, "debug_mode_enabled", lambda: True)
    main.check_second_monitor()


def test_check_second_monitor_exits_without_two_screens(monkeypatch: object) -> None:
    """Test test check second monitor exits without two screens."""
    critical_calls = []
    monkeypatch.setattr(main, "debug_mode_enabled", lambda: False)
    monkeypatch.setattr(
        main.QApplication,
        "instance",
        lambda: type(
            "App",
            (),
            {"screens": lambda self: [object()], "processEvents": lambda self: None},
        )(),
    )
    monkeypatch.setattr(
        main.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        main.sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code))
    )
    with pytest.raises(SystemExit):
        main.check_second_monitor()
    assert critical_calls


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_debug_env_flag_accepts_truthy_values(value: str) -> None:
    """JPARTY_DEBUG enables debug mode for common truthy spellings."""
    assert config.env_flag_enabled(config.DEBUG_ENV_VAR, {"JPARTY_DEBUG": value})


@pytest.mark.parametrize("env", [{}, {"JPARTY_DEBUG": ""}, {"JPARTY_DEBUG": "0"}])
def test_debug_env_flag_is_off_by_default(env: dict) -> None:
    """Debug mode stays off unless JPARTY_DEBUG is set to a truthy value."""
    assert not config.env_flag_enabled(config.DEBUG_ENV_VAR, env)


def _record_debug_mode_at_launch(monkeypatch: object) -> list[bool]:
    """Reset debug mode and record whether it is on when the GUI would start."""
    seen = []
    monkeypatch.setattr(config, "_debug_mode_requested", False)
    monkeypatch.setattr(
        main, "launch_gui", lambda: seen.append(config.debug_mode_enabled())
    )
    return seen


def test_main_debug_flag_enables_single_monitor_mode(monkeypatch: object) -> None:
    """The --debug CLI flag turns on debug mode before the GUI launches.

    The flag is recorded in ``jparty.app.config``, so every module that asks
    ``config.debug_mode_enabled()`` sees it, not just ``bootstrap``.
    """
    monkeypatch.delenv(config.DEBUG_ENV_VAR, raising=False)
    seen = _record_debug_mode_at_launch(monkeypatch)
    main.main(["--debug"])
    assert seen == [True]


def test_main_without_debug_flag_keeps_debug_mode(monkeypatch: object) -> None:
    """Launching without --debug or JPARTY_DEBUG keeps debug mode off."""
    monkeypatch.delenv(config.DEBUG_ENV_VAR, raising=False)
    seen = _record_debug_mode_at_launch(monkeypatch)
    main.main([])
    assert seen == [False]


def test_main_reads_debug_env_var_loaded_after_config_import(
    monkeypatch: object,
) -> None:
    """JPARTY_DEBUG set after config import (e.g. from .env) still applies."""
    seen = _record_debug_mode_at_launch(monkeypatch)
    monkeypatch.setenv(config.DEBUG_ENV_VAR, "1")
    main.main([])
    assert seen == [True]
