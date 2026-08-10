"""The training-label rubric: a deterministic decision list over the 26
shared features (see `app.core.features.FEATURE_NAMES`).

This is weak supervision, not ground truth (docs/architecture.md, "Honest ML
methodology") — every rule is named so a label always reduces to one
answerable "why": `label_window_with_reason` returns the rule that fired
alongside the label, not just the label.

Rule order is significant and is the whole design: HIGH_RISK is checked
first (a window matching both a HIGH_RISK and an AGGRESSIVE rule is the more
severe class, not a coin flip), then AGGRESSIVE, then CALM; anything left is
NORMAL by default, not by a positive rule — NORMAL is "nothing remarkable
happened," which is exactly what makes it a default rather than a threshold.

Thresholds were first anchored to the two places that already define "an
event" in this codebase (`app.core.events.thresholds`:
HARSH_BRAKING_ACCEL_MS2 = -3.5, RAPID_ACCELERATION_ACCEL_MS2 = 3.0,
SPEEDING_MARGIN_KPH = 5.0; `app.core.features.extract`: 0.5 m/s^2 "any
acceleration/braking", 2.5 m/s^2 "any lateral load"), then recalibrated
against the empirical distribution of the 1,709 UAH-DriveSet validation
windows (see docs/adr/0006-training-label-rubric.md, "UAH-calibrated
thresholds"). Some of the original anchor-derived cutoffs were never reached
by real driving at all (`rapid_accel_per_min` is 0.0 at every UAH window's
max; `accel_std >= 1.5` exceeded the global UAH max of 1.311) and have been
replaced with a feature that measures the same underlying behaviour but
actually varies in real data. Each rule's comment states which anchor it
still traces to, or which empirical percentile replaced it.
"""

from __future__ import annotations

from typing import Literal

RUBRIC_VERSION = "1"

Label = Literal["CALM", "NORMAL", "AGGRESSIVE", "HIGH_RISK"]

# --- HIGH_RISK --------------------------------------------------------------

# harsh_braking_per_min is quantized at ~2.008/event (one event in a 30s
# window). >=6.0 means "3 or more harsh brakes (<= -3.5 m/s^2,
# HARSH_BRAKING_ACCEL_MS2) in one window" — a driving *style*, not an
# occasional hard stop. >=4.0 (2 events) left no headroom for the
# AGGRESSIVE >=2.0 (1 event) rule below it; UAH: 14 windows, 0 on `normal`.
HIGH_RISK_HARSH_BRAKING_PER_MIN = 6.0

# Sustained speeding (> speed_limit + 5 kph, SPEEDING_MARGIN_KPH, for at
# least half the window) combined with hard deceleration is "too fast,
# reacting late". The second condition was originally
# harsh_braking_per_min >= 2.0 — the same 1-event quantum the AGGRESSIVE
# rule below already consumes, so the compound rarely had anything left to
# catch. accel_min is continuous and measures the same physics below the
# -3.5 event line without double-counting that quantum; -2.0 sits at the
# aggressive-labelled UAH windows' ~p12 and is never reached by a
# normal-labelled window. UAH: 12 windows.
HIGH_RISK_SPEEDING_TIME_RATIO = 0.5
HIGH_RISK_SPEEDING_ACCEL_MIN = -2.0

# A standalone "accel_min <= -X" rule was dropped entirely: accel_min <=
# -3.5 is definitionally the same event harsh_braking_per_min counts, so any
# cutoff at or below that line is either redundant with the harsh-braking
# rule above (if checked after it) or steals its population (if checked
# before it) depending on evaluation order — not fixable by moving the
# number. Tested -5.0/-4.5/-4.0/-3.5 against UAH: every variant classified
# zero windows once the rules above it were in place.

# --- AGGRESSIVE ---------------------------------------------------------

# Unchanged: now means "1-2 harsh brakes" (live only because HIGH_RISK moved
# to 6.0/3 events). UAH: 4 windows.
AGGRESSIVE_HARSH_BRAKING_PER_MIN = 2.0

# Was rapid_accel_per_min >= 2.0 — that feature is 0.0 at its max across all
# 1,709 UAH windows (RAPID_ACCELERATION_ACCEL_MS2 = 3.0 m/s^2 is never
# reached by any real recording here), so no cutoff on it can ever fire.
# accel_max measures the same "how hard did the driver accelerate" question
# without the RAPID_ACCELERATION event's all-or-nothing threshold; 1.5 sits
# at the aggressive-labelled p95 (1.549) and normal-labelled p99 (1.580).
# UAH: 37 windows.
AGGRESSIVE_ACCEL_MAX = 1.5

