"""The pygame application: input → fixed-step physics → render.

Rendering follows the display; physics advances in fixed 1/120 s steps via the
accumulator in `core.clock`. The two are deliberately decoupled — variable-dt
physics would be non-deterministic and none of the dynamics tests would
reproduce.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pygame

from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.core.clock import FixedTimestepClock
from drivesense_sim.input.keyboard import KEY_HINTS, KeyboardInputProvider
from drivesense_sim.render import hud, scene, theme
from drivesense_sim.session import SimulationSession
from drivesense_sim.telemetry.sinks import DEFAULT_RECORDING_DIR, JsonlSink

WINDOW_SIZE = (1280, 760)
PANEL_HEIGHT = 250


@dataclass
class AppOptions:
    record: bool = False
    recording_dir: Path = DEFAULT_RECORDING_DIR
    vehicle: str = "hatchback"
    window_size: tuple[int, int] = WINDOW_SIZE


class SimulatorApp:
    def __init__(self, options: AppOptions | None = None, config: SimConfig | None = None) -> None:
        self.options = options or AppOptions()
        self.config = config or SimConfig()
        self.spec = VehicleSpec.load(self.options.vehicle)

        pygame.init()
        pygame.display.set_caption("DriveSense — Vehicle Simulator")
        self.surface = pygame.display.set_mode(self.options.window_size)
        self.fonts = hud.Fonts()
        self.clock = pygame.time.Clock()

        self.provider = KeyboardInputProvider(self.config)
        self.session = SimulationSession(self.provider, self.spec, self.config)
        self.physics_clock = FixedTimestepClock(self.config.physics_dt)
        self.running = True

        if self.options.record:
            self.toggle_recording()

    # --- Recording ----------------------------------------------------------

    def toggle_recording(self) -> None:
        if self.session.recording:
            self.session.detach_sink()
            self._sink = None
        else:
            self._sink = JsonlSink(self.options.recording_dir)
            self.session.attach_sink(self._sink)

    @property
    def frames_written(self) -> int:
        sink = getattr(self, "_sink", None)
        return sink.frames_written if isinstance(sink, JsonlSink) else 0

    # --- Loop ---------------------------------------------------------------

    def handle_events(self) -> None:
        events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_F1:
                    self.toggle_recording()
        self.provider.handle_events(events)

    def update(self) -> None:
        for _ in range(self.physics_clock.steps_for_realtime()):
            self.session.step_once()

    def render(self) -> None:
        width, height = self.options.window_size
        scene_rect = pygame.Rect(0, 0, width, height - PANEL_HEIGHT)
        panel_rect = pygame.Rect(0, height - PANEL_HEIGHT, width, PANEL_HEIGHT)

        self.surface.fill(theme.SURFACE_BASE)
        scene.draw(self.surface, self.session.state, scene_rect)
        hud.draw(
            self.surface,
            self.fonts,
            self.session.state,
            self.spec,
            panel_rect,
            recording=self.session.recording,
            frames_written=self.frames_written,
            key_hints=KEY_HINTS,
            fps=self.clock.get_fps(),
        )
        pygame.display.flip()

    def tick(self) -> None:
        """One full frame. Exposed separately so tests can drive the loop."""
        self.handle_events()
        self.update()
        self.render()
        self.clock.tick(self.config.render_fps)

    def run(self) -> None:
        self.physics_clock.reset()
        try:
            while self.running:
                self.tick()
        finally:
            self.close()

    def close(self) -> None:
        self.session.close()
        pygame.quit()
