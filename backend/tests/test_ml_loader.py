"""Tests for the process-wide artefact: loading it, and running without one.

The no-artefact case gets equal billing here on purpose. `ml/artifacts/` is
gitignored, so *every fresh checkout* starts in that state — it is the default
path through this code, not an edge case — and the contract is that
`predict` returns `None` rather than raising, so callers branch instead of
catching.
"""

import json
import math
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.ml import loader
from app.ml.loader import ModelOutput, get_model, load_model, model_is_loaded, predict, unload_model

FIXTURE_MODEL = Path(__file__).parent / "fixtures" / "model.json"

# Values the golden artefact standardises to z = (2.0, 2.0, 1.0); see
# test_ml_artifact.py, which pins the arithmetic these results come from.
GOLDEN_FEATURES = {"speed_mean": 70.0, "accel_std": 2.0, "jerk_std": 6.0}
GOLDEN_SCORES = {"SAFE": -6.0, "AGGRESSIVE": 3.0, "HIGH_RISK": 5.25}


@pytest.fixture(autouse=True)
def _isolated_model_state() -> Iterator[None]:
    """Module state is process-wide; no test may leak an artefact into another."""
    unload_model()
    yield
    unload_model()


# --- No artefact present (the default state of a fresh checkout) -------------


def test_predict_returns_none_when_no_artefact_is_loaded() -> None:
    assert predict(GOLDEN_FEATURES) is None


def test_loading_a_missing_artefact_is_not_an_error(tmp_path: Path) -> None:
    assert load_model(tmp_path / "nowhere" / "model.json") is None
    assert model_is_loaded() is False
    assert get_model() is None
    assert predict(GOLDEN_FEATURES) is None


def test_a_missing_artefact_is_logged_not_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO", logger=loader.__name__):
        load_model(tmp_path / "model.json")

    assert "rule-only" in caplog.text


def test_a_malformed_artefact_does_raise(tmp_path: Path) -> None:
    # The distinction the loader draws: absent is normal, broken is not.
    path = tmp_path / "model.json"
    path.write_text(json.dumps({"format": "something-else"}))

    with pytest.raises(ValueError, match="expected format"):
        load_model(path)


# --- Artefact present --------------------------------------------------------


def test_loading_the_golden_artefact_populates_module_state() -> None:
    payload = load_model(FIXTURE_MODEL)

    assert payload is not None
    assert model_is_loaded() is True
    assert get_model() is payload
    assert loader.model_source() == FIXTURE_MODEL


def test_golden_prediction_through_the_loader() -> None:
    load_model(FIXTURE_MODEL)

    output = predict(GOLDEN_FEATURES)

    assert isinstance(output, ModelOutput)
    assert output.predicted_class == "HIGH_RISK"

    total = sum(math.exp(s) for s in GOLDEN_SCORES.values())
    expected = {cls: math.exp(s) / total for cls, s in GOLDEN_SCORES.items()}
    assert output.probabilities == pytest.approx(expected)
    assert sum(output.probabilities.values()) == pytest.approx(1.0)


def test_contributions_are_keyed_by_class_then_feature() -> None:
    load_model(FIXTURE_MODEL)

    output = predict(GOLDEN_FEATURES)

    assert output is not None
    assert set(output.contributions) == {"SAFE", "AGGRESSIVE", "HIGH_RISK"}
    assert set(output.contributions["HIGH_RISK"]) == set(GOLDEN_FEATURES)
    assert output.contributions["HIGH_RISK"]["speed_mean"] == pytest.approx(1.5)


def test_the_loader_preserves_the_contribution_sum_invariant() -> None:
    # Same invariant as the property test, asserted once through the dict-shaped
    # public API, so a naming or ordering bug in the zip cannot hide it.
    load_model(FIXTURE_MODEL)
    mean_score = sum(GOLDEN_SCORES.values()) / len(GOLDEN_SCORES)

    output = predict(GOLDEN_FEATURES)

    assert output is not None
    for cls, score in GOLDEN_SCORES.items():
        total = sum(output.contributions[cls].values()) + output.centered_intercepts[cls]
        assert total == pytest.approx(score - mean_score)


def test_features_are_selected_by_name_not_by_position() -> None:
    # The artefact names three features; a real feature vector carries 26 in
    # `FEATURE_NAMES` order. Selection by name is what keeps the coefficients
    # aligned, and excluded features are why the artefact's list is a subset.
    load_model(FIXTURE_MODEL)
    padded = {"jerk_std": 6.0, "unused": 999.0, "accel_std": 2.0, "speed_mean": 70.0}

    output = predict(padded)

    assert output is not None
    assert output.predicted_class == "HIGH_RISK"


def test_a_feature_vector_missing_a_required_value_is_rejected() -> None:
    load_model(FIXTURE_MODEL)

    with pytest.raises(ValueError, match="missing value"):
        predict({"speed_mean": 70.0, "accel_std": 2.0})


def test_unload_returns_to_the_rule_only_state() -> None:
    load_model(FIXTURE_MODEL)

    unload_model()

    assert model_is_loaded() is False
    assert predict(GOLDEN_FEATURES) is None
