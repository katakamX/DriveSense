"""Fixed-timestep clock.

Physics must advance in whole, identical steps or the model is not
deterministic and none of the dynamics tests reproduce. The accumulator
converts irregular real frame times into a whole number of fixed steps and
carries the remainder forward.

Two modes exist because a headless dataset run must not take as long as the
drive it simulates.
"""

from __future__ import annotations

import time


class FixedTimestepClock:
    def __init__(self, dt: float, *, realtime: bool = True, max_steps_per_frame: int = 12) -> None:
        self.dt = dt
        self.realtime = realtime
        self.max_steps_per_frame = max_steps_per_frame
        self._accumulator = 0.0
        self._last = time.perf_counter()

    def reset(self) -> None:
        self._accumulator = 0.0
        self._last = time.perf_counter()

    def steps_for_realtime(self) -> int:
        """Number of fixed steps owed since the last call."""
        now = time.perf_counter()
        elapsed = now - self._last
        self._last = now
        # Guard against a debugger pause or a stalled frame demanding hundreds
        # of catch-up steps at once.
        self._accumulator = min(self._accumulator + elapsed, self.dt * self.max_steps_per_frame)

        steps = int(self._accumulator / self.dt)
        self._accumulator -= steps * self.dt
        return steps

    def steps_for_duration(self, duration_s: float) -> int:
        """Whole steps needed to cover `duration_s` of simulated time."""
        return int(round(duration_s / self.dt))
