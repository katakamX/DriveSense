"""Wire shape for a risk assessment on the live stream.

`telemetry` and `event` messages put a bare dict in `LiveMessage.data`. This
one does not, for two reasons: a risk payload has fifteen fields rather than
six, and it is the message a dashboard makes a decision from. Validating it
here means the shape appears in the OpenAPI document and a typo in the
producer fails at the boundary rather than in a browser.
"""

from pydantic import BaseModel, ConfigDict

from app.core.risk.schema import Provenance, RiskAssessment, RiskBand


class FeatureContributionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feature: str
    value: float
    contribution: float


class RiskOut(BaseModel):
    """One window's assessment, as published and as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    window_start: str
    window_end: str
    sample_count: int
    coverage_ratio: float

    score: float
    band: RiskBand
    confidence: float
    provenance: Provenance
    model_available: bool
    gated: bool

    rule_band: RiskBand
    matched_rules: list[str]
    model_band: RiskBand | None
    model_score: float | None
    model_predicted_class: str | None
    probabilities: dict[str, float] | None
    contributions: list[FeatureContributionOut]
    contributions_remainder: float

    risk_engine_version: str
    feature_version: str
    rubric_version: str
    model_version: str | None

    @classmethod
    def from_assessment(cls, assessment: RiskAssessment) -> "RiskOut":
        return cls(
            window_start=assessment.window_start.isoformat(),
            window_end=assessment.window_end.isoformat(),
            sample_count=assessment.sample_count,
            coverage_ratio=assessment.coverage_ratio,
            score=assessment.score,
            band=assessment.band,
            confidence=assessment.confidence,
            provenance=assessment.provenance,
            model_available=assessment.model_available,
            gated=assessment.gated,
            rule_band=assessment.rule_band,
            matched_rules=list(assessment.matched_rules),
            model_band=assessment.model_band,
            model_score=assessment.model_score,
            model_predicted_class=assessment.model_predicted_class,
            probabilities=dict(assessment.probabilities)
            if assessment.probabilities is not None
            else None,
            contributions=[
                FeatureContributionOut.model_validate(contribution)
                for contribution in assessment.contributions
            ],
            contributions_remainder=assessment.contributions_remainder,
            risk_engine_version=assessment.risk_engine_version,
            feature_version=assessment.feature_version,
            rubric_version=assessment.rubric_version,
            model_version=assessment.model_version,
        )
