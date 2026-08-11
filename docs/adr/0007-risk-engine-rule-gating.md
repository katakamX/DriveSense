# ADR 0007 — The rules gate the risk engine's top band

- **Status:** Accepted
- **Date:** 2026-08-11
- **Milestone:** 9

## Context

Milestone 9 turns a model prediction and a rule evaluation into one published
number: a 0–100 risk score and one of four bands (`CALM`, `NORMAL`,
`AGGRESSIVE`, `HIGH_RISK`). The obvious design is to take the model's
`argmax` as the band and be done.

Milestone 8 measured what that would produce. From
[the model card](../model-card.md), on 1,709 windows of real UAH-DriveSet
telemetry:

- **`HIGH_RISK` precision is 0.105.** The model recovers 10 of the 16
  high-risk windows by predicting the class **95 times**. Roughly nine of
  every ten `HIGH_RISK` predictions on real driving are wrong.
- **16.0% of windows from trips UAH itself labelled `normal` are predicted
  `AGGRESSIVE` or `HIGH_RISK`.** One window in six of an ordinary trip.
- **`HIGH_RISK` is 16 windows on UAH** (0.9%), against 14.1% of the training
  corpus. Every per-class figure above rests on sixteen windows and carries an
  interval wide enough to swallow it.

One finding points the other way, and it is the reason the model is used at
all: **the severity ordering survives.** Windows from `aggressive`-labelled
trips are predicted `AGGRESSIVE` or `HIGH_RISK` 65.9% of the time, against
16.0% for `normal` trips. The model has not inverted the problem. Its
operating point is in the wrong place; its ranking is not.

Against that sits the rubric's one `HIGH_RISK` rule — sustained speeding plus
hard deceleration — which fires on 12 UAH windows and **on no
`normal`-labelled window at all** (ADR 0006). It is not ground truth either;
it is ten hand-set thresholds calibrated once against UAH percentiles. But its
failure mode is different in kind: a decision list is wrong in ways a reader
can check, and this rule's population is documented.

The band that matters is `HIGH_RISK`. It is the one a dashboard colours red,
the one a coaching feature would act on, and the one whose false positives
teach a user to ignore the system.

## Decision

**`HIGH_RISK` is emitted only when the rule layer independently reaches
`HIGH_RISK`. The model on its own is capped at `AGGRESSIVE`.**

Stated as the whole gate, where `rule_band` comes from
`app.core.risk.rules.evaluate` and `model_band` from the model's expected
severity:

```
ceiling = HIGH_RISK if rule_band is HIGH_RISK else AGGRESSIVE
band    = max(rule_band, min(model_band, ceiling))
```

Three consequences follow from that one line:

- Rules **raise** the band: a window the rules call `HIGH_RISK` is
  `HIGH_RISK`, whatever the model thinks.
- Rules **cap** the band at `AGGRESSIVE` when they have not reached
  `HIGH_RISK` themselves.
- Rules **never lower** a band below `AGGRESSIVE`. A model shouting about a
  window the rules have nothing to say about is still information, and
  discarding it would throw away the one thing M8 showed transfers.

Two further decisions make the gate legible rather than silent.

**The score is expected severity, not `p(HIGH_RISK)`.** The four bands sit at
0, 100/3, 200/3 and 100, and the score is the probability-weighted mean of
those anchors. A score keyed to `p(HIGH_RISK)` would be keyed to the single
least trustworthy output the model has; expected severity spreads the same
information across all four heads, which is where the surviving ordering
lives. It is also bounded in [0, 100] by construction, being a convex
combination.

**Every assessment says which source produced it.** `Provenance` is one of
`RULES_ONLY`, `MODEL_AND_RULES_AGREE` or `MODEL_ONLY`, a `gated` flag records
whether the ceiling actually bound, and the model's own band and argmax travel
alongside the emitted one. A user seeing `AGGRESSIVE` can find out whether the
rules agreed, and an engineer can reconstruct what the ungated system would
have said — which is what makes the gate revisable rather than permanent.

## Consequences

**Positive**

- The band with the worst measured precision cannot be reached by the
  component that measured badly. The 95 false `HIGH_RISK` predictions on UAH
  become at most the 12 the rubric's compound rule fires on.
- The system degrades to something defensible when the model is absent. A
  fresh checkout has no `model.json`, and the rule-only path is not a
  fallback bolted on — it is the same gate with the model term missing.
- The claim is testable as a property rather than a policy:
  `band is HIGH_RISK ⟹ rule_band is HIGH_RISK` holds over every generated
  input in `backend/tests/test_risk_properties.py`.
- `MODEL_ONLY` + `gated` is a countable signal. `TripRiskSummary.
  gated_window_ratio` measures how often the model wanted a band the rules
  refused, which is the data needed to revisit this decision.

**Negative**

- **A genuine `HIGH_RISK` window the rubric misses is capped at
  `AGGRESSIVE`.** The gate trades recall on the severest class for precision,
  deliberately, and the recall it trades away is not measured — nobody knows
  the rubric's own accuracy (model card, "Known next steps" #3). This is the
  real cost and it is not small.
- **The ceiling is the rubric's ceiling.** The engine can be no better on
  `HIGH_RISK` than a decision list of ten hand-set thresholds. Improving the
  model does not lift it; only improving the rules, or removing the gate,
  does.
- Two sources can disagree, and the disagreement has to be presented rather
  than resolved. `DISAGREEMENT_PENALTY` reduces confidence when they do, which
  is an admission, not a resolution.

## When this should be revisited

The gate exists because of one number. It should be removed or loosened when
that number moves:

> `HIGH_RISK` precision on a real-telemetry corpus the rubric did not
> calibrate against reaches a level where the model's false positives cost
> less than the rubric's false negatives.

Model card "Known next steps" #1 — recalibrating the decision threshold
against real data — is the cheapest route there, and is explicitly the highest
value item M8 identified. Until then, `RISK_ENGINE_VERSION` is stamped on every
stored assessment so a re-scored trip is distinguishable from a re-driven one.

## Alternatives considered

**Take the model's `argmax` and publish it.** Rejected on the measurement.
Nine of ten `HIGH_RISK` predictions wrong, and one window in six of an
ordinary trip flagged, is a system users learn to ignore. Shipping it and
calling the number "experimental" would move the cost onto the reader of a
dashboard, who has no way to apply the discount.

**Tune the model's probability threshold instead of gating.** This is the
right eventual fix and is recorded as such above. It is not available now: it
needs a calibration corpus the project does not have, and the model card is
explicit that `HIGH_RISK` recall of 0.625 rests on sixteen windows — too few
to fit an operating point to without overfitting the tuning set.

**Rules only; drop the model from the risk path.** Rejected. The rubric is
also unvalidated, it is a hard-threshold decision list that classifies a
window a hair over a cutoff differently from its neighbour, and the model
recovers script intent slightly *better* than the rubric it was trained on
(0.665 vs 0.639 macro-F1). Discarding it would lose the smoothing that gives
the score its continuity, and would leave the engine with four possible
outputs instead of a scale.

**Average the two sources into one number.** Rejected as unaccountable. An
average of a calibrated-ish probability and a threshold indicator is a
quantity with no units and no failure mode anyone can describe, and it would
make `provenance` impossible to state — the thing that makes this design
auditable is that every band traces to a source.

**Gate every band, not just the top one.** Rejected as too strong. The model's
`AGGRESSIVE`/`NORMAL` boundary is where the surviving severity ordering does
its work, and requiring rule agreement there would discard it. The gate is
placed at exactly the band whose precision was measured and found wanting.
