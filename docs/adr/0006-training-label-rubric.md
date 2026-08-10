# ADR 0006 — Training labels come from a rubric over simulator windows, not UAH's own labels

- **Status:** Accepted
- **Date:** 2026-08-10
- **Milestone:** 7 (decision), 8 (training)
- **Amended:** 2026-08-10 — the rubric's numeric cutoffs were recalibrated
  against UAH-DriveSet's empirical feature distributions after the original
  thresholds proved miscalibrated against real driving (three of six rules
  never fired; see "UAH-calibrated thresholds" below). This amendment also
  corrects an overclaim in the original text: UAH was not, in fact, left
  fully untouched by the rubric's development.

## Context

Milestone 8 needs labelled windows to train against. UAH-DriveSet already
ships trip-level labels (`NORMAL`/`NORMAL1`/`NORMAL2`/`AGGRESSIVE`/`DROWSY`),
so the shortest path looks like: use those.

That path is wrong on three independent grounds, not one:

1. **Wrong taxonomy.** DriveSense's classes are `CALM`/`NORMAL`/`AGGRESSIVE`/
   `HIGH_RISK` (`docs/architecture.md`). UAH's are a different set entirely —
   `DROWSY` is a driver-state label with no DriveSense equivalent, and there
   is no principled mapping from UAH's three classes onto four different
   ones without inventing the mapping itself, which is just relabelling by
   hand with extra steps.
2. **Wrong granularity.** UAH's labels are per-*trip* (one behaviour for an
   entire 20-40 minute recording). DriveSense trains on 30s windows. Applying
   a trip-level label to every window inside it asserts that a driver who
   was scored `AGGRESSIVE` overall was aggressive for the *entire* trip,
   including the idle windows at the start — visibly false, and it would
   inject the same wrong assumption 1,709 times (one per UAH window in
   `data/processed/features_uah_v1.parquet`).
3. **Wrong role for this dataset.** `docs/architecture.md`'s M7/M8 split
   already made UAH validation-only: "Results are validated against real
   public telemetry the rubric never saw." Training on UAH's labels and then
   validating against UAH data is circular — it cannot show the model
   generalises past what it was fitted to, which is the entire point of
   holding UAH out.

There is also no public dataset labelled with DriveSense's own classes (this
is stated directly in `docs/architecture.md`'s "Honest ML methodology"
section), so *some* label source has to be constructed either way.

## Decision

Training labels are produced by a **documented, deterministic rubric**
(`ml/pipelines/labeling/rubric.py`) applied to simulator-generated windows.
This is weak supervision from a rule-based labeller, not human-annotated
ground truth, and the model card states it as such — this ADR does not
relax that framing, it implements the mechanism `docs/architecture.md`
already committed to.

The rubric is a **decision list**, evaluated `HIGH_RISK` > `AGGRESSIVE` >
`CALM` > `NORMAL` (default), over the same 26 features
(`app.core.features.FEATURE_NAMES`) both training and inference already
share (ADR 0004). Where the numeric thresholds that already define "an
event" in this codebase (`app.core.events.thresholds`:
`HARSH_BRAKING_ACCEL_MS2 = -3.5`, `RAPID_ACCELERATION_ACCEL_MS2 = 3.0`,
`SPEEDING_MARGIN_KPH = 5.0`) held up against real driving data, the rubric
reuses them directly rather than inventing a second, independent set of
numbers. Where they didn't (see "UAH-calibrated thresholds" below), the
cutoff or the underlying feature was replaced with one that does — see the
module docstring for the specific rule-by-rule derivation. Each rule
carries a name; `label_window_with_reason` returns both the label and the
rule that produced it, so "why is this window `AGGRESSIVE`" always has a
one-line, checkable answer instead of resting on an opaque score.

UAH's own labels are not discarded — `uah_label` stays a column in the
Parquet output alongside `rubric_label` (populated for both corpora). Their
role is to let the rubric be *checked* post-hoc, on an ongoing basis: UAH
windows drawn from a trip UAH itself labelled `AGGRESSIVE` should skew
toward rubric `AGGRESSIVE` or `HIGH_RISK` more than windows from a UAH
`NORMAL` trip do. This is a sanity check on the rubric's thresholds, not a
training signal — the model itself never sees `uah_label`, and UAH windows
are never trained on regardless of what `rubric_label` says about them. No
UAH row appears in, or is derived into, the training parquet at any point.

### UAH-calibrated thresholds (a one-time, human-reviewed step)

The paragraph above describes the rubric's steady-state, ongoing relationship
with UAH: a read-only cross-tab check, never a training input. It does not
describe how the rubric's thresholds were originally set, and an earlier
version of this ADR implied — incorrectly — that UAH played no part in that
either. It did, precisely as follows:

1. The first version of the rubric anchored every cutoff to
   `app.core.events.thresholds` and a couple of informal thresholds already
   present in `app.core.features.extract`, without checking whether real
   driving data ever actually crossed them.
2. Running that rubric over the 1,709 already-featurised UAH validation
   windows showed it didn't: several `AGGRESSIVE`/`HIGH_RISK` rules never
   fired at all — most starkly, `rapid_accel_per_min` is 0.0 at its 99th
   percentile *and* its maximum across every UAH window regardless of
   label, so no cutoff on it could ever have fired, and `accel_std >= 1.5`
   exceeded the global UAH maximum of 1.311, making that rule unreachable
   by construction. `CALM` swallowed 70.6% of all windows because its
   cutoffs sat at each label's ~90th percentile instead of below it.
