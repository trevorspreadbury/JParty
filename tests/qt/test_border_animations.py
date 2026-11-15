"""Tests for border and podium animations (#105).

Animations used to run on Python threads that called widget methods, which
hung or crashed the app on quit. They now run on GUI-thread ``QTimer``s.
"""

import threading
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QWidget

from jparty.domain.models import Player
from jparty.ui.widgets import scoreboard
from jparty.ui.widgets.borders import Borders, HostBorders
from jparty.ui.widgets.scoreboard import PlayerWidget

pytestmark = pytest.mark.qt


def _lit(border: object) -> bool:
    """Return whether a border widget is currently lit."""
    return bool(border._BorderWidget__lit)


def _hint_shown(border: object) -> bool:
    """Return whether a host border is showing a hint image."""
    pixmap = border.hint_label.pixmap()
    return pixmap is not None and not pixmap.isNull()


def _borders(qtbot: object, cls: type = HostBorders) -> Borders:
    """Build borders on a parent window, then show it like a display does."""
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(400, 300)
    borders = cls(parent)
    # Keep the parent alive; Borders itself is not a QObject.
    borders.test_parent = parent
    parent.show()
    return borders


def _player_widget(qtbot: object) -> PlayerWidget:
    """Return a podium widget for a single test player."""
    game = SimpleNamespace(soliciting_player=False, active_question=None)
    player = Player("Alice", SimpleNamespace(send=lambda *args, **kwargs: None), 0)
    widget = PlayerWidget(game, player)
    qtbot.addWidget(widget)
    return widget


def test_animations_start_no_threads(qtbot: object, monkeypatch: object) -> None:
    """Test no animation starts a Python thread that would touch widgets."""
    started = []
    monkeypatch.setattr(
        threading.Thread, "start", lambda thread: started.append(thread.name)
    )
    borders = _borders(qtbot)
    borders.flash()
    borders.arrowhints(True)
    borders.spacehints(True)
    player_widget = _player_widget(qtbot)
    player_widget.buzz_hint()
    player_widget.run_lights()
    assert started == []


def test_flash_turns_borders_off_on_off(qtbot: object) -> None:
    """Test flash keeps its off, on (200 ms), off (400 ms) sequence."""
    borders = _borders(qtbot, Borders)
    borders.lights(True)
    borders.flash()
    assert not any(_lit(b) for b in borders)
    qtbot.waitUntil(lambda: all(_lit(b) for b in borders), timeout=1000)
    qtbot.waitUntil(lambda: not any(_lit(b) for b in borders), timeout=1000)
    assert not borders._flash_timer.isActive()


def test_hints_blink_until_turned_off(qtbot: object) -> None:
    """Test hints show at once, blink every 500 ms, and stop when turned off."""
    borders = _borders(qtbot)
    borders.spacehints(True)
    assert all(_hint_shown(b) for b in borders)
    qtbot.waitUntil(lambda: not any(_hint_shown(b) for b in borders), timeout=1500)
    qtbot.waitUntil(lambda: all(_hint_shown(b) for b in borders), timeout=1500)
    borders.spacehints(False)
    assert not borders._hint_timer.isActive()
    assert not any(_hint_shown(b) for b in borders)


def test_arrow_hints_replace_space_hints(qtbot: object) -> None:
    """Test starting arrow hints switches the blinking image to arrows."""
    borders = _borders(qtbot)
    borders.spacehints(True)
    borders.arrowhints(True)
    assert borders._hint_key == "arrow"
    assert all(b.colors for b in borders)
    borders.arrowhints(False)
    assert not borders._hint_timer.isActive()
    assert not any(b.colors for b in borders)


def test_stop_halts_all_border_timers(qtbot: object) -> None:
    """Test stop(), called when a display closes, halts every border timer."""
    borders = _borders(qtbot)
    borders.flash()
    borders.arrowhints(True)
    borders.stop()
    assert not borders._flash_timer.isActive()
    assert not borders._hint_timer.isActive()


def test_buzz_hint_lights_podium_briefly(qtbot: object) -> None:
    """Test a buzz hint lights the podium and turns it off after 250 ms."""
    widget = _player_widget(qtbot)
    widget.buzz_hint()
    assert widget.background is widget.active_background
    qtbot.waitUntil(lambda: widget.background is widget.main_background, timeout=1000)


def test_run_lights_counts_down_then_stays_lit(
    qtbot: object, monkeypatch: object
) -> None:
    """Test run_lights steps through each countdown image, then stays lit."""
    monkeypatch.setattr(scoreboard, "LIGHTS_STEP_MS", 20)
    widget = _player_widget(qtbot)
    seen = []
    original_update = widget.update

    def record_update() -> None:
        if not seen or seen[-1] is not widget.background:
            seen.append(widget.background)
        original_update()

    monkeypatch.setattr(widget, "update", record_update)
    widget.run_lights()
    qtbot.waitUntil(lambda: widget.background is widget.active_background)
    assert seen == [*widget.lights_backgrounds, widget.active_background]
    assert not widget._PlayerWidget__light_timer.isActive()


def test_stop_lights_cancels_countdown(qtbot: object) -> None:
    """Test stop_lights halts the countdown and restores the base podium."""
    widget = _player_widget(qtbot)
    widget.run_lights()
    assert widget.background is widget.lights_backgrounds[0]
    widget.stop_lights()
    assert not widget._PlayerWidget__light_timer.isActive()
    assert widget.background is widget.main_background
