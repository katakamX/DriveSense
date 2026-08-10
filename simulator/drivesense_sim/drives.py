"""Scripted drives.

`DEMO_DRIVE` exercises every behaviour the model claims to have: launch,
upshifts through the box, a corner, braking, a downshift, a stop, and revving
in neutral. It backs the golden regression test and gives the headless mode
something realistic to record.

The four *profile* families below (`CALM_DRIVES`, `NORMAL_DRIVES`,
`AGGRESSIVE_DRIVES`, `HIGH_RISK_DRIVES`) exist to generate labelled training
data for Milestone 8: each is authored so that the labelling rubric in
`ml/pipelines/labeling/rubric.py` classifies its windows into the matching
class *by construction*, rather than by a rubric guessing after the fact.

The pedal levels below are chosen against this vehicle's numbers
(`vehicles/hatchback.json`: 1250 kg, 9000 N max brake force -> ~7.2 m/s^2 at
`brake=1.0`, before drag) and against the two thresholds the rubric inherits
from `app.core.events.thresholds`:

    brake=0.20  ->  ~-1.4 m/s^2   gentle; CALM/NORMAL territory
    brake=0.30  ->  ~-2.2 m/s^2   firm; trips the rubric's -2.0 line
    brake=0.40  ->  ~-2.9 m/s^2   hard, still short of the -3.5 harsh line
    brake=0.70  ->  ~-5.0 m/s^2   past -3.5: registers harsh-braking frames

Note that `harsh_braking_per_min` counts *frames* below -3.5 m/s^2, not
distinct brake applications (see `app.core.events.detectors`), so at 10 Hz a
single half-second stab of the brake is already ~10 events/min. Only the
HIGH_RISK scripts brake hard enough to reach that, and they do it repeatedly.

Speeding is measured against `DEFAULT_SPEED_LIMIT_KPH = 100.0` in
`ml/pipelines/featurise.py`, with the +5 kph margin from
`SPEEDING_MARGIN_KPH`, so "speeding" here means holding above ~105 kph.
"""

from __future__ import annotations

from drivesense_sim.input.providers import ScriptStep

DEMO_DRIVE: list[ScriptStep] = [
    ScriptStep(1.0),  # idle
    ScriptStep(0.5, clutch=1.0, shift_up=True),  # neutral -> 1st
    ScriptStep(0.6, clutch=1.0, throttle=0.3),  # blip while disengaged
    ScriptStep(3.0, throttle=1.0),  # launch in 1st
    ScriptStep(0.4, clutch=1.0, shift_up=True),  # -> 2nd
    ScriptStep(3.5, throttle=1.0),
    ScriptStep(0.4, clutch=1.0, shift_up=True),  # -> 3rd
    ScriptStep(4.0, throttle=0.9),
    ScriptStep(0.4, clutch=1.0, shift_up=True),  # -> 4th
    ScriptStep(4.0, throttle=0.7),
    ScriptStep(3.0, throttle=0.4, steer=0.35),  # steady corner
    ScriptStep(3.0, brake=0.6),  # braking
    ScriptStep(0.4, clutch=1.0, shift_down=True),  # -> 3rd
    ScriptStep(2.0, throttle=0.5),
    ScriptStep(2.5, brake=0.9),  # to a stop
    ScriptStep(0.5, clutch=1.0, engage_neutral=True),
    ScriptStep(2.5, throttle=0.8),  # rev in neutral
    ScriptStep(1.0),
]


# --- Building blocks ------------------------------------------------------


def _shift_up() -> ScriptStep:
    return ScriptStep(0.4, clutch=1.0, shift_up=True)


def _launch(to_gear: int, throttle: float, segment_s: float) -> list[ScriptStep]:
    """Neutral -> `to_gear`, holding `throttle` for `segment_s` in each gear.

    `throttle` has to be enough to actually pull the car up to road speed
    before the next upshift. This gearbox is tall — 5th is ~1500 rpm at
    50 kph — so a too-gentle launch leaves the engine bogged below
    1200 rpm in the upper gears and the car never exceeds a walking pace.
    (The first version of these scripts used 0.30-0.42 here and produced
    drives whose *entire* speed range topped out around 14 kph.) Even for
    the CALM profile the ramp therefore uses a firm throttle; what makes
    that drive calm is the long steady cruise that follows it, not the
    launch.
    """
    steps = [ScriptStep(0.5, clutch=1.0, shift_up=True)]  # neutral -> 1st
    for _ in range(to_gear - 1):
        steps.append(ScriptStep(segment_s, throttle=throttle))
        steps.append(_shift_up())
    steps.append(ScriptStep(segment_s, throttle=throttle))
    return steps


