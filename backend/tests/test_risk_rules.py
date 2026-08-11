"""The rule layer, and the guard on the move that brought it here.

`ml/pipelines/labeling/rubric.py` produced the labels for all 1,135 training
windows. Moving its body into the backend must not change one of them, so the
parity test below re-labels the committed corpus through the new path and
compares against the labels stored in the parquet — the actual training
labels, not a re-derivation of them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.features.schema import FEATURE_NAMES, FEATURE_VERSION
from app.core.risk import rules
from app.core.risk.schema import RiskBand

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "ml" / "data" / "processed"
CORPUS_FILES = (
    f"features_sim_v{FEATURE_VERSION}.parquet",
    f"features_uah_v{FEATURE_VERSION}.parquet",
)

BASELINE: dict[str, float] = dict.fromkeys(FEATURE_NAMES, 0.0) | {
    "speed_mean": 50.0,
    "speed_cv": 0.10,
    "accel_std": 0.30,
    "accel_max": 0.90,
    "accel_min": -0.80,
    "lat_accel_std": 0.35,
    "lat_accel_max_abs": 1.00,
}


def window(**overrides: float) -> dict[str, float]:
    return {**BASELINE, **overrides}


def test_nothing_remarkable_is_normal_by_default() -> None:
    outcome = rules.evaluate(window())
    assert outcome.band is RiskBand.NORMAL
    # An empty tuple, not ("default",): no rule fired, so there is no reason
    # to show, and inventing one would make a default look like a finding.
    assert outcome.matched == ()
    assert outcome.first_match == rules.DEFAULT_RULE


@pytest.mark.parametrize(
    ("overrides", "expected_band", "expected_rule"),
    [
        (
            {"speeding_time_ratio": 0.6, "accel_min": -2.5},
            RiskBand.HIGH_RISK,
            "speeding_time_ratio>=0.5 and accel_min<=-2.0",
        ),
        ({"harsh_braking_per_min": 2.0}, RiskBand.AGGRESSIVE, "harsh_braking_per_min>=2.0"),
        ({"accel_max": 1.5}, RiskBand.AGGRESSIVE, "accel_max>=1.5"),
        ({"speeding_time_ratio": 0.5}, RiskBand.AGGRESSIVE, "speeding_time_ratio>=0.5"),
        ({"lat_accel_max_abs": 2.0}, RiskBand.AGGRESSIVE, "lat_accel_max_abs>=2.0"),
        ({"accel_std": 0.45}, RiskBand.AGGRESSIVE, "accel_std>=0.45"),
        (
            {"speed_cv": 0.02, "accel_std": 0.15, "lat_accel_std": 0.20},
            RiskBand.CALM,
            "steady_smooth_no_events",
        ),
    ],
)
def test_every_rule_id_is_reachable(
    overrides: dict[str, float], expected_band: RiskBand, expected_rule: str
) -> None:
    """Each cutoff fires at exactly its stated value, and names itself when it does."""
    outcome = rules.evaluate(window(**overrides))
    assert outcome.band is expected_band
    assert outcome.first_match == expected_rule


def test_rule_ids_constant_covers_every_reachable_rule() -> None:
    """`RULE_IDS` is documentation only if nothing checks it against the code."""
    reachable = {
        "speeding_time_ratio>=0.5 and accel_min<=-2.0": {
            "speeding_time_ratio": 0.6,
            "accel_min": -2.5,
        },
        "harsh_braking_per_min>=2.0": {"harsh_braking_per_min": 2.0},
        "accel_max>=1.5": {"accel_max": 1.5},
        "speeding_time_ratio>=0.5": {"speeding_time_ratio": 0.5},
        "lat_accel_max_abs>=2.0": {"lat_accel_max_abs": 2.0},
        "accel_std>=0.45": {"accel_std": 0.45},
        "steady_smooth_no_events": {
            "speed_cv": 0.02,
            "accel_std": 0.15,
            "lat_accel_std": 0.20,
        },
    }
    assert set(rules.RULE_IDS) == set(reachable)
    for rule_id, overrides in reachable.items():
        assert rule_id in rules.evaluate(window(**overrides)).matched


def test_high_risk_is_checked_before_aggressive() -> None:
    """Order is the design: the more severe class wins, not the coin flip."""
    outcome = rules.evaluate(
        window(speeding_time_ratio=0.6, accel_min=-2.5, harsh_braking_per_min=2.1, accel_max=1.6)
    )
    assert outcome.band is RiskBand.HIGH_RISK
    assert outcome.matched[0] == "speeding_time_ratio>=0.5 and accel_min<=-2.0"
    assert "harsh_braking_per_min>=2.0" in outcome.matched


def test_calm_and_aggressive_can_both_fire() -> None:
    """A single spike inside otherwise smooth driving. Both reasons survive."""
    outcome = rules.evaluate(
        window(speed_cv=0.02, accel_std=0.15, lat_accel_std=0.20, accel_max=1.6)
    )
    assert outcome.band is RiskBand.AGGRESSIVE
    assert outcome.matched == ("accel_max>=1.5", "steady_smooth_no_events")


def test_matched_is_ordered_most_severe_first() -> None:
    outcome = rules.evaluate(
        window(
            speeding_time_ratio=0.6,
            accel_min=-2.5,
            accel_max=1.6,
            accel_std=0.5,
            harsh_braking_per_min=2.1,
        )
    )
    assert outcome.matched[0].startswith("speeding_time_ratio>=0.5 and")
    assert len(outcome.matched) == 5


def test_first_match_agrees_with_the_labeller() -> None:
    """`evaluate` and `label_window_with_reason` read one list, so they must agree."""
    for overrides in (
        {},
        {"accel_max": 1.6},
        {"speeding_time_ratio": 0.6, "accel_min": -2.5},
        {"speed_cv": 0.02, "accel_std": 0.15, "lat_accel_std": 0.20},
    ):
        values = window(**overrides)
        outcome = rules.evaluate(values)
        label, reason = rules.label_window_with_reason(values)
        assert label == outcome.band.value
        assert reason == outcome.first_match


def test_shim_reexports_the_same_objects() -> None:
    """One implementation, two import paths — not two implementations."""
    pytest.importorskip("pandas")  # the ml package's own dependency chain
    from pipelines.labeling import rubric as shim

    assert shim.label_window_with_reason is rules.label_window_with_reason
    assert shim.RUBRIC_VERSION is rules.RUBRIC_VERSION
    assert shim.AGGRESSIVE_HARSH_BRAKING_PER_MIN == rules.AGGRESSIVE_HARSH_BRAKING_PER_MIN
    assert shim.HIGH_RISK_SPEEDING_ACCEL_MIN == rules.HIGH_RISK_SPEEDING_ACCEL_MIN


def _pre_move_rubric(values: dict[str, float]) -> tuple[str, str]:
    """The decision list exactly as it stood in `ml/pipelines/labeling/rubric.py`.

    A verbatim copy, frozen at the commit before the move, with the thresholds
    written out as literals rather than imported — importing them from
    `app.core.risk.rules` would make this compare the new code against itself
    and pass no matter what changed.

    This is the parity guard that runs everywhere. The corpus test below is
    stronger evidence when the corpus is present, but `ml/data/` is gitignored,
    so on a fresh checkout and in CI it skips; a proof that needs a file
    nobody has is not a proof.
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

    if speeding_time_ratio >= 0.5 and accel_min <= -2.0:
        return "HIGH_RISK", "speeding_time_ratio>=0.5 and accel_min<=-2.0"

    if harsh_braking_per_min >= 2.0:
        return "AGGRESSIVE", "harsh_braking_per_min>=2.0"
    if accel_max >= 1.5:
        return "AGGRESSIVE", "accel_max>=1.5"
    if speeding_time_ratio >= 0.5:
        return "AGGRESSIVE", "speeding_time_ratio>=0.5"
    if lat_accel_max_abs >= 2.0:
        return "AGGRESSIVE", "lat_accel_max_abs>=2.0"
    if accel_std >= 0.45:
        return "AGGRESSIVE", "accel_std>=0.45"

    if (
        harsh_braking_per_min == 0.0
        and rapid_accel_per_min == 0.0
        and speed_cv <= 0.03
        and accel_std <= 0.20
        and lat_accel_std <= 0.25
    ):
        return "CALM", "steady_smooth_no_events"

    return "NORMAL", "default"


