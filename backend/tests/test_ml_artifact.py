"""Tests for the artefact reader: the decision rule and the explanation math.

Two kinds of test here, doing different jobs.

`test_golden_*` pins the arithmetic against a checked-in artefact
(`tests/fixtures/model.json`) whose numbers were chosen so the expected
results can be written out by hand. If someone "optimises" `predict_proba`
into something subtly different, these fail with a number, not a shrug.

`test_contributions_*` is the property test, and it is the actual correctness
proof for the explainability path. Explanations are the part of a model users
believe without being able to check, so the invariant that makes them
meaningful — the contributions plus the centered intercept reconstruct the
centered logit exactly — is asserted over randomly generated artefacts rather
than over one convenient example.
"""

import json
import math
import random
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.ml.artifact import (
    MODEL_FORMAT,
    centered_intercepts,
    centered_logits,
    feature_contributions,
    predict,
    predict_proba,
    read_model_json,
    scores,
    standardise,
)

FIXTURE_MODEL = Path(__file__).parent / "fixtures" / "model.json"

# The fixture's numbers are chosen so this row standardises to exactly
# z = (2.0, 2.0, 1.0) and the scores come out whole.
GOLDEN_ROW = np.array([[70.0, 2.0, 6.0]])
GOLDEN_Z = [2.0, 2.0, 1.0]
GOLDEN_SCORES = [-6.0, 3.0, 5.25]  # SAFE, AGGRESSIVE, HIGH_RISK


@pytest.fixture
def payload() -> dict[str, Any]:
    return read_model_json(FIXTURE_MODEL)


# --- Golden: the decision rule ----------------------------------------------


def test_golden_standardisation(payload: dict[str, Any]) -> None:
    assert standardise(payload, GOLDEN_ROW).tolist() == [GOLDEN_Z]


def test_golden_scores(payload: dict[str, Any]) -> None:
    assert scores(payload, GOLDEN_ROW)[0].tolist() == pytest.approx(GOLDEN_SCORES)


def test_golden_probabilities(payload: dict[str, Any]) -> None:
    # Computed here with plain `math.exp`, not with the module under test.
    total = sum(math.exp(s) for s in GOLDEN_SCORES)
    expected = [math.exp(s) / total for s in GOLDEN_SCORES]

    assert predict_proba(payload, GOLDEN_ROW)[0].tolist() == pytest.approx(expected)


def test_golden_prediction(payload: dict[str, Any]) -> None:
    assert predict(payload, GOLDEN_ROW) == ["HIGH_RISK"]


def test_probabilities_sum_to_one(payload: dict[str, Any]) -> None:
    rows = np.array([[0.0, 0.0, 0.0], [120.0, 4.0, 30.0], [-40.0, -2.0, -9.0]])

    assert predict_proba(payload, rows).sum(axis=1).tolist() == pytest.approx([1.0, 1.0, 1.0])


def test_extreme_scores_do_not_overflow(payload: dict[str, Any]) -> None:
    # Without the max-shift in the softmax this overflows to nan.
    proba = predict_proba(payload, np.array([[1e6, 1e6, 1e6]]))

    assert not np.isnan(proba).any()
    assert proba.sum() == pytest.approx(1.0)


def test_wrong_feature_count_is_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="artefact expects 3"):
        predict_proba(payload, np.array([[1.0, 2.0]]))


# --- Golden: the reader's guardrails -----------------------------------------


def test_reader_rejects_a_foreign_artifact(tmp_path: Path) -> None:
    path = tmp_path / "model.json"
    path.write_text(json.dumps({"format": "sklearn-pickle", "format_version": "1"}))

    with pytest.raises(ValueError, match="expected format"):
        read_model_json(path)


def test_reader_rejects_an_unknown_format_version(tmp_path: Path) -> None:
    path = tmp_path / "model.json"
    path.write_text(json.dumps({"format": MODEL_FORMAT, "format_version": "99"}))

    with pytest.raises(ValueError, match="format version"):
        read_model_json(path)


# --- Golden: contributions ---------------------------------------------------


def test_golden_contributions(payload: dict[str, Any]) -> None:
    # Per-feature across-class coefficient means: (-1 + 0.25 + 0.75)/3 = 0,
    # (-2 + 1 + 1)/3 = 0, (-0.5 + 0.5 + 2)/3 = 2/3. So only jerk_std's
    # contributions are shifted by centering, and by exactly 2/3 * z = 2/3.
    contributions = feature_contributions(payload, GOLDEN_ROW)[0]

    safe, aggressive, high_risk = contributions.tolist()
    assert safe == pytest.approx([-2.0, -4.0, -0.5 - 2 / 3])
    assert aggressive == pytest.approx([0.5, 2.0, 0.5 - 2 / 3])
    assert high_risk == pytest.approx([1.5, 2.0, 2.0 - 2 / 3])