def _cruise(seconds: float, throttle: float, steer: float = 0.0) -> list[ScriptStep]:
    """One long held segment.

    Kept as a single `ScriptStep` rather than several short ones so the pedal
    target never moves: `ControlSmoother` then has nothing to ramp, and the
    window's `accel_std` settles to the near-zero value CALM requires.
    """
    return [ScriptStep(seconds, throttle=throttle, steer=steer)]


def _sweeper(seconds: float, throttle: float, steer: float) -> list[ScriptStep]:
    """A left-then-right pair of steady curves, for lateral content."""
    half = seconds / 2.0
    return [
        ScriptStep(half, throttle=throttle, steer=steer),
        ScriptStep(half, throttle=throttle, steer=-steer),
    ]


# --- CALM ------------------------------------------------------------------
# Steady speed, smooth inputs, no braking inside the cruise. The rubric's CALM
# rule needs speed_cv <= 0.03, accel_std <= 0.20 and lat_accel_std <= 0.25 with
# no harsh-braking or rapid-acceleration frames at all, so the spin-up is kept
# short and gentle and everything after it is one unbroken held throttle.

CALM_DRIVE_A: list[ScriptStep] = [
    ScriptStep(2.0),
    *_launch(to_gear=5, throttle=0.55, segment_s=6.0),
    *_cruise(165.0, throttle=0.32),
    ScriptStep(8.0, brake=0.15),
]

CALM_DRIVE_B: list[ScriptStep] = [
    ScriptStep(2.0),
    *_launch(to_gear=5, throttle=0.50, segment_s=7.0),
    *_cruise(130.0, throttle=0.28),
    *_cruise(70.0, throttle=0.30, steer=0.02),  # very gentle constant curve
    ScriptStep(8.0, brake=0.15),
]

CALM_DRIVE_C: list[ScriptStep] = [
    ScriptStep(2.0),
    *_launch(to_gear=6, throttle=0.58, segment_s=6.0),
    *_cruise(100.0, throttle=0.30),
    *_cruise(100.0, throttle=0.36),  # single small step change in cruise speed
    ScriptStep(8.0, brake=0.15),
]

CALM_DRIVES: dict[str, list[ScriptStep]] = {
    "a": CALM_DRIVE_A,
    "b": CALM_DRIVE_B,
    "c": CALM_DRIVE_C,
}


# --- NORMAL ----------------------------------------------------------------
# Unremarkable driving: speed changes, gentle corners, gentle stops. Must stay
# under every AGGRESSIVE cutoff — accel_max < 1.5, lat_accel_max_abs < 2.0,
# accel_std < 0.45, speeding_time_ratio < 0.5 — while being varied enough not
# to fall through into CALM.

NORMAL_DRIVE_A: list[ScriptStep] = [
    ScriptStep(1.5),
    *_launch(to_gear=3, throttle=0.45, segment_s=7.0),
    *_cruise(42.0, throttle=0.24),
    *_sweeper(30.0, throttle=0.22, steer=0.02),
    ScriptStep(6.0, throttle=0.05),
    *_cruise(40.0, throttle=0.28),
    *_sweeper(28.0, throttle=0.20, steer=0.02),
    ScriptStep(5.0, throttle=0.05),
    *_cruise(42.0, throttle=0.25),
    ScriptStep(6.0, throttle=0.05),
    *_cruise(38.0, throttle=0.27),
    ScriptStep(8.0, throttle=0.05),
]

