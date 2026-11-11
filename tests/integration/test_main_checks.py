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
    monkeypatch.setattr(main, "DEBUG_MODE", True)
    main.check_second_monitor()


def test_check_second_monitor_exits_without_two_screens(monkeypatch: object) -> None:
    """Test test check second monitor exits without two screens."""
    critical_calls = []
    monkeypatch.setattr(main, "DEBUG_MODE", False)
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


def test_main_debug_flag_enables_single_monitor_mode(monkeypatch: object) -> None:
    """The --debug CLI flag turns on debug mode before the GUI launches."""
    seen = []
    monkeypatch.setattr(main, "DEBUG_MODE", False)
    monkeypatch.setattr(main, "launch_gui", lambda: seen.append(main.DEBUG_MODE))
    main.main(["--debug"])
    assert seen == [True]


def test_main_without_debug_flag_keeps_debug_mode(monkeypatch: object) -> None:
    """Launching without --debug or JPARTY_DEBUG keeps debug mode off."""
    seen = []
    monkeypatch.delenv(config.DEBUG_ENV_VAR, raising=False)
    monkeypatch.setattr(main, "DEBUG_MODE", False)
    monkeypatch.setattr(main, "launch_gui", lambda: seen.append(main.DEBUG_MODE))
    main.main([])
    assert seen == [False]


def test_main_reads_debug_env_var_loaded_after_config_import(
    monkeypatch: object,
) -> None:
    """JPARTY_DEBUG set after config import (e.g. from .env) still applies."""
    seen = []
    monkeypatch.setattr(main, "DEBUG_MODE", False)
    monkeypatch.setenv(config.DEBUG_ENV_VAR, "1")
    monkeypatch.setattr(main, "launch_gui", lambda: seen.append(main.DEBUG_MODE))
    main.main([])
    assert seen == [True]
