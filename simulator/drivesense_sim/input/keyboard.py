"""Keyboard input. The only module in the package that reads pygame input.

Pedals come from held-key state; gear changes come from discrete KEYDOWN
events, because a held Shift key would otherwise walk up through every gear in
a single frame.
"""

from __future__ import annotations

from collections.abc import Iterable

import pygame

from drivesense_sim.config import SimConfig
from drivesense_sim.core.state import ControlInput, VehicleState
from drivesense_sim.input.providers import ControlSmoother

KEY_HINTS: tuple[tuple[str, str], ...] = (
    ("W", "throttle"),
    ("S", "brake"),
    ("A / D", "steer"),
    ("SHIFT", "gear up"),
    ("CTRL", "gear down"),
    ("R", "reverse"),
    ("SPACE", "clutch"),
    ("N", "neutral"),
    ("F1", "record"),
    ("ESC", "quit"),
)


class KeyboardInputProvider:
    def __init__(self, config: SimConfig) -> None:
        self._smoother = ControlSmoother(config)
        self._shift_up = False
        self._shift_down = False
        self._reverse = False
        self._neutral = False

    def handle_events(self, events: Iterable[pygame.event.Event]) -> None:
        """Latch one-shot gear events. Call once per rendered frame."""
        for event in events:
            if event.type != pygame.KEYDOWN:
                continue
            if event.key in (pygame.K_LSHIFT, pygame.K_RSHIFT):
                self._shift_up = True
            elif event.key in (pygame.K_LCTRL, pygame.K_RCTRL):
                self._shift_down = True
            elif event.key == pygame.K_r:
                self._reverse = True
            elif event.key == pygame.K_n:
                self._neutral = True

    def poll(self, state: VehicleState, dt: float) -> ControlInput:
        keys = pygame.key.get_pressed()

        steer = 0.0
        if keys[pygame.K_a]:
            steer -= 1.0
        if keys[pygame.K_d]:
            steer += 1.0

        target = ControlInput(
            throttle=1.0 if keys[pygame.K_w] else 0.0,
            brake=1.0 if keys[pygame.K_s] else 0.0,
            clutch=1.0 if keys[pygame.K_SPACE] else 0.0,
            steer=steer,
            shift_up=self._shift_up,
            shift_down=self._shift_down,
            engage_reverse=self._reverse,
            engage_neutral=self._neutral,
        )
        # Edge events are consumed by the first physics step of the frame.
        self._shift_up = self._shift_down = self._reverse = self._neutral = False

        return self._smoother.apply(target, dt)
