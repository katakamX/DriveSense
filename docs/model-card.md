# Model card — DriveSense behaviour classifier v1

- **Milestone:** 8
- **Date:** 2026-08-11 (revised; first issued 2026-08-10)
- **Artefact:** `ml/artifacts/model.json` (gitignored; regenerate with
  `python -m pipelines.train`)
- **Full metrics:** [`ml/reports/m8-evaluation.md`](../ml/reports/m8-evaluation.md)
- **Status:** **Not fit for production use.** It beats a majority-class
  baseline on real telemetry, but at a `HIGH_RISK` precision of 0.105. See
  "Bottom line" below.

## Bottom line, before anything else

On held-out simulator drives this model scores macro-F1 **0.922 ± 0.016**. On
1,709 windows of real UAH-DriveSet telemetry it scores **0.520 accuracy and
0.451 macro-F1, against a 0.214 majority-class baseline** — better than
guessing, and a long way from usable.

The single number that says how far: `HIGH_RISK` **precision 0.105**. The
model recovers 10 of UAH's 16 high-risk windows by predicting the class 95
times. That is not a threshold that can be tuned into shape from here; it is
a model that has learned roughly the right ordering and none of the right
operating point.

**This section previously read the opposite way, and the correction is part
of the record.** The first M8 run scored 0.302 accuracy against a 0.650
baseline — worse than answering `NORMAL` to everything. Investigating why
found the cause in the training corpus rather than the estimator: the
scripted simulator drives cruised at ~50 kph against UAH's 91.5 kph median
and never steered, leaving four lateral features exactly 0.000 in 58% of
simulator windows and 0% of real ones. `drivesense_sim.drives` was
recalibrated against measured real-driving figures and the corpus
regenerated; these numbers are from that corpus. What changed was the
training data, not the model, the features or the rubric — and the earlier
result was a true measurement of a corpus that had a defect in it, which is
why it is quoted here rather than deleted.

`ml/README.md` asks for results to be reported rather than hidden. That
applies to a result that improves, too: nothing below should be read as
claiming this model has been shown to work on real driving.

## What it does

Classifies one 30-second telemetry window into one of four behaviour classes —
`CALM`, `NORMAL`, `AGGRESSIVE`, `HIGH_RISK` — from 25 numeric features derived
from speed and acceleration.

**Model:** multinomial logistic regression (softmax) over standardised
features, `class_weight="balanced"`, L2 penalty, `C=1.0`. Fitted with
scikit-learn; shipped as an explicit coefficient dump in JSON, so the runtime
that loads it neither unpickles anything nor depends on scikit-learn.

**Inputs:** 22 of the 26 shared features in `app.core.features.FEATURE_NAMES`
(ADR 0004 — the same implementation training and inference both use). Four
features are deliberately excluded; see the next section.

**Outputs:** one of the four class labels, plus a probability per class.

## The deliberate feature exclusions

**Four features are excluded from the model's inputs.** 22 features, not 26.
All four fail the same test: the feature is dead or near-dead on the real
validation corpus while varying freely in the simulator, making it a channel
through which the model can learn something true of the simulator and false of
the world — scoring well on simulator folds and losing exactly that much on
real data.

| feature | on UAH (1,709 windows) | on the simulator |
| --- | --- | --- |
| `rapid_accel_per_min` | identically 0.000, 1 distinct value | 2 distinct values, max 2.007/min |
| `stop_ratio` | identically 0.000, 1 distinct value | 13 distinct values, 80 non-zero windows |
| `lat_accel_time_ratio` | zero in 98.4% of windows | zero in 86.3% |
| `harsh_braking_per_min` | zero in 99.2% (14 non-zero windows) | zero in 85.9%, far larger magnitudes |

The first two are the clearest cases: a column that is a literal constant on
the validation corpus can be learned from and can never generalise. The
underlying thresholds are simply never crossed by real phone-accelerometer
telemetry in this corpus — `RAPID_ACCELERATION_ACCEL_MS2 = 3.0` m/s² is never
sustained, and UAH-DriveSet is entirely motorway and secondary driving so no
window drops below the 3 kph stop line. `lat_accel_time_ratio` is near-dead on
*both* sides, contributing noise rather than signal; the cornering behaviour it
was meant to capture is carried by `lat_accel_std` and `lat_accel_max_abs`,
which are non-zero in every window of both corpora.