# 0.3 caught 91 normal-labelled UAH windows. 0.5 keeps meaningful
# aggressive-recall (34.7% of aggressive-labelled windows) while cutting
# normal-labelled hits to 53, and gives the HIGH_RISK compound rule a
# shared meaning: sustained speeding alone is AGGRESSIVE; sustained
# speeding plus hard deceleration is HIGH_RISK.
AGGRESSIVE_SPEEDING_TIME_RATIO = 0.5

# Was 4.0, which only ever fired twice in UAH — and both hits were
# normal-labelled (a sensor spike, not cornering). 2.0 sits at the
# aggressive-labelled p90 (2.025) and around the normal-labelled p97,
# clearly above the existing 2.5 m/s^2 "any lateral load" threshold's *time*
# variant (lat_accel_time_ratio) would suggest for a *peak*. UAH: 71
# windows.
AGGRESSIVE_LAT_ACCEL_MAX_ABS = 2.0

# Was 1.5, which exceeded the global UAH max (1.311) — unreachable by
# construction. 0.45 sits at the aggressive-labelled p75 (0.445) and above
# the normal-labelled p95 (0.364). UAH: 49 windows.
AGGRESSIVE_ACCEL_STD = 0.45

# --- CALM -----------------------------------------------------------------

# All three cutoffs were originally at or above the p90 of every UAH label
# (0.15 / 0.4 / 0.5), so each condition alone admitted ~90-95% of windows
# regardless of label — "distinctly below baseline" requires values between
# the normal-labelled p25 and p50, not near its p90. At these values the
# three-way conjunction captures 0% of aggressive-labelled UAH windows
# (down from 61% at the old cutoffs) while still admitting normal (19.3%)
# and drowsy (11.1%) windows.
CALM_SPEED_CV = 0.03
CALM_ACCEL_STD = 0.20
CALM_LAT_ACCEL_STD = 0.25


def label_window_with_reason(values: dict[str, float]) -> tuple[Label, str]:
    """Classify one window's feature dict, returning (label, matched_rule).

    `values` is a `FeatureVector.as_dict()`-shaped mapping: keyed by
    `app.core.features.FEATURE_NAMES`, one float per feature. This function
    is pure and does no I/O — the caller (a featurise pipeline stage) is
    responsible for building `values` and persisting the result.
    """
    harsh_braking_per_min = values["harsh_braking_per_min"]
    rapid_accel_per_min = values["rapid_accel_per_min"]
    speeding_time_ratio = values["speeding_time_ratio"]
    accel_min = values["accel_min"]
    accel_max = values["accel_max"]
    accel_std = values["accel_std"]
    lat_accel_max_abs = values["lat_accel_max_abs"]
    lat_accel_std = values["lat_accel_std"]
    speed_cv = values["speed_cv"]

    if harsh_braking_per_min >= HIGH_RISK_HARSH_BRAKING_PER_MIN:
        return "HIGH_RISK", "harsh_braking_per_min>=6.0"
    if (
        speeding_time_ratio >= HIGH_RISK_SPEEDING_TIME_RATIO
        and accel_min <= HIGH_RISK_SPEEDING_ACCEL_MIN
    ):
        return "HIGH_RISK", "speeding_time_ratio>=0.5 and accel_min<=-2.0"

    if harsh_braking_per_min >= AGGRESSIVE_HARSH_BRAKING_PER_MIN:
        return "AGGRESSIVE", "harsh_braking_per_min>=2.0"
    if accel_max >= AGGRESSIVE_ACCEL_MAX:
        return "AGGRESSIVE", "accel_max>=1.5"
    if speeding_time_ratio >= AGGRESSIVE_SPEEDING_TIME_RATIO:
        return "AGGRESSIVE", "speeding_time_ratio>=0.5"
    if lat_accel_max_abs >= AGGRESSIVE_LAT_ACCEL_MAX_ABS:
        return "AGGRESSIVE", "lat_accel_max_abs>=2.0"
    if accel_std >= AGGRESSIVE_ACCEL_STD:
        return "AGGRESSIVE", "accel_std>=0.45"

    if (
        harsh_braking_per_min == 0.0
        and rapid_accel_per_min == 0.0
        and speed_cv <= CALM_SPEED_CV
        and accel_std <= CALM_ACCEL_STD
        and lat_accel_std <= CALM_LAT_ACCEL_STD
    ):
        return "CALM", "steady_smooth_no_events"

    return "NORMAL", "default"
