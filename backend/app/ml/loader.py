"""Load `model.json` once at startup and hold it in module state.

The artefact is a few kilobytes of numbers and never changes while the process
runs, so it is read once at application startup and kept in memory rather than
re-read per request. Same single-worker justification as
`app.core.live.broadcaster` and `app.core.events.state`
(docs/adr/0003-defer-redis.md): module state, one process.

**No artefact is a normal state, not an error.** `ml/artifacts/` is gitignored
— a fresh checkout has no `model.json` until someone runs the training
pipeline, and the backend must come up and serve anyway, rule-only, on the
event detectors alone. So `load_model` returns `None` for a missing file and
logs it at INFO, and `predict` returns `None` rather than raising. Callers
branch on `None`; they do not catch exceptions to discover the model is
absent. A *malformed* or wrong-version artefact is a different thing and does
raise, because it means someone shipped a broken file and silently ignoring it
would hide that.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.config import get_settings
from app.ml.artifact import (
    centered_intercepts,
    feature_contributions,
    predict_proba,
    read_model_json,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelOutput:
    """One window's prediction, with the evidence for it.

    `contributions` is keyed class -> feature -> signed contribution to that
    class's centered logit; see `app.ml.artifact` for the arithmetic and the
    invariant that makes the numbers add up.
    """

    predicted_class: str
    probabilities: dict[str, float]
    contributions: dict[str, dict[str, float]]
    centered_intercepts: dict[str, float]


# Module state: the loaded artefact, or None when there is none to load.
_payload: dict[str, Any] | None = None
_source_path: Path | None = None


def load_model(path: Path | None = None) -> dict[str, Any] | None:
    """Read the artefact into module state and return it, or `None` if absent.

    Called from the application lifespan. Idempotent enough to call again with
    an explicit path (tests do); the last successful load wins.
    """
    global _payload, _source_path

    resolved = path if path is not None else get_settings().model_path
    if not resolved.is_file():
        logger.info(
            "No model artefact at %s — running rule-only "
            "(train one with `python -m pipelines.train`)",
            resolved,
        )
        _payload, _source_path = None, None
        return None

    payload = read_model_json(resolved)
    _payload, _source_path = payload, resolved
    logger.info(
        "Loaded model artefact %s: %d classes, %d features",
        resolved,
        len(payload["classes"]),
        len(payload["feature_names"]),
    )
    return payload


def unload_model() -> None:
    """Drop the loaded artefact. For tests, and for symmetry with `load_model`."""
    global _payload, _source_path
    _payload, _source_path = None, None


def get_model() -> dict[str, Any] | None:
    """The loaded artefact payload, or `None` when running rule-only."""
    return _payload


def model_is_loaded() -> bool:
    return _payload is not None


def model_source() -> Path | None:
    """Where the loaded artefact came from. For diagnostics."""
    return _source_path


def predict(features: Mapping[str, float]) -> ModelOutput | None:
    """Classify one feature vector, or return `None` when no artefact is loaded.

    `features` is keyed by feature name (`FeatureVector.as_dict()`), not
    positional: the artefact carries its own `feature_names`, which is a
    *subset* of `FEATURE_NAMES` whenever training excluded a degenerate
    feature. Selecting by name here is what keeps the coefficients aligned
    with the values they multiply.
    """
    payload = _payload
    if payload is None:
        return None

    names: list[str] = list(payload["feature_names"])
    missing = [name for name in names if name not in features]
    if missing:
        raise ValueError(f"feature vector is missing value(s) required by the artefact: {missing}")

    row = np.asarray([[float(features[name]) for name in names]], dtype=np.float64)
    classes: list[str] = list(payload["classes"])

    probabilities = predict_proba(payload, row)[0]
    contributions = feature_contributions(payload, row)[0]
    intercepts = centered_intercepts(payload)

    return ModelOutput(
        predicted_class=classes[int(probabilities.argmax())],
        probabilities={cls: float(p) for cls, p in zip(classes, probabilities, strict=True)},
        contributions={
            cls: {name: float(value) for name, value in zip(names, row_c, strict=True)}
            for cls, row_c in zip(classes, contributions, strict=True)
        },
        centered_intercepts={
            cls: float(value) for cls, value in zip(classes, intercepts, strict=True)
        },
    )
