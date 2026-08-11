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
   scikit-learn is upgraded. `predict_proba` is fifteen lines of numpy that
   will mean the same thing in five years.

The cost is that the format is specific to this model class. A tree-based
model would need its own node-dump format; that is a deliberate trade, and the
comparison tree M8 trains is reported as a metric only — it is not serialised
and not the shipped artefact (see `ml/reports/m8-evaluation.md`).

Floats are written at full `repr` precision, so a round-trip is exact rather
than merely close: `predict` on the deserialised artefact returns the same
labels as the fitted scikit-learn pipeline, not similar ones. That is asserted
in `ml/tests/test_train.py`, not assumed.

**The reader half now lives in `backend/app/ml/artifact.py`** — the split this
docstring anticipated when it said the backend loads the artefact at runtime.
`read_model_json`, `predict_proba` and `predict` are imported back from there
and re-exported here, so training and serving evaluate the artefact with the
same code rather than with two implementations that agree until they don't.
What stays is what only training needs: the serialiser, the writer, and
`feature_matrix` (which takes a pandas frame the backend has no reason to
depend on).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from app.ml.artifact import (
    DECISION_RULE,
    MODEL_FORMAT,
    MODEL_FORMAT_VERSION,
    centered_coefficients,
    centered_intercepts,
    centered_logits,
    feature_contributions,
    predict,
    predict_proba,
    read_model_json,
    scores,
    standardise,
)

__all__ = [
    "DECISION_RULE",
    "MODEL_FORMAT",
    "MODEL_FORMAT_VERSION",
    "centered_coefficients",
    "centered_intercepts",
    "centered_logits",
    "feature_contributions",
    "feature_matrix",
    "predict",
    "predict_proba",
    "read_model_json",
    "scores",
    "serialise_logistic_regression",
    "standardise",
    "write_model_json",
]


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