**`harsh_braking_per_min` is excluded from the model but still used by the
labelling rubric, and that is deliberate rather than an inconsistency.** The
rubric (`AGGRESSIVE_HARSH_BRAKING_PER_MIN = 2.0`) is a human-authored decision
list read by people, where one brake application in 30 s is meaningful evidence
on the handful of windows that have it. The model is a fitted function that
would treat the same near-constant column as a free simulator-vs-real
discriminator. Same feature, two consumers, two appropriate treatments.

Excluding these does not fix the domain gap — the results above show it did not
— but it removes the sharpest known instances of it. Two alternatives were
rejected. Lowering the detection thresholds would change live event detection in
`app.core.events`, a backend behaviour change well outside a training decision.
Keeping the features and documenting them would have left the model free to use
them anyway.

The exclusions and their reasons travel inside `model.json` itself
(`excluded_features`), not only in this document, so an artefact separated from
its paperwork still carries the decision.

## Training data, and what the labels are

**1,135 windows from 74 scripted simulator recordings**, across 13 authored
script variants (three or four per class). Class balance: `AGGRESSIVE` 34.4%,
`NORMAL` 30.3%, `CALM` 21.1%, `HIGH_RISK` 14.1%.

**Labels are weak supervision, not ground truth.** They come from a
deterministic rule-based rubric (`ml/pipelines/labeling/rubric.py`,
[ADR 0006](adr/0006-training-label-rubric.md)) applied to feature windows —
ten hand-set thresholds in a decision list, each rule named so that any label
reduces to one checkable reason. No human annotated these windows.

This matters in a specific way that is easy to lose: **the model's ceiling is
the rubric's accuracy, and the rubric's accuracy is not known.** A rule-based
labeller is wrong in ways a human would not be, and every metric in the
evaluation report measures agreement with the rubric, not agreement with
reality. The one partial exception is the script-intent comparison below.

`sim-demo`, a pre-existing demo recording with no scripted intent, is excluded
entirely (1 window).

### Agreement with script intent

Each simulator drive was *authored* to produce a class. Scored against that
intent — the only non-circular check available on simulator data, since
scoring the rubric against its own labels would return 1.000 by construction:

| | accuracy | macro-F1 |
| --- | --- | --- |
| rubric (the labeller itself) | 0.622 | 0.639 |
| this model (out-of-fold) | 0.652 | 0.665 |
| decision tree (out-of-fold) | 0.601 | 0.621 |

**The model recovers intent slightly better than the rubric it was trained on,
which is the wrong direction and is flagged rather than claimed as a win.** It
can only inherit what the labeller encoded, minus what the fit loses, so a
higher score wants an explanation. The benign one is that the rubric is a
hard-threshold decision list — a window a hair over one cutoff is labelled
differently from its neighbour, while a fitted model smooths across that
boundary and can land nearer the authored intent. The one that would matter is
a leak: `recording_id` determines intent, so any feature encoding which
recording a window came from would produce this. At 0.025 macro-F1 over 13
variants neither reading is established; `m8-evaluation.md` section 5 states
it the same way.

Intent is itself a per-*recording* label applied to every window inside it, so
it is not ground truth either — the idle windows at the start of an aggressive
drive are not aggressive.

## Evaluation

### What the split does, and what it does not prove

**Leave-one-variant-out grouped 3-fold cross-validation.** The group is the
*script variant*, not the recording. This matters: the six recordings of one
variant differ only in `sensor_noise_seed` — identical physics, identical
authored driving, different measurement noise. Splitting by recording would
have put two near-copies of one drive on opposite sides of the split and
called the result generalisation. Every variant is held out in exactly one
fold, so the folds partition the corpus and every window has exactly one
out-of-fold prediction. `ml/tests/test_split.py` asserts the leak guard.

**What it proves:** the model generalises from some authored scripts to other
authored scripts it has not seen.

**What it does not prove:** that it generalises to real driving. Those are
different claims, and section 7 of the evaluation report is where the second is
tested — it is passed only in the weak sense of beating a baseline. Three or
four scripts per class is also a very small population to rotate through: the
fold-to-fold spread reported beside every mean is the honest width of these
numbers, and `HIGH_RISK`'s perfect in-domain recall rests on four authored
drives.