NORMAL_DRIVE_B: list[ScriptStep] = [
    ScriptStep(1.5),
    *_launch(to_gear=3, throttle=0.44, segment_s=7.5),
    *_cruise(44.0, throttle=0.22),
    ScriptStep(5.0, throttle=0.05),
    *_sweeper(34.0, throttle=0.20, steer=0.02),
    *_cruise(46.0, throttle=0.26),
    ScriptStep(6.0, throttle=0.05),
    *_sweeper(32.0, throttle=0.19, steer=0.02),
    *_cruise(42.0, throttle=0.24),
    ScriptStep(7.0, throttle=0.05),
    *_cruise(34.0, throttle=0.26),
    ScriptStep(8.0, throttle=0.05),
]

NORMAL_DRIVE_C: list[ScriptStep] = [
    ScriptStep(1.5),
    *_launch(to_gear=3, throttle=0.46, segment_s=7.0),
    *_cruise(48.0, throttle=0.25),
    *_sweeper(36.0, throttle=0.21, steer=0.02),
    ScriptStep(6.0, throttle=0.05),
    *_cruise(44.0, throttle=0.28),
    ScriptStep(5.0, throttle=0.05),
    *_sweeper(32.0, throttle=0.19, steer=0.02),
    *_cruise(40.0, throttle=0.24),
    ScriptStep(8.0, throttle=0.05),
]

NORMAL_DRIVES: dict[str, list[ScriptStep]] = {
    "a": NORMAL_DRIVE_A,
    "b": NORMAL_DRIVE_B,
    "c": NORMAL_DRIVE_C,
}


# --- AGGRESSIVE ------------------------------------------------------------
# Hard acceleration, hard cornering, firm braking — but deliberately kept
# *short* of the HIGH_RISK rules: braking stays above -3.5 m/s^2 (no harsh
# frames), and sustained speeding is avoided so the "speeding + hard
# deceleration" compound never fires. These earn AGGRESSIVE through
# accel_max, lat_accel_max_abs and accel_std instead.

AGGRESSIVE_DRIVE_A: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=2, throttle=1.0, segment_s=5.0),
    *_sweeper(16.0, throttle=0.55, steer=0.10),  # hard, not grip-limited
    ScriptStep(5.0, brake=0.22),
    *_cruise(14.0, throttle=0.60),
    *_sweeper(16.0, throttle=0.52, steer=0.11),
    ScriptStep(5.0, brake=0.20),
    *_cruise(16.0, throttle=0.62),
    *_sweeper(18.0, throttle=0.54, steer=0.105),
    ScriptStep(6.0, brake=0.22),
    *_cruise(18.0, throttle=0.58),
    ScriptStep(7.0, brake=0.20),
]

AGGRESSIVE_DRIVE_B: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=2, throttle=1.0, segment_s=4.5),
    ScriptStep(5.0, brake=0.22),
    *_launch(to_gear=2, throttle=1.0, segment_s=4.5),  # re-launch through the box
    *_sweeper(20.0, throttle=0.56, steer=0.095),
    ScriptStep(5.5, brake=0.21),
    *_cruise(16.0, throttle=0.62),
    *_sweeper(18.0, throttle=0.50, steer=0.115),
    ScriptStep(5.0, brake=0.22),
    *_cruise(20.0, throttle=0.60),
    *_sweeper(16.0, throttle=0.54, steer=0.10),
    ScriptStep(7.0, brake=0.20),
]

AGGRESSIVE_DRIVE_C: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=2, throttle=1.0, segment_s=5.0),
    *_cruise(12.0, throttle=0.64),
    ScriptStep(4.5, brake=0.22),
    *_sweeper(22.0, throttle=0.55, steer=0.105),
    ScriptStep(5.0, brake=0.20),
    *_cruise(18.0, throttle=0.60),
    *_sweeper(20.0, throttle=0.52, steer=0.11),
    ScriptStep(5.5, brake=0.22),
    *_cruise(16.0, throttle=0.58),
    *_sweeper(16.0, throttle=0.53, steer=0.10),
    ScriptStep(7.0, brake=0.21),
]

AGGRESSIVE_DRIVES: dict[str, list[ScriptStep]] = {
    "a": AGGRESSIVE_DRIVE_A,
    "b": AGGRESSIVE_DRIVE_B,
    "c": AGGRESSIVE_DRIVE_C,
}


