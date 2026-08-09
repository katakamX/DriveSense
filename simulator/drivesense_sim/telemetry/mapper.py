"""VehicleState → TelemetryFrame.

The single place the conversion happens. Every value is read from simulated
state; nothing here invents data. Optional measurement noise is available
behind configuration and is disabled by default.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from drivesense_contracts import TelemetryFrame
from drivesense_sim.config import SimConfig
from drivesense_sim.core.state import VehicleState

METRES_PER_DEGREE_LAT = 111_320.0

# Standard deviations applied only when sensor noise is explicitly enabled.
NOISE_SIGMA = {
    "speed_kph": 0.15,
    "engine_rpm": 12.0,
    "accel_ms2": 0.05,
    "coolant_c": 0.2,
}


class TelemetryMapper:
    def __init__(
        self,
        config: SimConfig,
        trip_id: str,
        started_at: datetime,
        source: str = "simulator",
    ) -> None:
        self._config = config
        self._trip_id = trip_id
        self._started_at = started_at
        self._source = source
        self._seq = 0
        self._rng = random.Random(config.sensor_noise_seed)

    def _noisy(self, key: str, value: float) -> float:
        if not self._config.sensor_noise_enabled:
            return value
        return value + self._rng.gauss(0.0, NOISE_SIGMA[key])

    def to_frame(self, state: VehicleState) -> TelemetryFrame:
        cfg = self._config

        lat = cfg.origin_lat + state.pos_y / METRES_PER_DEGREE_LAT
        lon = cfg.origin_lon + state.pos_x / (
            METRES_PER_DEGREE_LAT * math.cos(math.radians(cfg.origin_lat))
        )

        frame = TelemetryFrame(
            trip_id=self._trip_id,
            source="simulator",
            seq=self._seq,
            sim_t=round(state.sim_t, 6),
            # Simulated time, not wall-clock: a headless run compresses thirty
            # minutes of driving into seconds and must still stamp frames as
            # thirty minutes apart.
            ts=self._started_at + timedelta(seconds=state.sim_t),
            speed_kph=self._noisy("speed_kph", state.speed_kph),
            accel_ms2=self._noisy("accel_ms2", state.accel_ms2),
            engine_rpm=max(0.0, self._noisy("engine_rpm", state.engine_rpm)),
            throttle_pct=state.throttle * 100.0,
            brake_pct=state.brake * 100.0,
            clutch_pct=state.clutch * 100.0,
            gear=state.gear,
            engine_load_pct=state.engine_load * 100.0,
            engine_on=state.engine_on,
            rev_limiter_active=state.rev_limiter_active,
            steering_deg=state.steering_deg,
            yaw_rate_dps=math.degrees(state.yaw_rate),
            lateral_accel_ms2=state.lateral_accel_ms2,
            heading_deg=math.degrees(state.heading) % 360.0,
            distance_m=state.distance_m,
            lat=lat,
            lon=lon,
            coolant_c=self._noisy("coolant_c", state.coolant_c),
        )
        self._seq += 1
        return frame
