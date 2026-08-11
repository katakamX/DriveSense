"""Pure, versioned, explainable risk scoring (Milestone 9).

Four pure modules and one impure one. `schema` is the vocabulary, `rules` the
decision list moved here from the offline labeller, `score` the function that
turns a window and a model output into a `RiskAssessment`, and `aggregate` the
fold that reduces a trip's worth of them to one verdict. None of those four
imports `sink`, which is the module that writes to PostgreSQL — see its
docstring for why it is here at all.

`sink` is deliberately *not* re-exported. Importing it pulls in SQLAlchemy and
the database session, and the point of the split is that a caller wanting to
score something never needs either. Import it by path — `from app.core.risk
import sink` — which makes the dependency visible at the import site.
"""

from app.core.risk.aggregate import (
    EMPTY,
    TripRiskAccumulator,
    TripRiskSummary,
    finalise,
    fold,
    fold_all,
    summarise,
)
from app.core.risk.rules import RUBRIC_VERSION, RULE_IDS, Label, RuleOutcome, evaluate
from app.core.risk.rules import label_window_with_reason as label_window_with_reason
from app.core.risk.schema import (
    BAND_ORDER,
    BAND_SEVERITY,
    RISK_ENGINE_VERSION,
    SCORE_MAX,
    SCORE_MIN,
    FeatureContribution,
    Provenance,
    RiskAssessment,
    RiskBand,
    band_for_score,
    band_index,
    band_score_range,
    clamp_into_band,
    max_band,
    min_band,
)
from app.core.risk.score import (
    DEFAULT_TOP_K,
    DISAGREEMENT_PENALTY,
    RULE_ONLY_CONFIDENCE,
    assess,
    expected_severity,
)

__all__ = [
    "BAND_ORDER",
    "BAND_SEVERITY",
    "DEFAULT_TOP_K",
    "DISAGREEMENT_PENALTY",
    "EMPTY",
    "RISK_ENGINE_VERSION",
    "RUBRIC_VERSION",
    "RULE_IDS",
    "RULE_ONLY_CONFIDENCE",
    "SCORE_MAX",
    "SCORE_MIN",
    "FeatureContribution",
    "Label",
    "Provenance",
    "RiskAssessment",
    "RiskBand",
    "RuleOutcome",
    "TripRiskAccumulator",
    "TripRiskSummary",
    "assess",
    "band_for_score",
    "band_index",
    "band_score_range",
    "clamp_into_band",
    "evaluate",
    "expected_severity",
    "finalise",
    "fold",
    "fold_all",
    "label_window_with_reason",
    "max_band",
    "min_band",
    "summarise",
]
