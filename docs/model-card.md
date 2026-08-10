# Model card — DriveSense behaviour classifier v1

- **Milestone:** 8
- **Date:** 2026-08-10
- **Artefact:** `ml/artifacts/model.json` (gitignored; regenerate with
  `python -m pipelines.train`)
- **Full metrics:** [`ml/reports/m8-evaluation.md`](../ml/reports/m8-evaluation.md)
- **Status:** **Not fit for production use.** It does not beat a
  majority-class baseline on real telemetry. See "Bottom line" below.

## Bottom line, before anything else

On held-out simulator drives this model scores macro-F1 **0.843 ± 0.079**.
On 1,709 windows of real UAH-DriveSet telemetry it scores **0.302 accuracy
against a 0.650 majority-class baseline** — that is, worse than answering
`NORMAL` to everything.

That number is the model card's headline, not a caveat buried under the good
one. A model trained only on scripted simulator drives has not been shown to
transfer to real driving, and nothing in this document should be read as
claiming otherwise. `ml/README.md` asks for exactly this to be reported rather
than hidden.

## What it does

Classifies one 30-second telemetry window into one of four behaviour classes —
`CALM`, `NORMAL`, `AGGRESSIVE`, `HIGH_RISK` — from 25 numeric features derived
from speed and acceleration.

**Model:** multinomial logistic regression (softmax) over standardised
features, `class_weight="balanced"`, L2 penalty, `C=1.0`. Fitted with
scikit-learn; shipped as an explicit coefficient dump in JSON, so the runtime
that loads it neither unpickles anything nor depends on scikit-learn.

**Inputs:** 25 of the 26 shared features in `app.core.features.FEATURE_NAMES`
(ADR 0004 — the same implementation training and inference both use). One
feature is deliberately excluded; see the next section.

**Outputs:** one of the four class labels, plus a probability per class.

## The deliberate feature exclusion

**`rapid_accel_per_min` is excluded from the model's inputs.** 25 features,
not 26.

The reason is measured, not stylistic. Across all 1,709 UAH validation windows
this feature is **identically 0.0** — at every percentile, at every maximum,
for every label. On the simulator it reaches 36.1/min. The underlying
threshold (`RAPID_ACCELERATION_ACCEL_MS2 = 3.0` m/s²) is simply never crossed
by real phone-accelerometer telemetry in this corpus, while clean simulator
physics crosses it routinely (M7b report, finding (a)).

A feature like that is worse than useless: it is a channel through which the
model can learn something that is true of the simulator and false of the
world, then score well on simulator folds and lose exactly that much on real
data. Excluding it does not fix the domain gap — the results above show it did
not — but it removes the single sharpest known instance of it.

Two alternatives were rejected. Lowering the 3.0 m/s² threshold would change
live event detection in `app.core.events`, a backend behaviour change well
outside a training decision. Keeping the feature and documenting it would have
left the model free to use it anyway.

The exclusion and this reason travel inside `model.json` itself
(`excluded_features`), not only in this document, so an artefact separated from
its paperwork still carries the decision.

## Training data, and what the labels are

**827 windows from 74 scripted simulator recordings**, across 13 authored
script variants (three or four per class). Class balance: `NORMAL` 36.6%,
`CALM` 29.9%, `AGGRESSIVE` 21.4%, `HIGH_RISK` 12.1%.

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
| rubric (the labeller itself) | 0.780 | 0.807 |
| this model (out-of-fold) | 0.758 | 0.772 |
| decision tree (out-of-fold) | 0.788 | 0.805 |

The model recovers intent slightly less well than the rubric it was trained
on, which is the expected direction: it can only inherit what the labeller
encoded, minus what the fit loses. Intent is itself a per-*recording* label
applied to every window inside it, so it is not ground truth either — the idle
windows at the start of an aggressive drive are not aggressive.

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
different claims, and section 7 of the evaluation report is where the second
one was tested and failed. Three or four scripts per class is also a very
small population to rotate through — the fold-to-fold spread reported beside
every mean is the honest width of these numbers, and on `AGGRESSIVE` recall it
is ±0.291, which is most of the interval.

### Cross-validated results (mean ± sd over 3 folds)

| model | accuracy | majority baseline | macro-F1 | balanced acc. | HIGH_RISK recall |
| --- | --- | --- | --- | --- | --- |
| majority-class baseline | 0.294 ± 0.049 | 0.294 ± 0.049 | 0.113 ± 0.015 | 0.250 ± 0.000 | 0.000 ± 0.000 |
| **logistic regression (shipped)** | 0.824 ± 0.058 | 0.294 ± 0.049 | **0.843 ± 0.079** | 0.851 ± 0.083 | 0.939 ± 0.086 |
| decision tree (comparison) | 0.944 ± 0.024 | 0.294 ± 0.049 | 0.944 ± 0.019 | 0.956 ± 0.013 | 1.000 ± 0.000 |

