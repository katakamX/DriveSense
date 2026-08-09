"""Vehicle specification and simulation configuration.

Every physical constant lives here rather than being scattered through the
model, so a second vehicle is a new JSON file and not a code change.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

VEHICLES_DIR = Path(__file__).parent / "vehicles"


class VehicleSpec(BaseModel):
    """Physical parameters of a simulated vehicle.

    These are plausible values for a small hatchback. The model they feed is
    physics-*inspired* and simplified — it is not a validated vehicle dynamics
    model, and telemetry derived from it is smoother than a real car's.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    mass_kg: float = Field(gt=0)
    wheel_radius_m: float = Field(gt=0)
    wheelbase_m: float = Field(gt=0)

    # --- Powertrain ---------------------------------------------------------
    gear_ratios: list[float] = Field(min_length=1, description="Forward gears, 1..n")
    reverse_ratio: float = Field(gt=0)
    final_drive: float = Field(gt=0)
    drivetrain_efficiency: float = Field(gt=0, le=1)

    torque_curve: list[tuple[float, float]] = Field(
        min_length=2, description="(rpm, newton-metres) at wide-open throttle"
    )
    idle_rpm: float = Field(gt=0)
    redline_rpm: float = Field(gt=0)
    stall_rpm: float = Field(gt=0)
    limiter_hysteresis_rpm: float = Field(ge=0)

    engine_inertia_kgm2: float = Field(gt=0)
    engine_friction_nm: float = Field(ge=0)
    engine_friction_nm_per_rad_s: float = Field(ge=0)
    idle_governor_max_nm: float = Field(ge=0)

    # --- Chassis ------------------------------------------------------------
    max_brake_force_n: float = Field(gt=0)
    drag_coefficient: float = Field(gt=0)
    frontal_area_m2: float = Field(gt=0)
    air_density: float = Field(gt=0)
    rolling_resistance_coeff: float = Field(ge=0)

    # --- Steering -----------------------------------------------------------
    max_steering_deg: float = Field(gt=0)
    steering_rate_dps: float = Field(gt=0)
    steering_return_dps: float = Field(gt=0)
    steering_falloff_kph: float = Field(gt=0, description="Speed at which authority halves")
    max_lateral_accel_ms2: float = Field(
        gt=0, description="Tyre grip limit; beyond this the vehicle understeers"
    )

    # --- Thermal ------------------------------------------------------------
    coolant_ambient_c: float
    coolant_operating_c: float
    coolant_time_constant_s: float = Field(gt=0)

    @property
    def max_forward_gear(self) -> int:
        return len(self.gear_ratios)

    @classmethod
    def load(cls, name_or_path: str | Path = "hatchback") -> VehicleSpec:
        path = Path(name_or_path)
        if not path.suffix:
            path = VEHICLES_DIR / f"{path.name}.json"
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))


class SimConfig(BaseModel):
    """Simulation rates and behaviour switches.

    The three rates are deliberately independent: physics must be a fixed,
    deterministic timestep, rendering follows the display, and telemetry is
    sampled at the rate a real logger would use.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    physics_hz: float = Field(default=120.0, gt=0)
    telemetry_hz: float = Field(default=10.0, gt=0)
    render_fps: int = Field(default=60, gt=0)

    # Rate at which pedal inputs ramp toward their target, in units per second.
    # Keyboard input is binary; ramping produces analog-like traces instead of
    # square waves, which matters for downstream feature engineering.
    throttle_rate_per_s: float = Field(default=2.2, gt=0)
    brake_rate_per_s: float = Field(default=3.5, gt=0)
    clutch_rate_per_s: float = Field(default=4.0, gt=0)

    # Realistic manual-transmission stalling. Off by default: it makes casual
    # demonstration frustrating without adding telemetry value.
    stall_enabled: bool = False

    # Optional measurement noise. Off by default; telemetry is otherwise an
    # exact reading of simulated state.
    sensor_noise_enabled: bool = False
    sensor_noise_seed: int = 12345

    origin_lat: float = 12.9716
    origin_lon: float = 77.5946

    @property
    def physics_dt(self) -> float:
        return 1.0 / self.physics_hz

    @property
    def telemetry_period(self) -> float:
        return 1.0 / self.telemetry_hz