### Cross-validated results (mean ± sd over 3 folds)

| model | accuracy | majority baseline | macro-F1 | balanced acc. | HIGH_RISK recall |
| --- | --- | --- | --- | --- | --- |
| majority-class baseline | 0.345 ± 0.026 | 0.345 ± 0.026 | 0.128 ± 0.007 | 0.250 ± 0.000 | 0.000 ± 0.000 |
| **logistic regression (shipped)** | 0.917 ± 0.014 | 0.345 ± 0.026 | **0.922 ± 0.016** | 0.927 ± 0.019 | 1.000 ± 0.000 |
| decision tree (comparison) | 0.905 ± 0.037 | 0.345 ± 0.026 | 0.915 ± 0.028 | 0.913 ± 0.031 | 0.952 ± 0.067 |

Per class, shipped model:

| class | precision | recall | F1 | support |
| --- | --- | --- | --- | --- |
| AGGRESSIVE | 0.986 ± 0.020 | 0.944 ± 0.010 | 0.964 ± 0.015 | 391 |
| CALM | 0.847 ± 0.065 | 0.877 ± 0.102 | 0.857 ± 0.054 | 240 |
| HIGH_RISK | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 160 |
| NORMAL | 0.853 ± 0.047 | 0.885 ± 0.047 | 0.866 ± 0.013 | 344 |

**Macro-F1 is the headline metric, not accuracy.** With one class at 34% of the
training corpus and 65% of the validation corpus, accuracy largely measures
class balance; it is reported only alongside the majority-class baseline it must
beat. Note that the baseline is the majority class *of the training corpus* —
the only class an always-guess model could know — which is why the UAH baseline
below is 0.214 rather than UAH's own 65% `NORMAL` share.

### Real-telemetry validation (UAH-DriveSet, 1,709 windows)

| model | accuracy | majority baseline | macro-F1 | balanced acc. | HIGH_RISK recall |
| --- | --- | --- | --- | --- | --- |
| **logistic regression (shipped)** | 0.520 | 0.214 | **0.451** | 0.657 | 0.625 |
| decision tree (comparison) | 0.518 | 0.214 | 0.393 | 0.418 | **0.062** |

Both models beat the baseline. The failure modes still differ, and the
difference is the most useful thing M8 learned:

- The **shipped logistic regression over-predicts risk**. It recovers 10 of the
  16 `HIGH_RISK` windows (recall 0.625) but predicts that class 95 times —
  precision 0.105. `CALM` is worse in the same direction: recall 0.944 at
  precision 0.255, from 799 predictions against 216 actual windows. 16.0% of
  windows from trips UAH itself labelled `normal` are predicted `AGGRESSIVE` or
  `HIGH_RISK`.
- The **decision tree goes nearly silent** on the class that matters. It
  recovers 1 of 16 `HIGH_RISK` windows (recall 0.062) — down from perfect recall
  in-domain — and its balanced accuracy (0.418) falls below the baseline's own
  structure even as its raw accuracy clears it.

That contrast is why the tree is not shipped, despite the two being within 0.007
macro-F1 in-domain. `model.json`'s coefficient format could not carry a tree
anyway, but the better reason is that a model which degrades loudly is safer
than one that degrades silently on the class that matters most.

One genuine positive: the severity *ordering* survives. Windows from trips UAH
labelled `aggressive` are predicted `AGGRESSIVE` or `HIGH_RISK` 65.9% of the
time, against 16.0% for `normal` and 17.9% for `drowsy` trips. The model has not
inverted the problem; its threshold is in the wrong place, and the 16.0% floor is
where "wrong place" becomes "not usable".

## What this evaluation is not

Three things stand between the UAH figure and the phrase "held-out test set",
and all three are load-bearing:

1. **The yardstick was shaped by what it measures.** The UAH evaluation scores
   predictions against `rubric_label`, and ADR 0006 records that ten of the
   rubric's hand-set thresholds were calibrated, once, by a human reading
   UAH's own feature percentile distributions. The narrow guarantee holds
   exactly as stated: UAH's *own labels* never trained or scored any model,
   and **no UAH row has ever been in the training parquet**. But "the rubric
   never saw UAH data" would be false, and this card does not claim it.
