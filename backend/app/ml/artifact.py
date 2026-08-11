"""`model.json`'s reader half: parse the artefact, evaluate it, explain it.

This is the deserialiser split out of `ml/pipelines/artifact.py`, whose
docstring already named this module as the consumer ("`backend/app/ml` loads
this at runtime; unpickling an artefact is arbitrary code execution, parsing
JSON is not"). The serialiser stays on the training side — it needs a fitted
estimator's arrays, and nothing here should suggest the backend can produce an
artefact — and `pipelines.artifact` imports these names back, so the decision
rule has one implementation rather than a training copy and a serving copy
that drift. That is ADR 0004's argument applied to the model itself: the
reason feature extraction lives in the backend and is imported by the pipeline
is the same reason the decision rule now does.

Everything here is a pure function of `(payload, features)`. Module state —
which artefact is loaded, and whether one is loaded at all — lives in
`app.ml.loader`, so this half stays trivially testable and reusable offline.

## Contributions

`predict_proba` answers *what*; `feature_contributions` answers *why*. For a
multinomial logistic regression the raw per-feature term `coefficients[c][f] *
z[f]` is a poor explanation, because softmax is invariant to adding a constant
to every class's score: a feature can carry a large coefficient for every
class and still say nothing about which class wins. Centering the coefficients
across classes removes exactly that shared component:

    contribution[c][f] = (coefficients[c][f] - mean_over_classes(coefficients[.][f])) * z[f]

What remains is the part of the score that actually discriminates, and it sums
exactly:

    sum_f contribution[c][f] + centered_intercept[c] == score[c] - mean(score)

That identity is the correctness proof for the explainability path and is
asserted as a property in `backend/tests/test_ml_artifact.py`, not assumed.
A positive contribution means the feature pushed this window towards class `c`
relative to the average class; a negative one pushed it away.
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


def _softmax(scores: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    # Shift by the row max before exponentiating: mathematically a no-op,
    # numerically the difference between a probability and an overflow warning.
    shifted = scores - scores.max(axis=1, keepdims=True)
    exponentiated = np.exp(shifted)
    normalised: npt.NDArray[np.float64] = exponentiated / exponentiated.sum(axis=1, keepdims=True)
    return normalised


def standardise(
    payload: dict[str, Any], features: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """`z = (x - mean) / scale` — the standardised features the model actually sees.

    Exposed because contributions are stated in units of `z`, so a caller
    explaining a prediction needs the same numbers the coefficients multiply.
    """
    standardiser = payload["standardiser"]
    mean = np.asarray(standardiser["mean"], dtype=np.float64)
    scale = np.asarray(standardiser["scale"], dtype=np.float64)

    if features.shape[1] != mean.shape[0]:
        raise ValueError(
            f"got {features.shape[1]} features, artefact expects {mean.shape[0]} "
            f"({', '.join(payload['feature_names'])})"
        )
    standardised: npt.NDArray[np.float64] = (features - mean) / scale
    return standardised


def scores(payload: dict[str, Any], features: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Pre-softmax logits, one row per input row, in `payload["classes"]` order."""
    coefficients = np.asarray(payload["coefficients"], dtype=np.float64)
    intercepts = np.asarray(payload["intercepts"], dtype=np.float64)
    raw: npt.NDArray[np.float64] = standardise(payload, features) @ coefficients.T + intercepts
    return raw


def predict_proba(
    payload: dict[str, Any], features: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Class probabilities for each row of `features`, in `payload["classes"]` order.

    `features` must already be ordered by `payload["feature_names"]` — use
    `pipelines.artifact.feature_matrix` (offline) or `app.ml.loader` (online)
    to build it, rather than trusting the caller's column order.
    """
    return _softmax(scores(payload, features))


def predict(payload: dict[str, Any], features: npt.NDArray[np.float64]) -> list[str]:
    """Predicted class label per row of `features`."""
    classes: list[str] = list(payload["classes"])
    indices = predict_proba(payload, features).argmax(axis=1)
    return [classes[int(index)] for index in indices]


def centered_coefficients(payload: dict[str, Any]) -> npt.NDArray[np.float64]:
    """Coefficients with the per-feature across-class mean removed, shape (classes, features)."""
    coefficients = np.asarray(payload["coefficients"], dtype=np.float64)
    centered: npt.NDArray[np.float64] = coefficients - coefficients.mean(axis=0, keepdims=True)
    return centered


def centered_intercepts(payload: dict[str, Any]) -> npt.NDArray[np.float64]:
    """Intercepts with the across-class mean removed, shape (classes,)."""
    intercepts = np.asarray(payload["intercepts"], dtype=np.float64)
    centered: npt.NDArray[np.float64] = intercepts - intercepts.mean()
    return centered


def centered_logits(
    payload: dict[str, Any], features: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Scores with each row's across-class mean removed, shape (rows, classes).

    The quantity contributions decompose. Softmax is unchanged by this shift,
    so these order and separate the classes exactly as the raw scores do.
    """
    raw = scores(payload, features)
    centered: npt.NDArray[np.float64] = raw - raw.mean(axis=1, keepdims=True)
    return centered


def feature_contributions(
    payload: dict[str, Any], features: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Per-(row, class, feature) contribution to the centered logit.

    `contribution[r][c][f] = centered_coefficients[c][f] * z[r][f]`, so that
    `contributions[r][c].sum() + centered_intercepts[c] == centered_logits[r][c]`.
    See this module's docstring for why the centering is not optional.
    """
    standardised = standardise(payload, features)
    centered = centered_coefficients(payload)
    # (rows, 1, features) * (classes, features) -> (rows, classes, features)
    contributions: npt.NDArray[np.float64] = standardised[:, np.newaxis, :] * centered
    return contributions