# Values straddle every cutoff in the list, so the search spends its budget on
# the boundaries rather than on windows where nothing is close to firing.
_rule_inputs = st.fixed_dictionaries(
    {
        name: st.sampled_from([0.0, 0.019, 0.02, 0.2, 0.45, 0.5, 1.5, 2.0, 2.5, -2.0, -1.999])
        for name in (
            "harsh_braking_per_min",
            "rapid_accel_per_min",
            "speeding_time_ratio",
            "accel_min",
            "accel_max",
            "accel_std",
            "lat_accel_max_abs",
            "lat_accel_std",
            "speed_cv",
        )
    }
)


@given(_rule_inputs)
def test_matches_frozen_pre_move_rubric(values: dict[str, float]) -> None:
    """The moved rules are the same function, over the cutoffs that matter."""
    assert rules.label_window_with_reason({**BASELINE, **values}) == _pre_move_rubric(
        {**BASELINE, **values}
    )


@pytest.mark.parametrize("corpus", CORPUS_FILES)
def test_matches_pre_move_rubric(corpus: str) -> None:
    """Re-label the committed corpus and compare to the labels already in it.

    The parquet's `rubric_label` column was written by the rubric *before* the
    move. If this passes, no training label changed — which is the only claim
    that matters, because the corpus those labels came from is what M8's
    numbers were measured on.

    Skipped rather than failed when the corpus is absent: `ml/data/` is
    gitignored and a fresh checkout has to run `pipelines.featurise` first.
    """
    pandas = pytest.importorskip("pandas")
    path = PROCESSED_DIR / corpus
    if not path.is_file():
        pytest.skip(f"{path} not present — run `python -m pipelines.featurise` in ml/")

    frame = pandas.read_parquet(path)
    assert len(frame) > 0

    relabelled = [
        rules.label_window_with_reason(
            {name: float(row[name]) for name in FEATURE_NAMES}  # type: ignore[index]
        )[0]
        for _, row in frame.iterrows()
    ]
    stored = [str(value) for value in frame["rubric_label"]]
    mismatches = [
        (index, was, now)
        for index, (was, now) in enumerate(zip(stored, relabelled, strict=True))
        if was != now
    ]
    assert not mismatches, f"{len(mismatches)} of {len(stored)} labels changed: {mismatches[:5]}"
