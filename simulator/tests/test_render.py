"""Rendering and keyboard tests, run against SDL's dummy video driver.

These are smoke tests: they prove the window, HUD and input mapping work
without a display, which is what CI can verify. They are not a substitute for
looking at the thing.
"""

from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pygame  # noqa: E402
import pytest  # noqa: E402

from drivesense_sim.config import SimConfig  # noqa: E402
from drivesense_sim.core.state import VehicleState  # noqa: E402
from drivesense_sim.input.keyboard import KEY_HINTS, KeyboardInputProvider  # noqa: E402
from drivesense_sim.render import hud  # noqa: E402
from drivesense_sim.render.app import AppOptions, SimulatorApp  # noqa: E402


@pytest.fixture
def app(tmp_path: Path) -> Iterator[SimulatorApp]:
    application = SimulatorApp(AppOptions(recording_dir=tmp_path))
    yield application
    application.close()


def test_app_renders_frames_without_a_display(app: SimulatorApp) -> None:
    for _ in range(5):
        app.tick()

    assert app.running is True
    assert app.session.state.sim_t >= 0.0


def test_rendered_frame_is_not_blank(app: SimulatorApp, tmp_path: Path) -> None:
    app.tick()
    app.tick()

    screenshot = tmp_path / "frame.png"
    pygame.image.save(app.surface, str(screenshot))

    assert screenshot.stat().st_size > 0
    colours = {
        app.surface.get_at((x, y))[:3] for x in range(0, 1280, 40) for y in range(0, 760, 40)
    }
    # A blank window would yield a single colour.
    assert len(colours) > 5


def test_escape_stops_the_loop(app: SimulatorApp) -> None:
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    app.handle_events()

    assert app.running is False


def test_f1_toggles_recording(app: SimulatorApp) -> None:
    assert app.session.recording is False

    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1))
    app.handle_events()
    assert app.session.recording is True

    app.tick()
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1))
    app.handle_events()
    assert app.session.recording is False


@pytest.mark.parametrize(
    ("key", "field"),
    [
        (pygame.K_LSHIFT, "shift_up"),
        (pygame.K_RSHIFT, "shift_up"),
        (pygame.K_LCTRL, "shift_down"),
        (pygame.K_RCTRL, "shift_down"),
        (pygame.K_r, "engage_reverse"),
        (pygame.K_n, "engage_neutral"),
    ],
)
def test_gear_keys_are_edge_triggered(app: SimulatorApp, key: int, field: str) -> None:
    provider = KeyboardInputProvider(SimConfig())
    provider.handle_events([pygame.event.Event(pygame.KEYDOWN, key=key)])

    first = provider.poll(VehicleState(), 1 / 120)
    second = provider.poll(VehicleState(), 1 / 120)

    assert getattr(first, field) is True
    # Held keys must not repeat the shift on the following step.
    assert getattr(second, field) is False


class _FakeKeys:
    """Stands in for pygame.key.get_pressed(), which cannot be driven
    synthetically. Lets the held-key pedal mapping be tested without a human."""

    def __init__(self, *held: int) -> None:
        self._held = set(held)

    def __getitem__(self, key: int) -> bool:
        return key in self._held


@pytest.mark.parametrize(
    ("held", "field", "expected"),
    [
        ((pygame.K_w,), "throttle", True),
        ((pygame.K_s,), "brake", True),
        ((pygame.K_SPACE,), "clutch", True),
        ((), "throttle", False),
    ],
)
def test_held_keys_drive_the_pedals(
    monkeypatch: pytest.MonkeyPatch, held: tuple[int, ...], field: str, expected: bool
) -> None:
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: _FakeKeys(*held))
    provider = KeyboardInputProvider(SimConfig())

    control = provider.poll(VehicleState(), 1 / 120)

    assert (getattr(control, field) > 0.0) is expected


@pytest.mark.parametrize(
    ("held", "sign"),
    [((pygame.K_a,), -1), ((pygame.K_d,), 1), ((pygame.K_a, pygame.K_d), 0), ((), 0)],
)
def test_held_keys_drive_steering(
    monkeypatch: pytest.MonkeyPatch, held: tuple[int, ...], sign: int
) -> None:
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: _FakeKeys(*held))
    provider = KeyboardInputProvider(SimConfig())

    steer = provider.poll(VehicleState(), 1 / 120).steer

    assert (0 if steer == 0 else (1 if steer > 0 else -1)) == sign


def test_pedals_ramp_rather_than_snapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Binary keys must not produce square-wave telemetry."""
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: _FakeKeys(pygame.K_w))
    provider = KeyboardInputProvider(SimConfig())

    first = provider.poll(VehicleState(), 1 / 120).throttle
    second = provider.poll(VehicleState(), 1 / 120).throttle

    assert 0.0 < first < 1.0
    assert first < second < 1.0


def test_key_hints_cover_the_documented_controls() -> None:
    keys = {key for key, _ in KEY_HINTS}

    assert {"W", "S", "A / D", "SHIFT", "CTRL", "R", "SPACE"} <= keys


@pytest.mark.parametrize(
    ("clutch", "expected"),
    [(0.0, "ENGAGED"), (0.5, "SLIPPING"), (1.0, "DISENGAGED")],
)
def test_clutch_status_labels(clutch: float, expected: str) -> None:
    assert hud.clutch_status(VehicleState(clutch=clutch)) == expected
