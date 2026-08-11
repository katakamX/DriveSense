"""The training-label rubric — moved to `app.core.risk.rules`, re-exported here.

The rules themselves, their calibration comments and their ADR-0006 history now
live in the backend, at `backend/app/core/risk/rules.py`. Nothing about them
changed in the move; only their address did.

**Why they moved.** From Milestone 9 the same decision list has two consumers:
this pipeline, which reads it once per window offline to produce
`rubric_label`, and the live risk engine, which reads it once per second to
gate the model's top band (docs/adr/0007-risk-engine-rule-gating.md). Two
copies of a decision list are two decision lists, and the one that drifts is
whichever one nobody is looking at. The direction of the move is forced:
`ml/` already depends on `drivesense-backend` — that is how ADR 0004 arranged
feature extraction, and how `pipelines.artifact` already imports the decision
rule back from `app.ml.artifact` — while the backend depends on nothing in
`ml/` and must not start.

**This module is not deprecated.** `pipelines.featurise` importing
`pipelines.labeling.rubric` is the right expression of intent for a labelling
stage; it should not have to know that the rules are shared infrastructure.
The shim is the seam, not a migration step.

`ml/tests/test_rubric.py` continues to test through this import path, so the
re-export is exercised rather than assumed, and
`backend/tests/test_risk_rules.py::test_shim_reexports_the_same_objects`
asserts the two paths reach one implementation rather than two.
"""

from app.core.risk.rules import (
    AGGRESSIVE_ACCEL_MAX,
    AGGRESSIVE_ACCEL_STD,
    AGGRESSIVE_HARSH_BRAKING_PER_MIN,
    AGGRESSIVE_LAT_ACCEL_MAX_ABS,
    AGGRESSIVE_SPEEDING_TIME_RATIO,
    CALM_ACCEL_STD,
    CALM_LAT_ACCEL_STD,
    CALM_SPEED_CV,
    HIGH_RISK_SPEEDING_ACCEL_MIN,
    HIGH_RISK_SPEEDING_TIME_RATIO,
    RUBRIC_VERSION,
    Label,
    label_window_with_reason,
)

__all__ = [
    "AGGRESSIVE_ACCEL_MAX",
    "AGGRESSIVE_ACCEL_STD",
    "AGGRESSIVE_HARSH_BRAKING_PER_MIN",
    "AGGRESSIVE_LAT_ACCEL_MAX_ABS",
    "AGGRESSIVE_SPEEDING_TIME_RATIO",
    "CALM_ACCEL_STD",
    "CALM_LAT_ACCEL_STD",
    "CALM_SPEED_CV",
    "HIGH_RISK_SPEEDING_ACCEL_MIN",
    "HIGH_RISK_SPEEDING_TIME_RATIO",
    "RUBRIC_VERSION",
    "Label",
    "label_window_with_reason",
]