2. **It is a domain gap, not merely unseen data.** Narrowed by the M8
   recalibration, not closed (M7b section 1b): the simulator's median speed is
   now 84.8 kph against UAH's 91.5, and `accel_std` 0.197 against 0.229, but
   `lat_accel_std` still peaks 2.85× higher and `jerk_std`'s median is 0.835
   against UAH's 2.284. Two differently-shaped distributions, not two samples
   of one. A model trained on clean physics meets a corpus whose signal is
   persistent low-level sensor noise it never saw.
3. **`HIGH_RISK` is 16 windows on UAH** (0.9%), against 14.1% in training. Any
   per-class figure over sixteen windows carries an interval wide enough to
   swallow the conclusion — including the 0.625 recall quoted above.

**What cross-validation does not prove here.** Rotating variants through the
test position estimates generalisation to unseen *scripts*. The UAH result
demonstrates concretely that this is a weak predictor of generalisation to
unseen *driving*: the two models are 0.007 macro-F1 apart in-domain and 0.058
apart out of it, and the tree's `HIGH_RISK` recall goes from 0.952 to 0.062
across that boundary. Read the cross-validated numbers as an upper bound on
in-domain behaviour, never as an estimate of field performance.

## Intended use, and uses to avoid

**Appropriate now:** as the ML path in `backend/app/ml` behind the rule-based
fallback, for development and demonstration; as a baseline for M8+ work to
beat; as evidence in this repository's own methodology discussion.

**Not appropriate:** any decision about a real driver — insurance pricing,
employment, driver scoring, enforcement, coaching presented as authoritative.
On real telemetry the model calls one window in six from an ordinary trip
`AGGRESSIVE` or `HIGH_RISK`, and its labels were never validated against human
judgement of driving behaviour. Beating a majority-class baseline is a
sanity floor, not a fitness bar.

**`HIGH_RISK` measures outcome severity, not intent, and cannot separate their
causes.** A drowsy driver who brakes hard after drifting and a tailgating
driver who brakes hard produce the same features and land in the same class.
ADR 0006 states this as a limitation of a vehicle-telemetry-only rubric;
inheriting it, the model cannot distinguish them either. The UAH cross-tab
shows exactly that: `drowsy`-labelled windows spread across all four classes.

## Reproducing this

```
python -m pipelines.featurise            # both corpora -> data/processed/*.parquet
python -m pipelines.split                # fold assignment -> ml/configs/fold_manifest_v1.json
python -m pipelines.train                # model.json, metadata.json, m8-evaluation.md
```

Configuration is `ml/configs/train_v1.yaml` (seeds, hyperparameters, the
feature exclusion and its reason). The fold assignment is pinned in a committed
manifest and verified against the corpus on every run, so a corpus change fails
training rather than silently producing numbers from a different split.
`ml/artifacts/metadata.json` records the ordered feature names, git SHA,
dataset hash and the complete metrics for the run that produced the artefact.

## Known next steps

The evaluation identifies these; none is done.

1. **Recalibrate the decision threshold against real data.** Now the highest
   value item, and the cheapest. Severity ordering survives transfer; the
   operating point does not. `HIGH_RISK` precision 0.105 at recall 0.625 is a
   curve with room on it — the model is not blind, it is loud.
2. **Close the remaining domain gap, which is now a gap in the tails rather
   than in scale.** M8's recalibration fixed speed and cornering; what remains
   is that clean physics produces none of the persistent low-level sensor noise
   real telemetry always has (`jerk_std` median 0.835 vs 2.284). Adding
   realistic sensor noise to the simulator is the direct attack; training on
   real telemetry with rubric labels while holding out a different real corpus
   is the alternative.
3. **Validate the rubric against human judgement.** Every metric here is
   agreement with a rule-based labeller of unmeasured accuracy. Unchanged from
   the first issue of this card and still the ceiling on everything above.
4. **Check the intent result for a leak.** The model scores 0.025 macro-F1
   above the rubric it was trained on when both are scored against script
   intent. Probably benign; not established.
5. **Re-examine the four excluded features after any further simulator work.**
   Two of them (`rapid_accel_per_min`, `stop_ratio`) are constants on UAH and
   no simulator change can revive them, but the exclusion list was re-measured
   once and should be re-measured again rather than inherited.