3. Percentile distributions of the relevant features (`accel_std`,
   `accel_max`, `accel_min`, `harsh_braking_per_min`, `speed_cv`,
   `lat_accel_max_abs`, `speeding_time_ratio`), broken out by `uah_label`,
   were computed and reviewed by a human. New cutoffs were proposed from
   that evidence — e.g. `AGGRESSIVE_ACCEL_STD` moved to 0.45, sitting at the
   aggressive-labelled p75 and above the normal-labelled p95 — and one rule
   (`accel_min <= -5.0`) was dropped outright as structurally redundant with
   `harsh_braking_per_min` rather than recalibrated.
4. The proposed numbers were reported, reviewed, and only then committed to
   `rubric.py`. This was a single offline analysis step, not a fitting
   procedure — no optimiser searched for these numbers, no cross-validation
   loop touched them, and the result is eleven hand-set constants (three for
   `HIGH_RISK`, five for `AGGRESSIVE`, three for `CALM`) a human can read and
   re-derive from the percentile tables in the review that produced them.

What this means precisely, so "held out" is stated as narrowly as it is
true: **UAH's per-window labels were never used to train or evaluate any
model, and no UAH row is or has ever been present in the training
parquet.** What UAH *did* inform is the numeric value of a small set of
human-authored, interpretable rule thresholds, in a one-time step, before
any model existed to evaluate. That is a materially different — and
weaker — claim than "the rubric never saw UAH data," and this ADR no
longer states the stronger one.

### Per-trip and per-driver-profile splits (already committed, restated here)

`docs/architecture.md` already requires train/test splits by trip and by
driver profile, never by row — restated here because it is the property
that makes rubric-labelled data usable at all. Consecutive, 50%-overlapping
windows from the same recording are near-duplicates; if two overlapping
windows from one aggressive drive land on opposite sides of a split, the
model is tested on data it has effectively already seen, and reported
accuracy stops measuring anything. Every simulator recording used for
training must therefore be assigned to exactly one side of the split, not
split window-by-window.

### Why simulator-only for training

The simulator is the only source where the *cause* of a window's behaviour
is known and controllable — a scripted `HIGH_RISK` drive is high-risk
because a `ScriptStep` sequence with sustained speeding and late, hard
braking was authored to make it so, not because a rubric guessed it
afterward. That control is what makes bulk labelled data generation
possible at all (`docs/architecture.md`'s `ml/` responsibility already
names "label" as a pipeline stage after simulator-produced windows). UAH
carries no such control — it is real, uncontrolled driving, which is
exactly why it is the right thing to validate against and the wrong thing
to manufacture training labels from.

## Consequences

**Positive**

- The label source is auditable: every label traces to one named rule over
  features that are themselves shared, tested code (ADR 0004), not to a
  human annotator's judgement call or an unexplained trip-level tag.
- UAH's labels are never used to train or evaluate a model, and no UAH row
  enters the training parquet — the M7/M8 validation split's *modelling*
  guarantee holds. (Its numeric feature distributions were used once, by a
  human, to calibrate rule thresholds — see "UAH-calibrated thresholds"
  above. That is a narrower, and true, claim, not the stronger "UAH data
  never touched the rubric at all.")
- Thresholds are anchored to existing, already-justified numbers
  (`app.core.events.thresholds`), so the rubric does not carry a second,
  silently-divergent definition of "harsh braking" alongside the one
  `app.core.events` already owns.

**Negative**

- Weak supervision, stated plainly: a rule-based rubric can be wrong in ways
  a human labeller would not be, and the model card must report this rather
  than presenting rubric labels as ground truth.
- The rubric is only as good as the simulator's scripted drives are
  representative of real driving. A scripted `HIGH_RISK` drive is high-risk
  by construction, which risks the model learning "matches a script" rather
  than "matches risky driving" if drive variety is too narrow — mitigated
  by authoring multiple script variants per class rather than one each, but
  not eliminated by this ADR alone.
- Two label columns (`uah_label`, `rubric_label`) on the same schema is more
  surface area than one; the featurise pipeline must keep straight which
  corpora populate which, and future edits could confuse "validation label"
  with "training label" if the distinction is not kept explicit at read
  time, not just in this document.
- **`HIGH_RISK` measures outcome severity, not driver intent, and cannot
  distinguish their causes.** A drowsy driver who brakes hard because they
  drifted and startled, and an aggressive driver who brakes hard because
  they were following too close, produce the same `harsh_braking_per_min`
  and `accel_min` values and land on the same `HIGH_RISK` rule. On the
  1,709 UAH validation windows this is not hypothetical: `HIGH_RISK` fires
  on UAH `drowsy`-labelled and `aggressive`-labelled windows at
  statistically indistinguishable rates (13 of each, out of 577 and 346
  respectively). This is a stated limitation of a 4-class *behaviour*
  rubric, not a bug: separating drowsiness from aggression as a *cause*
  would need driver-state signal this rubric — built only from vehicle
  telemetry features — does not have access to.

## Alternatives considered

**Map UAH's three labels onto DriveSense's four.** Rejected for the reasons
in Context: wrong granularity (trip vs. window) and circularity (training
and validating on the same dataset) are structural problems a mapping
cannot fix, independent of how the mapping is chosen.

**Hand-label a sample of simulator windows.** More faithful to "ground
truth" in principle, but does not scale to the window counts a training set
needs, and swaps one weak-supervision problem (rubric bias) for another
(annotator consistency and bias) without the auditability a named rule
provides.

**Train directly on rule-based event counts (no ML at all).** Consistent
with the repo's "rule-based heuristics first, ML as stretch goal" stance,
and remains the fallback if the rubric-labelled training set proves too
small or too narrow to beat the logistic-regression baseline
(`ml/README.md`'s stated baselines make this an explicit, reportable
comparison rather than a silent fallback). Not a reason to skip building
the rubric now: the baselines it exists to be compared against need the
same labelled data either way.