def test_golden_centered_intercepts(payload: dict[str, Any]) -> None:
    mean_intercept = (0.5 + 0.0 - 0.25) / 3

    assert centered_intercepts(payload).tolist() == pytest.approx(
        [0.5 - mean_intercept, 0.0 - mean_intercept, -0.25 - mean_intercept]
    )


def test_a_feature_that_moves_every_class_equally_contributes_nothing() -> None:
    # The reason for centering, as a test: a feature whose coefficient is the
    # same for all three classes cannot change which class wins, so its
    # contribution must be zero rather than large-and-misleading.
    payload = {
        "classes": ["SAFE", "AGGRESSIVE", "HIGH_RISK"],
        "feature_names": ["shared", "discriminating"],
        "standardiser": {"mean": [0.0, 0.0], "scale": [1.0, 1.0]},
        "coefficients": [[3.0, -1.0], [3.0, 0.0], [3.0, 1.0]],
        "intercepts": [0.0, 0.0, 0.0],
    }

    contributions = feature_contributions(payload, np.array([[5.0, 2.0]]))[0]

    assert contributions[:, 0].tolist() == pytest.approx([0.0, 0.0, 0.0])
    assert contributions[:, 1].tolist() == pytest.approx([-2.0, 0.0, 2.0])


# --- The property: contributions reconstruct the centered logit --------------


def _random_payload(rng: random.Random) -> dict[str, Any]:
    n_classes = rng.randint(2, 5)
    n_features = rng.randint(1, 8)
    return {
        "classes": [f"class_{i}" for i in range(n_classes)],
        "feature_names": [f"feature_{i}" for i in range(n_features)],
        "standardiser": {
            "mean": [rng.uniform(-100.0, 100.0) for _ in range(n_features)],
            # Never near zero: a degenerate feature is excluded at training
            # time, so an artefact never carries a zero scale.
            "scale": [rng.uniform(0.05, 50.0) for _ in range(n_features)],
        },
        "coefficients": [
            [rng.uniform(-5.0, 5.0) for _ in range(n_features)] for _ in range(n_classes)
        ],
        "intercepts": [rng.uniform(-3.0, 3.0) for _ in range(n_classes)],
    }


def _random_rows(rng: random.Random, n_features: int, n_rows: int = 4) -> np.ndarray:
    return np.array(
        [[rng.uniform(-500.0, 500.0) for _ in range(n_features)] for _ in range(n_rows)]
    )


def test_contributions_and_centered_intercept_sum_to_the_centered_logit() -> None:
    rng = random.Random(20260811)

    for _ in range(200):
        payload = _random_payload(rng)
        rows = _random_rows(rng, len(payload["feature_names"]))

        reconstructed = feature_contributions(payload, rows).sum(axis=2) + centered_intercepts(
            payload
        )

        assert np.allclose(reconstructed, centered_logits(payload, rows), rtol=1e-9, atol=1e-9)


def test_centered_logits_are_the_scores_with_the_class_mean_removed() -> None:
    rng = random.Random(11)

    for _ in range(50):
        payload = _random_payload(rng)
        rows = _random_rows(rng, len(payload["feature_names"]))
        raw = scores(payload, rows)

        assert np.allclose(centered_logits(payload, rows), raw - raw.mean(axis=1, keepdims=True))


def test_centering_does_not_change_the_probabilities() -> None:
    # Why centering is safe at all: softmax is invariant to a per-row constant
    # shift, so the explanation and the prediction describe the same model.
    rng = random.Random(3)

    for _ in range(50):
        payload = _random_payload(rng)
        rows = _random_rows(rng, len(payload["feature_names"]))
        centered = centered_logits(payload, rows)
        exponentiated = np.exp(centered - centered.max(axis=1, keepdims=True))

        from_centered = exponentiated / exponentiated.sum(axis=1, keepdims=True)
        assert np.allclose(from_centered, predict_proba(payload, rows))


def test_the_class_with_the_largest_total_contribution_is_the_prediction() -> None:
    # The property a UI depends on: the explanation cannot point at one class
    # while the prediction says another.
    rng = random.Random(7)

    for _ in range(100):
        payload = _random_payload(rng)
        rows = _random_rows(rng, len(payload["feature_names"]))
        totals = feature_contributions(payload, rows).sum(axis=2) + centered_intercepts(payload)

        predicted = predict(payload, rows)
        expected = [payload["classes"][int(i)] for i in totals.argmax(axis=1)]
        assert predicted == expected