Per class, shipped model:

| class | precision | recall | F1 | support |
| --- | --- | --- | --- | --- |
| AGGRESSIVE | 0.896 ± 0.147 | 0.746 ± 0.291 | 0.800 ± 0.246 | 177 |
| CALM | 0.764 ± 0.125 | 0.945 ± 0.070 | 0.834 ± 0.069 | 247 |
| HIGH_RISK | 1.000 ± 0.000 | 0.939 ± 0.086 | 0.967 ± 0.047 | 100 |
| NORMAL | 0.797 ± 0.131 | 0.773 ± 0.094 | 0.773 ± 0.067 | 303 |

**Macro-F1 is the headline metric, not accuracy.** With one class at 37% of
the training corpus and 65% of the validation corpus, accuracy largely
measures class balance; it is reported only alongside the majority-class
baseline it must beat.

### Real-telemetry validation (UAH-DriveSet, 1,709 windows)

| model | accuracy | majority baseline | macro-F1 | balanced acc. | HIGH_RISK recall |
| --- | --- | --- | --- | --- | --- |
| **logistic regression (shipped)** | 0.302 | 0.650 | 0.290 | 0.507 | 1.000 |
| decision tree (comparison) | 0.539 | 0.650 | 0.385 | 0.458 | **0.000** |

Neither model beats the baseline. The failure modes differ, and the difference
is the most useful thing M8 learned:

- The **shipped logistic regression over-predicts risk**. It recovers all 16
  `HIGH_RISK` windows (recall 1.000) but predicts that class 321 times —
  precision 0.050. Roughly two-thirds of windows from trips UAH itself labelled
  `normal` are predicted `AGGRESSIVE` or `HIGH_RISK`.
- The **decision tree goes silent**. It won every simulator fold and had
  perfect `HIGH_RISK` recall there, then predicted `HIGH_RISK` **zero times**
  across all 1,709 real windows.

That contrast is why the tree is not shipped despite winning in-domain by 0.10
macro-F1. `model.json`'s coefficient format could not carry a tree anyway, but
the better reason is that a model which degrades loudly is safer than one that
degrades silently on the class that matters most.

One genuine positive: the severity *ordering* survives. Windows from trips UAH
labelled `aggressive` draw a `HIGH_RISK` prediction 45.1% of the time, against
12.8% for `normal` and 11.1% for `drowsy` trips. The model has not inverted the
problem; its threshold is in the wrong place.

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
2. **It is a domain gap, not merely unseen data.** M7b measured it directly:
   the simulator is *smoother than real driving at the median and more extreme
   at the tails* — `accel_std` median 0.127 vs UAH's 0.229, but absolute
   maximum 2.529 vs 1.311; `speed_cv` maximum 3.6× higher; `lat_accel_std`
   2.8×. Two differently-shaped distributions, not two samples of one. A model
   trained on the tails of a clean physics model meets a corpus whose signal is
   persistent low-level noise it never saw.
3. **`HIGH_RISK` is 16 windows on UAH** (0.9%), against 12.1% in training. Any
   per-class figure over sixteen windows carries an interval wide enough to
   swallow the conclusion.

**What cross-validation does not prove here.** Rotating variants through the
test position estimates generalisation to unseen *scripts*. The UAH result
demonstrates concretely that this is a weak predictor of generalisation to
unseen *driving* — the tree scored 0.944 on the first and 0.000 `HIGH_RISK`
recall on the second. Read the cross-validated numbers as an upper bound on
in-domain behaviour, never as an estimate of field performance.

## Intended use, and uses to avoid

**Appropriate now:** as the ML path in `backend/app/ml` behind the rule-based
fallback, for development and demonstration; as a baseline for M8+ work to
beat; as evidence in this repository's own methodology discussion.

**Not appropriate:** any decision about a real driver — insurance pricing,
employment, driver scoring, enforcement, coaching presented as authoritative.
The model does not beat "always guess `NORMAL`" on real telemetry, and its
labels were never validated against human judgement of driving behaviour.

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

1. **Close or characterise the domain gap.** The training corpus is the
   problem, not the estimator — no hyperparameter fixes a 0.30-vs-0.65 result.
   Adding realistic sensor noise to the simulator, or training on real
   telemetry with rubric labels while holding out a different real corpus, are
   the two obvious directions.
2. **Recalibrate the decision threshold against real data.** Severity ordering
   survives transfer; the operating point does not. That is a smaller problem
   than it looks, and probably the cheapest available improvement.
3. **Validate the rubric against human judgement.** Every metric here is
   agreement with a rule-based labeller of unmeasured accuracy.
4. **Re-examine features beyond `rapid_accel_per_min`.** One feature was
   excluded on a measured simulator/real divergence; M7b found others
   (`speed_cv` 3.6×, `lat_accel_std` 2.8×) that were not acted on.
