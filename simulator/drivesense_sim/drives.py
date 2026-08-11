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

`app.core.events.detectors` debounces impulse events, so
`harsh_braking_per_min` counts brake *applications*, not the 10 Hz frames it
counted when these scripts were first written. Only the HIGH_RISK scripts
brake past -3.5 m/s^2 at all, and they do it repeatedly.

Speeding is measured against `DEFAULT_SPEED_LIMIT_KPH = 100.0` in
`ml/pipelines/featurise.py`, with the +5 kph margin from
`SPEEDING_MARGIN_KPH`, so "speeding" here means holding above ~105 kph.

## Calibrating against real driving (M8 domain-gap work)

These scripts were rewritten after the M8 evaluation found that a model
trained on the corpus they produced did not beat a majority-class baseline on
real UAH-DriveSet telemetry. Two of the causes were defects in *this file*,
not in the vehicle model — every constant in `vehicles/hatchback.json` was
checked against real-hatchback figures and found plausible:

1. **The drives were too slow.** 81% of simulator windows sat below UAH's 5th
   percentile speed. UAH is entirely motorway and secondary driving: its
   slowest window anywhere is 50.9 kph, its median 91.5. The old CALM and
   NORMAL scripts cruised at ~50 kph, so a model trained on them had never
   seen the speed band it was validated in. They now spend most of their time
   between 80 and 100 kph, with slower sections retained because real driving
   has both and the product has to handle both.

2. **The drives did not steer.** Four features (`lat_accel_std`,
   `lat_accel_max_abs`, `yaw_rate_std`, `heading_change_rate`) were *exactly*
   0.000 in 58% of simulator windows — CALM 88%, HIGH_RISK 84%, NORMAL 48% —
   and in 0% of UAH windows. A real road always bends. The old scripts put
   steering in short discrete `_sweeper` blocks separated by long dead-straight
   cruises, so any 30 s window that landed inside a cruise had no lateral
   content at all. `_winding` replaces those cruises: the road curves
   continuously and its curvature never passes through exactly zero.

A third defect surfaced while doing that work, and it was the more serious
one. The HIGH_RISK scripts had been authored against a rubric rule that no
longer exists — `harsh_braking_per_min >= 6.0`, dropped as structurally
unreachable in ADR 0006's post-debounce recalibration. The corpus on disk
still carried 101 HIGH_RISK labels because it had been generated *before*
that change and never regenerated; re-running the current rubric over the same
rows relabels every one of them AGGRESSIVE. So the scripts were satisfying a
deleted rule, and the surviving rule —

    speeding_time_ratio >= 0.5  AND  accel_min <= -2.0

— was being satisfied by essentially nothing: the drives braked so hard and so
often that speed collapsed and never returned above the limit. HIGH_RISK is
now authored against that rule directly. See the profile's own comment below.

Steering and throttle values below are calibrated against measured
steady-state behaviour of this vehicle, not guessed:

    6th gear, throttle 0.46 / 0.50 / 0.54 / 0.58  ->  80 / 90 / 100 / 108 kph
    4th gear, throttle 0.24 / 0.28 / 0.32         ->  45 /  68 /  83 kph
    lateral accel ~ 55 * steer at 90 kph, ~ 28 * steer at 60 kph

Note the speed-dependence in that last line: the same `steer` produces roughly
half the lateral load at 60 kph that it does at 90 (`steering_falloff_kph`
reduces authority with speed, but lateral acceleration rises with it faster),
so the slower blocks below pass a proportionally larger `steer` to hold a
comparable lateral load.
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


def _shift_up(steer: float = 0.0) -> ScriptStep:
    return ScriptStep(0.4, clutch=1.0, shift_up=True, steer=steer)


def _shift_down(steer: float = 0.0) -> ScriptStep:
    return ScriptStep(0.4, clutch=1.0, shift_down=True, steer=steer)


def _ease(
    seconds: float, *, brake: float = 0.0, throttle: float = 0.0, steer: float = 0.0
) -> ScriptStep:
    """A braking or coasting link between two blocks, still on a curve.

    These interstitial steps used to take the `steer=0.0` default, which
    quietly reintroduced the exactly-zero-lateral windows `_winding` exists to
    remove: a 30 s window landing on a brake-and-downshift sequence saw no
    steering at all, even though the blocks either side of it were curving.
    """
    return ScriptStep(seconds, brake=brake, throttle=throttle, steer=steer)