# --- HIGH_RISK -------------------------------------------------------------
# Deliberately over-scripted relative to the other classes: HIGH_RISK is rare
# in real driving, so leaving its frequency to chance would under-represent it
# in the training set (four variants here against three elsewhere).
#
# Each variant pairs *sustained* speeding — full throttle in a high gear, held
# well past 105 kph — with a late, hard brake (0.70-0.85, i.e. -5 m/s^2 or
# worse). That combination is what the rubric's two HIGH_RISK rules look for:
# repeated harsh-braking frames, and speeding >= 50% of a window alongside a
# deceleration past -2.0.

HIGH_RISK_DRIVE_A: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=5, throttle=1.0, segment_s=3.5),
    *_cruise(22.0, throttle=1.0),  # hold well above the limit
    ScriptStep(3.0, brake=0.80),  # late, hard
    *_cruise(20.0, throttle=1.0),
    ScriptStep(3.0, brake=0.75),
    *_cruise(20.0, throttle=1.0),
    ScriptStep(3.5, brake=0.85),
    *_cruise(18.0, throttle=1.0),
    ScriptStep(4.0, brake=0.80),
]

HIGH_RISK_DRIVE_B: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=5, throttle=1.0, segment_s=3.0),
    *_cruise(18.0, throttle=1.0),
    ScriptStep(2.5, brake=0.85),
    *_sweeper(10.0, throttle=1.0, steer=0.40),  # fast, and turning
    ScriptStep(3.0, brake=0.80),
    *_cruise(22.0, throttle=1.0),
    ScriptStep(3.0, brake=0.78),
    *_cruise(16.0, throttle=0.62),
    *_sweeper(10.0, throttle=0.95, steer=0.45),
    ScriptStep(4.0, brake=0.82),
]

HIGH_RISK_DRIVE_C: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=6, throttle=1.0, segment_s=3.0),
    *_cruise(28.0, throttle=1.0),  # long sustained speeding block
    ScriptStep(3.5, brake=0.80),
    *_cruise(26.0, throttle=1.0),
    ScriptStep(3.0, brake=0.85),
    *_cruise(24.0, throttle=1.0),
    ScriptStep(4.0, brake=0.75),
]

HIGH_RISK_DRIVE_D: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=5, throttle=1.0, segment_s=3.5),
    *_cruise(14.0, throttle=1.0),
    ScriptStep(2.0, brake=0.85),  # tighter stab-and-go cadence
    *_cruise(12.0, throttle=0.64),
    ScriptStep(2.0, brake=0.80),
    *_cruise(12.0, throttle=0.64),
    ScriptStep(2.0, brake=0.85),
    *_cruise(14.0, throttle=1.0),
    ScriptStep(2.5, brake=0.78),
    *_cruise(16.0, throttle=0.62),
    ScriptStep(3.0, brake=0.82),
]

HIGH_RISK_DRIVES: dict[str, list[ScriptStep]] = {
    "a": HIGH_RISK_DRIVE_A,
    "b": HIGH_RISK_DRIVE_B,
    "c": HIGH_RISK_DRIVE_C,
    "d": HIGH_RISK_DRIVE_D,
}


# --- Registry --------------------------------------------------------------

PROFILE_DRIVES: dict[str, dict[str, list[ScriptStep]]] = {
    "calm": CALM_DRIVES,
    "normal": NORMAL_DRIVES,
    "aggressive": AGGRESSIVE_DRIVES,
    "high_risk": HIGH_RISK_DRIVES,
}

DRIVES: dict[str, list[ScriptStep]] = {
    "demo": DEMO_DRIVE,
    **{name: variants["a"] for name, variants in PROFILE_DRIVES.items()},
}


def get_drive(name: str, variant: str = "a") -> list[ScriptStep]:
    """Look up a drive by profile name and variant letter.

    `demo` has no variants; every profile family has at least `a`.
    """
    if name == "demo":
        return DEMO_DRIVE
    try:
        return PROFILE_DRIVES[name][variant]
    except KeyError as exc:
        known = ", ".join(sorted([*PROFILE_DRIVES, "demo"]))
        raise KeyError(
            f"unknown drive {name!r} variant {variant!r} (known profiles: {known})"
        ) from exc


def variants_for(name: str) -> list[str]:
    """Variant letters available for a profile, in a stable order."""
    if name == "demo":
        return ["a"]
    return sorted(PROFILE_DRIVES[name])
