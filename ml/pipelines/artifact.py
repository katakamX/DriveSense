"""`model.json` — a hand-written, human-readable serialiser for the trained model.

`ml/README.md` specifies the artefact as `model.json`, not a pickle, and this
module is why that is possible rather than aspirational: a multinomial
logistic regression over standardised features *is* just numbers — a mean and
a scale per feature, a coefficient per (class, feature), an intercept per
class. Writing them out explicitly buys three things a pickle does not:

1. **Inspectability.** A reviewer can open the artefact and read which feature
   pushes a window towards `HIGH_RISK`, without loading it or trusting it.
2. **No code-execution surface.** `backend/app/ml` loads this at runtime;
   unpickling an artefact is arbitrary code execution, parsing JSON is not.
3. **No version coupling.** The artefact does not embed scikit-learn's object
   graph, so it does not silently break, or silently *change behaviour*, when
   scikit-learn is upgraded. `predict_proba` here is fifteen lines of numpy
   that will mean the same thing in five years.

The cost is that the format is specific to this model class. A tree-based
model would need its own node-dump format; that is a deliberate trade, and the
comparison tree M8 trains is reported as a metric only — it is not serialised
and not the shipped artefact (see `ml/reports/m8-evaluation.md`).

Floats are written at full `repr` precision, so a round-trip is exact rather
than merely close: `predict` on the deserialised artefact returns the same
labels as the fitted scikit-learn pipeline, not similar ones. That is asserted
in `ml/tests/test_train.py`, not assumed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

MODEL_FORMAT = "drivesense-multinomial-logreg"
MODEL_FORMAT_VERSION = "1"

# The arithmetic the artefact encodes, written where a reader will find it.
DECISION_RULE = (
    "z = (x - standardiser.mean) / standardiser.scale; "
    "scores = coefficients @ z + intercepts; "
    "proba = softmax(scores); "
    "prediction = classes[argmax(proba)]"
)


def serialise_logistic_regression(
    *,
    scaler_mean: npt.NDArray[np.float64],
    scaler_scale: npt.NDArray[np.float64],
    coefficients: npt.NDArray[np.float64],
    intercepts: npt.NDArray[np.float64],
    classes: list[str],
    feature_names: list[str],
    excluded_features: dict[str, str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the `model.json` payload from a fitted scaler + logistic regression.

    Takes the fitted arrays rather than the estimator objects so this module
    imports no scikit-learn: the deserialiser is the half `backend/app/ml`
    will depend on, and it should not drag a training dependency with it.
    """
    n_classes, n_features = coefficients.shape
    if n_features != len(feature_names):
        raise ValueError(
            f"coefficients have {n_features} columns but {len(feature_names)} feature names"
        )
    if n_classes != len(classes):
        raise ValueError(f"coefficients have {n_classes} rows but {len(classes)} classes")
    for name, array in (("mean", scaler_mean), ("scale", scaler_scale)):
        if array.shape != (n_features,):
            raise ValueError(
                f"standardiser {name} has shape {array.shape}, expected ({n_features},)"
            )

    payload: dict[str, Any] = {
        "format": MODEL_FORMAT,
        "format_version": MODEL_FORMAT_VERSION,
        "decision_rule": DECISION_RULE,
        "classes": list(classes),
        "feature_names": list(feature_names),
        "excluded_features": dict(excluded_features),
        "standardiser": {
            "mean": [float(value) for value in scaler_mean],
            "scale": [float(value) for value in scaler_scale],
        },
        "coefficients": [[float(value) for value in row] for row in coefficients],
        "intercepts": [float(value) for value in intercepts],
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


def _softmax(scores: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    # Shift by the row max before exponentiating: mathematically a no-op,
    # numerically the difference between a probability and an overflow warning.
    shifted = scores - scores.max(axis=1, keepdims=True)
    exponentiated = np.exp(shifted)
    normalised: npt.NDArray[np.float64] = exponentiated / exponentiated.sum(axis=1, keepdims=True)
    return normalised


def predict_proba(
    payload: dict[str, Any], features: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Class probabilities for each row of `features`, in `payload["classes"]` order.

    `features` must already be ordered by `payload["feature_names"]` — use
    `feature_matrix` to build it from a frame rather than trusting column order.
    """
    standardiser = payload["standardiser"]
    mean = np.asarray(standardiser["mean"], dtype=np.float64)
    scale = np.asarray(standardiser["scale"], dtype=np.float64)
    coefficients = np.asarray(payload["coefficients"], dtype=np.float64)
    intercepts = np.asarray(payload["intercepts"], dtype=np.float64)

    if features.shape[1] != mean.shape[0]:
        raise ValueError(
            f"got {features.shape[1]} features, artefact expects {mean.shape[0]} "
            f"({', '.join(payload['feature_names'])})"
        )

    standardised = (features - mean) / scale
    return _softmax(standardised @ coefficients.T + intercepts)


def predict(payload: dict[str, Any], features: npt.NDArray[np.float64]) -> list[str]:
    """Predicted class label per row of `features`."""
    classes: list[str] = list(payload["classes"])
    indices = predict_proba(payload, features).argmax(axis=1)
    return [classes[int(index)] for index in indices]


def feature_matrix(frame: Any, payload: dict[str, Any]) -> npt.NDArray[np.float64]:
    """Select and order `frame`'s columns to match the artefact's feature list.

    Column *order* is part of the artefact's contract — coefficients are
    positional — so this selects by name rather than assuming the caller's
    frame happens to be in the right order.
    """
    names: list[str] = list(payload["feature_names"])
    missing = [name for name in names if name not in frame.columns]
    if missing:
        raise ValueError(f"frame is missing feature column(s) required by the artefact: {missing}")
    return np.asarray(frame[names].to_numpy(dtype=np.float64))


def write_model_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_model_json(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != MODEL_FORMAT:
        raise ValueError(
            f"{path.name}: expected format {MODEL_FORMAT!r}, got {payload.get('format')!r}"
        )
    if payload.get("format_version") != MODEL_FORMAT_VERSION:
        raise ValueError(
            f"{path.name}: artefact format version {payload.get('format_version')!r} "
            f"is not the {MODEL_FORMAT_VERSION!r} this reader understands"
        )
    return payload
