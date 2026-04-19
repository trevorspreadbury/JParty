import pytest

from jparty.app import bootstrap as main

pytestmark = pytest.mark.integration


def test_check_internet_exits_when_request_fails(monkeypatch):
    critical_calls = []
    monkeypatch.setattr(
        main.requests,
        "get",
        lambda url: (_ for _ in ()).throw(main.requests.exceptions.ConnectionError()),
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


def test_check_second_monitor_skips_when_debug_enabled(monkeypatch):
    monkeypatch.setattr(main, "DEBUG_MODE", True)

    main.check_second_monitor()


def test_check_second_monitor_exits_without_two_screens(monkeypatch):
    critical_calls = []
    monkeypatch.setattr(main, "DEBUG_MODE", False)
    monkeypatch.setattr(
        main.QApplication,
        "instance",
        lambda: type(
            "App",
            (),
            {
                "screens": lambda self: [object()],
                "processEvents": lambda self: None,
            },
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
