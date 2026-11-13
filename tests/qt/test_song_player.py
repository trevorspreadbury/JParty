"""Tests for the Qt Multimedia based ``SongPlayer``."""

import logging
from pathlib import Path

import pytest
from PyQt6.QtMultimedia import QSoundEffect

from jparty.ui.widgets import common
from jparty.ui.widgets.common import SongPlayer, has_audio_output

pytestmark = pytest.mark.qt

INFINITE_LOOPS = QSoundEffect.Loop.Infinite.value


class FakeSignal:
    """Minimal stand-in for a Qt signal."""

    def __init__(self) -> None:
        """Start with no connected slots."""
        self.slots = []

    def connect(self, slot: object) -> None:
        """Record a connected slot."""
        self.slots.append(slot)

    def emit(self) -> None:
        """Call every connected slot."""
        for slot in self.slots:
            slot()


class FakeSoundEffect:
    """Record what ``SongPlayer`` asks a sound effect to do, without audio."""

    Status = QSoundEffect.Status
    Loop = QSoundEffect.Loop
    instances = []

    def __init__(self) -> None:
        """Start stopped, with one loop and no source."""
        self.source = None
        self.loop_count = 1
        self.play_calls = 0
        self.stop_calls = 0
        self.current_status = QSoundEffect.Status.Ready
        self.statusChanged = FakeSignal()
        FakeSoundEffect.instances.append(self)

    def setSource(self, url: object) -> None:
        """Record the source URL."""
        self.source = url

    def setLoopCount(self, count: int) -> None:
        """Record the loop count."""
        self.loop_count = count

    def play(self) -> None:
        """Count a play request."""
        self.play_calls += 1

    def stop(self) -> None:
        """Count a stop request."""
        self.stop_calls += 1

    def status(self) -> object:
        """Return the current load status."""
        return self.current_status


@pytest.fixture()
def fake_player(monkeypatch: object, qapp: object) -> tuple:
    """Build a ``SongPlayer`` whose clips are ``FakeSoundEffect`` objects."""
    FakeSoundEffect.instances = []
    monkeypatch.setattr(common, "QSoundEffect", FakeSoundEffect)
    player = SongPlayer()
    clips = {
        Path(effect.source.toLocalFile()).name: effect
        for effect in FakeSoundEffect.instances
    }
    return player, clips


def test_song_player_loads_every_packaged_clip(fake_player: tuple) -> None:
    """Each clip should point at an existing packaged wav file."""
    _player, clips = fake_player

    assert set(clips) == {"intro.wav", "final.wav", "stumped.wav", "dd.wav"}
    for effect in clips.values():
        assert Path(effect.source.toLocalFile()).is_file()


def test_intro_loops_until_stopped(fake_player: tuple) -> None:
    """Repeating intro music should loop forever and stop on request."""
    player, clips = fake_player

    player.play(repeat=True)

    assert clips["intro.wav"].loop_count == INFINITE_LOOPS
    assert clips["intro.wav"].play_calls == 1

    player.stop()

    assert clips["intro.wav"].stop_calls == 1


def test_final_music_replaces_intro_and_plays_once(fake_player: tuple) -> None:
    """Starting Final music should stop the intro and play Final one time."""
    player, clips = fake_player
    player.play(repeat=True)

    player.final()

    assert clips["intro.wav"].stop_calls == 1
    assert clips["final.wav"].loop_count == 1
    assert clips["final.wav"].play_calls == 1


def test_stop_without_music_is_a_no_op(fake_player: tuple) -> None:
    """Stopping before any music starts should not raise or stop cues."""
    player, clips = fake_player

    player.stop()

    assert all(effect.stop_calls == 0 for effect in clips.values())


def test_cues_play_and_are_not_cut_off_by_stop(fake_player: tuple) -> None:
    """Short cues play once and are left alone when music stops."""
    player, clips = fake_player
    player.play(repeat=True)

    player.daily_double()
    player.stumped()
    player.stop()

    assert clips["dd.wav"].play_calls == 1
    assert clips["stumped.wav"].play_calls == 1
    assert clips["dd.wav"].stop_calls == 0
    assert clips["stumped.wav"].stop_calls == 0


def test_clip_load_error_is_logged(fake_player: tuple, caplog: object) -> None:
    """A clip that fails to load should be reported in the log."""
    _player, clips = fake_player
    effect = clips["dd.wav"]

    effect.current_status = QSoundEffect.Status.Error
    with caplog.at_level(logging.ERROR):
        effect.statusChanged.emit()

    assert "Could not load audio asset dd.wav" in caplog.text


def test_has_audio_output_reflects_qt_devices(monkeypatch: object) -> None:
    """The startup audio check should follow Qt's list of output devices."""
    monkeypatch.setattr(common.QMediaDevices, "audioOutputs", lambda: [])
    assert has_audio_output() is False

    monkeypatch.setattr(common.QMediaDevices, "audioOutputs", lambda: [object()])
    assert has_audio_output() is True


def test_real_clips_load_without_errors(qapp: object, qtbot: object) -> None:
    """Qt should decode every packaged wav file. Nothing is played."""
    if not has_audio_output():
        pytest.skip("No audio output device available")
    player = SongPlayer()
    effects = [
        effect
        for name, effect in vars(player).items()
        if isinstance(effect, QSoundEffect)
    ]
    assert len(effects) == len(["intro", "final", "stumped", "dd"])

    qtbot.waitUntil(
        lambda: all(
            effect.status() != QSoundEffect.Status.Loading for effect in effects
        ),
        timeout=5000,
    )

    assert all(effect.status() == QSoundEffect.Status.Ready for effect in effects)
