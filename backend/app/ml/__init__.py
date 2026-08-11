"""Runtime model inference: load `model.json`, predict, explain.

Two halves. `artifact` is the pure decision rule — the deserialiser moved out
of `ml/pipelines/artifact.py`, which now imports it back so training and
serving share one implementation. `loader` holds the process-wide artefact and
turns a feature vector into a `ModelOutput`, returning `None` when no artefact
is present (the default state of a fresh checkout).
"""

from app.ml.artifact import (
    DECISION_RULE,
    MODEL_FORMAT,
    MODEL_FORMAT_VERSION,
    centered_coefficients,
    centered_intercepts,
    centered_logits,
    feature_contributions,
    predict_proba,
    read_model_json,
    scores,
    standardise,
)
from app.ml.loader import (
    ModelOutput,
    get_model,
    load_model,
    model_fingerprint,
    model_is_loaded,
    model_source,
    predict,
    unload_model,
)

__all__ = [
    "DECISION_RULE",
    "MODEL_FORMAT",
    "MODEL_FORMAT_VERSION",
    "ModelOutput",
    "centered_coefficients",
    "centered_intercepts",
    "centered_logits",
    "feature_contributions",
    "get_model",
    "load_model",
    "model_fingerprint",
    "model_is_loaded",
    "model_source",
    "predict",
    "predict_proba",
    "read_model_json",
    "scores",
    "standardise",
    "unload_model",
]