def _launch(
    to_gear: int, throttle: float, segment_s: float, *, steer: float = 0.0
) -> list[ScriptStep]:
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

    `steer` holds a constant gentle curve through the spin-up. Without it the
    first ~50 s of every drive — two to three feature windows — has exactly
    zero lateral acceleration, which is the artefact `_winding` was introduced
    to remove from the cruises.
    """
    steps = [ScriptStep(0.5, clutch=1.0, shift_up=True, steer=steer)]  # neutral -> 1st
    for _ in range(to_gear - 1):
        steps.append(ScriptStep(segment_s, throttle=throttle, steer=steer))
        steps.append(_shift_up(steer=steer))
    steps.append(ScriptStep(segment_s, throttle=throttle, steer=steer))
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


# Multipliers on a block's steering amplitude, one per segment, cycled. This is
# the shape of the road: it bends one way, straightens out a little, bends the
# other. No entry is zero, and that is the point — a window whose every sample
# has *exactly* 0.000 lateral acceleration does not occur in real telemetry
# (0 of 1,709 UAH windows) and occurred in 58% of the corpus these scripts used
# to produce. The largest adjacent step sets how much lateral variation a
# window straddling a transition sees, which is what `lat_accel_std` measures.
_ROAD_SHAPE: tuple[float, ...] = (1.0, 0.6, 0.85, 0.35, -0.5, -0.85, -0.45, -0.75, 0.4, 0.7)

# CALM has a lateral budget the others do not: the rubric's CALM rule requires
# lat_accel_std <= 0.25, so this shape keeps every adjacent step small (<= 0.7
# of amplitude) and changes direction rarely. It still never reaches zero.
_ROAD_SHAPE_GENTLE: tuple[float, ...] = (0.9, 0.6, 0.35, -0.35, -0.6, -0.9, -0.55, -0.3, 0.3, 0.65)


def _winding(
    seconds: float,
    throttle: float,
    steer: float,
    *,
    segment_s: float = 22.0,
    shape: tuple[float, ...] = _ROAD_SHAPE,
) -> list[ScriptStep]:
    """A cruise along a road that bends, held at one throttle.

    Replaces `_cruise` wherever a drive would otherwise travel in a dead
    straight line for longer than a feature window. `segment_s` is deliberately
    close to the 30 s window length: shorter and every window averages the
    curvature away, much longer and windows land wholly inside one curve and
    report zero lateral *variation*. Real driving does neither.
    """
    steps: list[ScriptStep] = []
    remaining = seconds
    index = 0
    while remaining > 1e-9:
        span = min(segment_s, remaining)
        steps.append(ScriptStep(span, throttle=throttle, steer=steer * shape[index % len(shape)]))
        remaining -= span
        index += 1
    return steps


# --- CALM ------------------------------------------------------------------
# Steady speed, smooth inputs, no braking inside the cruise. The rubric's CALM
# rule needs speed_cv <= 0.03, accel_std <= 0.20 and lat_accel_std <= 0.25 with
# no harsh-braking or rapid-acceleration events at all.
#
# Calm is now a *highway* drive, which is what "calm" mostly means in the
# validation corpus: 80-95 kph on a gently bending road, with one slower
# secondary-road section reached by a soft brake rather than a stop. The
# lateral amplitudes (0.009 highway, 0.020 slower) hold peak lateral load
# around 0.5 m/s^2 — real, but comfortably inside CALM's 0.25 std budget.

CALM_DRIVE_A: list[ScriptStep] = [
    ScriptStep(2.0),
    *_launch(to_gear=4, throttle=0.42, segment_s=6.0, steer=0.022),
    _shift_up(),
    ScriptStep(16.0, throttle=0.88, steer=0.020),
    _shift_up(),
    ScriptStep(26.0, throttle=0.86, steer=0.018),
    *_winding(140.0, throttle=0.52, steer=0.018, segment_s=30.0, shape=_ROAD_SHAPE_GENTLE),
    _ease(9.0, brake=0.13, steer=0.012),
    _shift_down(steer=0.016),
    _shift_down(steer=0.020),
    *_winding(66.0, throttle=0.27, steer=0.040, segment_s=33.0, shape=_ROAD_SHAPE_GENTLE),
    _ease(8.0, brake=0.13, steer=0.016),
]

CALM_DRIVE_B: list[ScriptStep] = [
    ScriptStep(2.0),
    *_launch(to_gear=4, throttle=0.40, segment_s=6.5, steer=0.024),
    _shift_up(),
    ScriptStep(18.0, throttle=0.86, steer=0.022),
    _shift_up(),
    ScriptStep(24.0, throttle=0.84, steer=0.018),
    *_winding(90.0, throttle=0.48, steer=0.020, segment_s=30.0, shape=_ROAD_SHAPE_GENTLE),
    *_winding(84.0, throttle=0.54, steer=0.016, segment_s=28.0, shape=_ROAD_SHAPE_GENTLE),
    _ease(9.0, brake=0.12, steer=0.012),
    _shift_down(steer=0.016),
    _shift_down(steer=0.022),
    *_winding(60.0, throttle=0.25, steer=0.044, segment_s=30.0, shape=_ROAD_SHAPE_GENTLE),
    _ease(8.0, brake=0.14, steer=0.018),
]

CALM_DRIVE_C: list[ScriptStep] = [
    ScriptStep(2.0),
    *_launch(to_gear=4, throttle=0.44, segment_s=6.0, steer=0.020),
    _shift_up(),
    ScriptStep(16.0, throttle=0.90, steer=0.020),
    _shift_up(),
    ScriptStep(28.0, throttle=0.88, steer=0.016),
    *_winding(150.0, throttle=0.55, steer=0.016, segment_s=30.0, shape=_ROAD_SHAPE_GENTLE),
    _ease(10.0, brake=0.13, steer=0.014),
    _shift_down(steer=0.018),
    _shift_down(steer=0.024),
    *_winding(64.0, throttle=0.29, steer=0.036, segment_s=32.0, shape=_ROAD_SHAPE_GENTLE),
    _ease(8.0, brake=0.13, steer=0.016),
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

# Normal driving is a *mix*: a highway leg and a secondary-road leg, joined by
# ordinary braking and gear changes, on a road that bends throughout. The
# launch stops at 4th and continues in the upper gears, where the gearbox
# cannot produce more than ~1.16 m/s^2 even at full throttle — that is what
# keeps `accel_max` under the AGGRESSIVE rule's 1.5 line while still reaching
# 90-100 kph. Cruise throttles stay at or below 0.54 (~100 kph) so sustained
# speeding past 105 never fires the AGGRESSIVE speeding rule either.

NORMAL_DRIVE_A: list[ScriptStep] = [
    ScriptStep(1.5),
    *_launch(to_gear=4, throttle=0.45, segment_s=6.5, steer=0.044),
    _shift_up(),
    ScriptStep(15.0, throttle=0.92, steer=0.040),
    _shift_up(),
    ScriptStep(24.0, throttle=0.90, steer=0.034),
    *_winding(96.0, throttle=0.54, steer=0.036, segment_s=20.0),
    _ease(7.0, brake=0.16, steer=0.024),
    *_winding(72.0, throttle=0.52, steer=0.032, segment_s=20.0),
    _ease(8.0, brake=0.18, steer=0.026),
    _shift_down(steer=0.032),
    _shift_down(steer=0.044),
    *_winding(42.0, throttle=0.26, steer=0.068, segment_s=18.0),
    _ease(6.0, throttle=0.05, steer=0.048),
    *_winding(30.0, throttle=0.28, steer=0.060, segment_s=18.0),
    _ease(8.0, brake=0.16, steer=0.032),
]

NORMAL_DRIVE_B: list[ScriptStep] = [
    ScriptStep(1.5),
    *_launch(to_gear=4, throttle=0.44, segment_s=7.0, steer=0.048),
    _shift_up(),
    ScriptStep(16.0, throttle=0.90, steer=0.042),
    _shift_up(),
    ScriptStep(22.0, throttle=0.88, steer=0.036),
    *_winding(62.0, throttle=0.50, steer=0.040, segment_s=17.0),
    *_winding(84.0, throttle=0.55, steer=0.034, segment_s=18.0),
    _ease(7.0, brake=0.17, steer=0.022),
    *_winding(60.0, throttle=0.52, steer=0.038, segment_s=17.0),
    _ease(8.0, brake=0.19, steer=0.028),
    _shift_down(steer=0.034),
    _shift_down(steer=0.046),
    *_winding(40.0, throttle=0.25, steer=0.072, segment_s=20.0),
    _ease(6.0, throttle=0.05, steer=0.052),
    *_winding(28.0, throttle=0.29, steer=0.060, segment_s=14.0),
    _ease(8.0, brake=0.16, steer=0.034),
]

NORMAL_DRIVE_C: list[ScriptStep] = [
    ScriptStep(1.5),
    *_launch(to_gear=4, throttle=0.46, segment_s=6.5, steer=0.042),
    _shift_up(),
    ScriptStep(18.0, throttle=0.94, steer=0.038),
    _shift_up(),
    ScriptStep(26.0, throttle=0.92, steer=0.032),
    *_winding(104.0, throttle=0.52, steer=0.038, segment_s=22.0),
    _ease(6.0, brake=0.15, steer=0.024),
    *_winding(76.0, throttle=0.56, steer=0.032, segment_s=21.0),
    _ease(8.0, brake=0.20, steer=0.026),
    _shift_down(steer=0.032),
    _shift_down(steer=0.042),
    *_winding(38.0, throttle=0.28, steer=0.064, segment_s=19.0),
    _ease(6.0, throttle=0.05, steer=0.050),
    *_winding(28.0, throttle=0.26, steer=0.068, segment_s=14.0),
    _ease(8.0, brake=0.16, steer=0.030),
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
    _ease(5.0, brake=0.22, steer=0.012),
    *_cruise(14.0, throttle=0.60, steer=0.014),
    *_sweeper(16.0, throttle=0.52, steer=0.11),
    _ease(5.0, brake=0.20, steer=0.012),
    *_cruise(16.0, throttle=0.62, steer=0.014),
    *_sweeper(18.0, throttle=0.54, steer=0.105),
    _ease(6.0, brake=0.22, steer=0.012),
    *_cruise(18.0, throttle=0.58, steer=0.014),
    _ease(7.0, brake=0.20, steer=0.012),
]

AGGRESSIVE_DRIVE_B: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=2, throttle=1.0, segment_s=4.5),
    _ease(5.0, brake=0.22, steer=0.012),
    *_launch(to_gear=2, throttle=1.0, segment_s=4.5),  # re-launch through the box
    *_sweeper(20.0, throttle=0.56, steer=0.095),
    _ease(5.5, brake=0.21, steer=0.012),
    *_cruise(16.0, throttle=0.62, steer=0.014),
    *_sweeper(18.0, throttle=0.50, steer=0.115),
    _ease(5.0, brake=0.22, steer=0.012),
    *_cruise(20.0, throttle=0.60, steer=0.014),
    *_sweeper(16.0, throttle=0.54, steer=0.10),
    _ease(7.0, brake=0.20, steer=0.012),
]

AGGRESSIVE_DRIVE_C: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=2, throttle=1.0, segment_s=5.0),
    *_cruise(12.0, throttle=0.64, steer=0.014),
    _ease(4.5, brake=0.22, steer=0.012),
    *_sweeper(22.0, throttle=0.55, steer=0.105),
    _ease(5.0, brake=0.20, steer=0.012),
    *_cruise(18.0, throttle=0.60, steer=0.014),
    *_sweeper(20.0, throttle=0.52, steer=0.11),
    _ease(5.5, brake=0.22, steer=0.012),
    *_cruise(16.0, throttle=0.58, steer=0.014),
    *_sweeper(16.0, throttle=0.53, steer=0.10),
    _ease(7.0, brake=0.21, steer=0.012),
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
# **These were rebuilt against the rubric's surviving HIGH_RISK rule.** The
# earlier versions were authored when a standalone `harsh_braking_per_min`
# rule existed; that rule was dropped as structurally unreachable (ADR 0006,
# "Recalibrating harsh_braking_per_min after debouncing"), leaving exactly one
# route to HIGH_RISK:
#
#     speeding_time_ratio >= 0.5  AND  accel_min <= -2.0
#
# i.e. *more than half the window spent above ~105 kph, and a hard
# deceleration inside it*. The old scripts satisfied the second half easily
# and the first half almost never: they braked so hard, so often, that speed
# collapsed and never recovered — one measured drive spent 10% of its samples
# above 105 kph and its windows fell through to AGGRESSIVE.
#
# The cadence is therefore inverted. Speeding is now the *sustained* state —
# a held 115-125 kph cruise, well past the limit — and the hard braking is a
# short stab that dips speed without destroying it, followed by an immediate
# return to speed. That is also the more honest picture of the behaviour being
# modelled: habitual speeding punctuated by late, hard braking, rather than a
# car that is mostly stopped.

HIGH_RISK_DRIVE_A: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=5, throttle=1.0, segment_s=3.5, steer=0.012),
    ScriptStep(16.0, throttle=1.0, steer=0.012),  # straight past the limit
    *_winding(26.0, throttle=0.62, steer=0.014, segment_s=13.0),  # ~135, held
    _ease(1.0, brake=0.80, steer=0.010),  # late and hard, but brief
    ScriptStep(9.0, throttle=1.0, steer=0.012),  # straight back to speed
    *_winding(24.0, throttle=0.62, steer=0.015, segment_s=12.0),
    _ease(1.0, brake=0.78, steer=0.010),
    ScriptStep(9.0, throttle=1.0, steer=0.012),
    *_winding(24.0, throttle=0.60, steer=0.014, segment_s=12.0),
    _ease(1.1, brake=0.85, steer=0.011),
    ScriptStep(10.0, throttle=1.0, steer=0.013),
    *_winding(24.0, throttle=0.62, steer=0.016, segment_s=12.0),
    _ease(1.0, brake=0.80, steer=0.010),
    ScriptStep(9.0, throttle=1.0, steer=0.012),
    *_winding(22.0, throttle=0.60, steer=0.015, segment_s=11.0),
    _ease(4.0, brake=0.55, steer=0.010),
]

HIGH_RISK_DRIVE_B: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=5, throttle=1.0, segment_s=3.0, steer=0.013),
    ScriptStep(18.0, throttle=1.0, steer=0.012),
    *_winding(24.0, throttle=0.62, steer=0.015, segment_s=12.0),
    _ease(1.0, brake=0.85, steer=0.011),
    ScriptStep(9.0, throttle=1.0, steer=0.012),
    *_sweeper(16.0, throttle=0.64, steer=0.030),  # fast, and turning hard
    _ease(1.0, brake=0.80, steer=0.011),
    ScriptStep(10.0, throttle=1.0, steer=0.012),
    *_winding(24.0, throttle=0.62, steer=0.016, segment_s=12.0),
    _ease(1.1, brake=0.78, steer=0.010),
    ScriptStep(9.0, throttle=1.0, steer=0.013),
    *_winding(22.0, throttle=0.60, steer=0.015, segment_s=11.0),
    _ease(1.0, brake=0.82, steer=0.011),
    ScriptStep(9.0, throttle=1.0, steer=0.012),
    *_sweeper(18.0, throttle=0.62, steer=0.028),
    _ease(4.0, brake=0.55, steer=0.010),
]

HIGH_RISK_DRIVE_C: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=5, throttle=1.0, segment_s=3.0, steer=0.011),
    ScriptStep(20.0, throttle=1.0, steer=0.011),
    *_winding(34.0, throttle=0.62, steer=0.013, segment_s=17.0),  # long speeding block
    _ease(1.1, brake=0.80, steer=0.010),
    ScriptStep(10.0, throttle=1.0, steer=0.011),
    *_winding(32.0, throttle=0.64, steer=0.014, segment_s=16.0),
    _ease(1.0, brake=0.85, steer=0.010),
    ScriptStep(10.0, throttle=1.0, steer=0.012),
    *_winding(30.0, throttle=0.62, steer=0.013, segment_s=15.0),
    _ease(1.1, brake=0.78, steer=0.011),
    ScriptStep(9.0, throttle=1.0, steer=0.011),
    *_winding(26.0, throttle=0.60, steer=0.014, segment_s=13.0),
    _ease(4.0, brake=0.55, steer=0.010),
]

HIGH_RISK_DRIVE_D: list[ScriptStep] = [
    ScriptStep(1.0),
    *_launch(to_gear=5, throttle=1.0, segment_s=3.5, steer=0.013),
    ScriptStep(16.0, throttle=1.0, steer=0.012),
    *_winding(20.0, throttle=0.62, steer=0.015, segment_s=10.0),
    _ease(0.9, brake=0.85, steer=0.011),  # tighter stab-and-go cadence
    ScriptStep(8.0, throttle=1.0, steer=0.012),
    *_winding(18.0, throttle=0.62, steer=0.017, segment_s=9.0),
    _ease(0.9, brake=0.80, steer=0.011),
    ScriptStep(8.0, throttle=1.0, steer=0.012),
    *_winding(18.0, throttle=0.60, steer=0.016, segment_s=9.0),
    _ease(0.9, brake=0.85, steer=0.011),
    ScriptStep(8.0, throttle=1.0, steer=0.013),
    *_winding(20.0, throttle=0.62, steer=0.015, segment_s=10.0),
    _ease(1.0, brake=0.78, steer=0.010),
    ScriptStep(8.0, throttle=1.0, steer=0.012),
    *_winding(20.0, throttle=0.60, steer=0.017, segment_s=10.0),
    _ease(0.9, brake=0.82, steer=0.011),
    ScriptStep(8.0, throttle=1.0, steer=0.012),
    *_winding(20.0, throttle=0.62, steer=0.016, segment_s=10.0),
    _ease(4.0, brake=0.55, steer=0.010),
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
