"""Golden fixtures: the engine's output for a fixed set of inputs, pinned.

Regenerate with `python -m tests.fixtures.risk.regenerate` from `backend/`,
but read the diff first — see that module's docstring for why regenerating is
never on its own the fix for a failure here.

Tolerances are asymmetric on purpose. Bands, provenance, rule IDs and flags
are compared exactly, because there is no such thing as almost-HIGH_RISK.
Scores and confidences get 1e-9, which is float noise and nothing else: a
golden that tolerates a change big enough to see is not pinning anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.risk import assess, summarise
from app.core.risk.rules import RULE_IDS
from app.core.risk.schema import RiskAssessment
from app.ml.artifact import MODEL_FORMAT, MODEL_FORMAT_VERSION, read_model_json
from tests.fixtures.risk.regenerate import (
    BASELINE,
    TOY_MODEL_PATH,
    WINDOW_END,
    WINDOW_START,
    load_toy_model,
    model_output,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "risk"
EXACT = 1e-9


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


WINDOWS = _load("golden_windows.json")
TRIP = _load("golden_trip.json")


# --- the fixture artefact itself --------------------------------------------


def test_toy_model_is_a_valid_artefact() -> None:
    """The committed stand-in must parse as a real one, or the goldens rot silently.

    `ml/artifacts/` is gitignored, so without this file the entire model path
    of the risk engine would be untested anywhere the training pipeline has
    not been run — which includes CI and every fresh checkout.
    """
    payload = read_model_json(TOY_MODEL_PATH)
    assert payload["format"] == MODEL_FORMAT
    assert payload["format_version"] == MODEL_FORMAT_VERSION
    assert sorted(payload["classes"]) == ["AGGRESSIVE", "CALM", "HIGH_RISK", "NORMAL"]
    assert len(payload["coefficients"]) == len(payload["classes"])
    for row in payload["coefficients"]:
        assert len(row) == len(payload["feature_names"])
    assert all(name in BASELINE for name in payload["feature_names"])


# --- the window goldens ------------------------------------------------------


def _replay(case: dict[str, Any]) -> RiskAssessment:
    features = {**BASELINE, **case["features"]}
    output = model_output(load_toy_model(), features) if case["use_model"] else None
    return assess(
        features=features,
        model_output=output,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        sample_count=case["sample_count"],
        coverage_ratio=case["coverage_ratio"],
        model_version=WINDOWS["model_version"] if case["use_model"] else None,
        top_k=case["top_k"],
    )


@pytest.mark.parametrize("case", WINDOWS["cases"], ids=lambda case: str(case["name"]))
def test_golden_window(case: dict[str, Any]) -> None:
    actual = _replay(case)
    expected = case["expected"]

    # Exact: a band or a provenance is either right or wrong.
    assert actual.band.value == expected["band"]
    assert actual.rule_band.value == expected["rule_band"]
    assert actual.provenance.value == expected["provenance"]
    assert actual.gated is expected["gated"]
    assert actual.model_available is expected["model_available"]
    assert list(actual.matched_rules) == expected["matched_rules"]
    assert actual.model_predicted_class == expected["model_predicted_class"]
    assert (actual.model_band.value if actual.model_band else None) == expected["model_band"]
    assert actual.sample_count == expected["sample_count"]
    assert actual.risk_engine_version == expected["risk_engine_version"]
    assert actual.feature_version == expected["feature_version"]
    assert actual.rubric_version == expected["rubric_version"]
    assert actual.model_version == expected["model_version"]

    # Float noise only.
    assert actual.score == pytest.approx(expected["score"], abs=EXACT)
    assert actual.confidence == pytest.approx(expected["confidence"], abs=EXACT)
    assert actual.coverage_ratio == pytest.approx(expected["coverage_ratio"], abs=EXACT)
    assert actual.contributions_remainder == pytest.approx(
        expected["contributions_remainder"], abs=EXACT
    )
    if expected["model_score"] is None:
        assert actual.model_score is None
    else:
        assert actual.model_score == pytest.approx(expected["model_score"], abs=EXACT)

    assert len(actual.contributions) == len(expected["contributions"])
    for got, want in zip(actual.contributions, expected["contributions"], strict=True):
        assert got.feature == want["feature"]
        assert got.value == pytest.approx(want["value"], abs=EXACT)
        assert got.contribution == pytest.approx(want["contribution"], abs=EXACT)


def test_the_golden_set_covers_every_rule_and_every_provenance() -> None:
    """A fixture set is only a safety net over what it actually reaches."""
    seen_rules = {rule for case in WINDOWS["cases"] for rule in case["expected"]["matched_rules"]}
    assert seen_rules == set(RULE_IDS)

    assert {case["expected"]["band"] for case in WINDOWS["cases"]} == {
        "CALM",
        "NORMAL",
        "AGGRESSIVE",
        "HIGH_RISK",
    }
    assert {case["expected"]["provenance"] for case in WINDOWS["cases"]} == {
        "RULES_ONLY",
        "MODEL_AND_RULES_AGREE",
        "MODEL_ONLY",
    }
    assert {case["expected"]["gated"] for case in WINDOWS["cases"]} == {True, False}
    assert {case["expected"]["model_available"] for case in WINDOWS["cases"]} == {True, False}


def test_case_names_are_unique() -> None:
    names = [case["name"] for case in WINDOWS["cases"]]
    assert len(names) == len(set(names))


# --- the trip golden ---------------------------------------------------------


def test_golden_trip_summary() -> None:
    payload = load_toy_model()
    assessments = []
    for index, step in enumerate(TRIP["steps"]):
        features = {**BASELINE, **step["features"]}
        output = model_output(payload, features) if step["use_model"] else None
        assessments.append(
            assess(
                features=features,
                model_output=output,
                window_start=WINDOW_START.replace(second=index),
                window_end=WINDOW_END.replace(second=index),
                sample_count=int(300 * step["coverage_ratio"]),
                coverage_ratio=step["coverage_ratio"],
                model_version="toyfixture01" if step["use_model"] else None,
            )
        )

    summary = summarise(assessments)
    expected = TRIP["expected_summary"]

    assert summary.window_count == expected["window_count"]
    assert summary.trip_band is not None
    assert summary.trip_band.value == expected["trip_band"]
    assert summary.risk_engine_version == expected["risk_engine_version"]
    assert {band.value: count for band, count in summary.band_counts.items()} == expected[
        "band_counts"
    ]
    assert summary.trip_score == pytest.approx(expected["trip_score"], abs=EXACT)
    assert summary.mean_score == pytest.approx(expected["mean_score"], abs=EXACT)
    assert summary.max_score == pytest.approx(expected["max_score"], abs=EXACT)
    assert summary.high_risk_window_ratio == pytest.approx(
        expected["high_risk_window_ratio"], abs=EXACT
    )
    assert summary.gated_window_ratio == pytest.approx(expected["gated_window_ratio"], abs=EXACT)
    assert summary.model_window_ratio == pytest.approx(expected["model_window_ratio"], abs=EXACT)


def test_the_golden_trip_visits_every_band() -> None:
    assert all(count > 0 for count in TRIP["expected_summary"]["band_counts"].values())
