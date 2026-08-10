"""Training tests: the artefact round-trip, and the metric guards.

The load-bearing test here is `test_artifact_round_trips_exactly`. `model.json`
is hand-serialised (`pipelines.artifact`) precisely so it is readable and
pickle-free, and the whole bet is that a dump of numbers reproduces the fitted
model. If it does not — a lost digit, a transposed coefficient matrix, a
forgotten standardiser — the artefact is a plausible-looking file that predicts
something other than what was trained and evaluated. That failure would be
silent everywhere except here, so it is asserted on exact label equality rather
than on a tolerance.

Everything runs on a small synthetic fixture rather than the real corpus: the
Parquet inputs are gitignored, and CI has to be able to run these.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from app.core.features import FEATURE_NAMES

from pipelines import evaluate as ev
from pipelines.artifact import (
    MODEL_FORMAT,
    feature_matrix,
    predict,
    predict_proba,
    read_model_json,
    write_model_json,
)
from pipelines.split import CLASS_ORDER, build_manifest
from pipelines.train import (
    DEFAULT_CONFIG_PATH,
    LOGREG_MODEL,
    MAJORITY_MODEL,
    TREE_MODEL,
    TrainConfig,
    build_decision_tree,
    build_logistic_regression,
    fit_final_logistic_regression,
    load_config,
    run_cross_validation,
)

PROFILES = {
    "calm": (["a", "b", "c"], "CALM"),
    "normal": (["a", "b", "c"], "NORMAL"),
    "aggressive": (["a", "b", "c"], "AGGRESSIVE"),
    "high_risk": (["a", "b", "c", "d"], "HIGH_RISK"),
}

# Per-class feature offsets, so the fixture is learnable but not trivially so —
# a model that cannot separate these is broken, and one that scores a perfect
# 1.000 would make the round-trip assertion vacuous.
CLASS_OFFSET = {"CALM": -1.5, "NORMAL": 0.0, "AGGRESSIVE": 1.5, "HIGH_RISK": 3.0}


def _fixture_frame(*, seeds: int = 3, windows: int = 8, noise: float = 0.6) -> pd.DataFrame:
    rng = np.random.default_rng(20260810)
    rows: list[dict[str, object]] = []
    for profile, (variants, label) in PROFILES.items():
        for variant in variants:
            for seed in range(seeds):
                recording_id = f"{profile}-{variant}-seed{1000 + seed}"
                for index in range(windows):
                    values = rng.normal(CLASS_OFFSET[label], noise, size=len(FEATURE_NAMES))
                    row: dict[str, object] = {
                        "window_id": f"{recording_id}::{index:04d}",
                        "recording_id": recording_id,
                        "rubric_label": label,
                    }
                    row.update(dict(zip(FEATURE_NAMES, values.tolist(), strict=True)))
                    rows.append(row)
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def config() -> TrainConfig:
    return load_config(DEFAULT_CONFIG_PATH)


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    from pipelines.split import add_split_columns

    return add_split_columns(_fixture_frame())


# --- Configuration ---------------------------------------------------------------


def test_the_committed_config_excludes_rapid_accel_per_min(config: TrainConfig) -> None:
    """The M8 feature decision, asserted rather than trusted to the YAML staying put."""
    assert "rapid_accel_per_min" in config.excluded_features
    assert config.excluded_features["rapid_accel_per_min"]
    assert "rapid_accel_per_min" not in config.feature_names


def test_feature_subset_is_the_shared_list_minus_exclusions(config: TrainConfig) -> None:
    names = config.feature_names
    excluded = config.excluded_features

    assert len(names) == len(FEATURE_NAMES) - len(excluded)
    # Order must follow the shared list: coefficients are positional.
    assert names == [name for name in FEATURE_NAMES if name not in excluded]


# --- The artefact round-trip -------------------------------------------------------


def test_artifact_round_trips_exactly(
    frame: pd.DataFrame, config: TrainConfig, tmp_path: Path
) -> None:
    pipeline, payload = fit_final_logistic_regression(frame, config)

    path = tmp_path / "model.json"
    write_model_json(payload, path)
    reloaded = read_model_json(path)

    features = feature_matrix(frame, reloaded)
    from_artifact = predict(reloaded, features)
    from_pipeline = [str(value) for value in pipeline.predict(features)]

    assert from_artifact == from_pipeline, "the serialised artefact is not the fitted model"


def test_artifact_probabilities_match_the_fitted_pipeline(
    frame: pd.DataFrame, config: TrainConfig
) -> None:
    pipeline, payload = fit_final_logistic_regression(frame, config)
    features = feature_matrix(frame, payload)

    np.testing.assert_allclose(
        predict_proba(payload, features), pipeline.predict_proba(features), rtol=1e-9, atol=1e-12
    )


def test_artifact_is_plain_readable_json(
    frame: pd.DataFrame, config: TrainConfig, tmp_path: Path
) -> None:
    _, payload = fit_final_logistic_regression(frame, config)
    path = tmp_path / "model.json"
    write_model_json(payload, path)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["format"] == MODEL_FORMAT
    assert loaded["classes"] == list(CLASS_ORDER)
    assert len(loaded["coefficients"]) == len(CLASS_ORDER)
    assert len(loaded["coefficients"][0]) == len(loaded["feature_names"])
    assert len(loaded["standardiser"]["mean"]) == len(loaded["feature_names"])
    # The deliberate exclusion travels with the artefact, not only with the report.
    assert "rapid_accel_per_min" in loaded["excluded_features"]


def test_reader_rejects_a_foreign_artifact(tmp_path: Path) -> None:
    path = tmp_path / "model.json"
    path.write_text(json.dumps({"format": "something-else"}), encoding="utf-8")
    with pytest.raises(ValueError, match="expected format"):
        read_model_json(path)


def test_feature_matrix_rejects_a_frame_missing_a_feature(
    frame: pd.DataFrame, config: TrainConfig
) -> None:
    _, payload = fit_final_logistic_regression(frame, config)
    with pytest.raises(ValueError, match="missing feature column"):
        feature_matrix(frame.drop(columns=[payload["feature_names"][0]]), payload)


def test_feature_matrix_is_ordered_by_the_artifact_not_the_frame(
    frame: pd.DataFrame, config: TrainConfig
) -> None:
    """Coefficients are positional, so column order must come from the artefact."""
    _, payload = fit_final_logistic_regression(frame, config)
    shuffled = frame[list(reversed(frame.columns.tolist()))]

    np.testing.assert_array_equal(feature_matrix(shuffled, payload), feature_matrix(frame, payload))


# --- Cross-validation smoke ---------------------------------------------------------


def test_cross_validation_produces_one_out_of_fold_prediction_per_window(
    frame: pd.DataFrame, config: TrainConfig
) -> None:
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("fixture.parquet"))
    run = run_cross_validation(frame, manifest, config)

    for model in (LOGREG_MODEL, TREE_MODEL):
        assert len(run.out_of_fold[model]) == len(frame)
        assert "" not in run.out_of_fold[model], "a window was never in a test fold"
        assert set(run.out_of_fold[model]) <= set(CLASS_ORDER)
    assert sum(run.fold_sizes) == len(frame)


def test_all_three_models_are_scored_on_the_same_folds(
    frame: pd.DataFrame, config: TrainConfig
) -> None:
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("fixture.parquet"))
    run = run_cross_validation(frame, manifest, config)

    assert set(run.summaries) == {MAJORITY_MODEL, LOGREG_MODEL, TREE_MODEL}
    sizes = {
        model: [metrics.n_windows for metrics in summary.folds]
        for model, summary in run.summaries.items()
    }
    assert len({tuple(value) for value in sizes.values()}) == 1, "models saw different test sets"


def test_the_majority_baseline_is_degenerate_by_construction(
    frame: pd.DataFrame, config: TrainConfig
) -> None:
    """The guard has to fire on the one model that is definitionally degenerate."""
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("fixture.parquet"))
    run = run_cross_validation(frame, manifest, config)

    flags = run.summaries[MAJORITY_MODEL].flags
    assert flags, "the always-guess-one-class baseline was not flagged as degenerate"
    assert any("zero recall" in flag for flag in flags)


def test_a_learnable_fixture_beats_the_majority_baseline(
    frame: pd.DataFrame, config: TrainConfig
) -> None:
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("fixture.parquet"))
    run = run_cross_validation(frame, manifest, config)

    logreg = run.summaries[LOGREG_MODEL]
    assert logreg.macro_f1.mean > run.summaries[MAJORITY_MODEL].macro_f1.mean
    assert logreg.accuracy.mean > logreg.majority_accuracy.mean


def test_models_are_constructible_from_the_committed_config(config: TrainConfig) -> None:
    assert build_logistic_regression(config).named_steps["logreg"].class_weight == "balanced"
    assert build_decision_tree(config).class_weight == "balanced"


# --- Metric guards --------------------------------------------------------------------


def test_majority_baseline_accuracy_is_reported_next_to_the_model() -> None:
    truth = ["NORMAL"] * 90 + ["HIGH_RISK"] * 10
    always_normal = ["NORMAL"] * 100
    metrics = ev.evaluate_predictions(
        truth, always_normal, name="degenerate", majority_label="NORMAL"
    )

    assert metrics.accuracy == pytest.approx(0.90)
    assert metrics.majority_accuracy == pytest.approx(0.90)
    assert not metrics.beats_majority
    # The whole point: 0.90 accuracy, and macro-F1 sees straight through it.
    assert metrics.macro_f1 < 0.30
    assert metrics.high_risk_recall == 0.0
    assert "HIGH_RISK" in metrics.zero_recall_labels


def test_flags_name_every_degenerate_condition() -> None:
    truth = ["NORMAL"] * 90 + ["HIGH_RISK"] * 10
    metrics = ev.evaluate_predictions(
        truth, ["NORMAL"] * 100, name="degenerate", majority_label="NORMAL"
    )
    joined = " ".join(metrics.flags)

    assert "DEGENERATE" in joined
    assert "HIGH_RISK" in joined
    assert "majority-class baseline" in joined


def test_a_healthy_prediction_raises_no_flags() -> None:
    truth = list(CLASS_ORDER) * 10
    metrics = ev.evaluate_predictions(truth, truth, name="perfect", majority_label="NORMAL")

    assert metrics.flags == ()
    assert metrics.macro_f1 == pytest.approx(1.0)
    assert metrics.balanced_accuracy == pytest.approx(1.0)


def test_majority_label_comes_from_training_not_test_labels() -> None:
    """A baseline told the test majority would be cheating; it gets the train one."""
    truth = ["HIGH_RISK"] * 80 + ["NORMAL"] * 20
    metrics = ev.evaluate_predictions(
        truth, ["NORMAL"] * 100, name="mismatched", majority_label="NORMAL"
    )
    assert metrics.majority_accuracy == pytest.approx(0.20)


def test_spread_reports_mean_and_variation() -> None:
    spread = ev.spread_of([0.2, 0.4, 0.6])
    assert spread.mean == pytest.approx(0.4)
    assert spread.std > 0
    assert (spread.minimum, spread.maximum) == (0.2, 0.6)


def test_confusion_matrix_rows_are_the_truth() -> None:
    metrics = ev.evaluate_predictions(
        ["HIGH_RISK", "HIGH_RISK"], ["NORMAL", "HIGH_RISK"], name="x", majority_label="NORMAL"
    )
    high_risk_row = metrics.confusion[CLASS_ORDER.index("HIGH_RISK")]

    assert high_risk_row[CLASS_ORDER.index("HIGH_RISK")] == 1
    assert high_risk_row[CLASS_ORDER.index("NORMAL")] == 1
    assert metrics.recall_of("HIGH_RISK") == pytest.approx(0.5)
