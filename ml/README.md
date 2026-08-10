# ml/ — Offline machine-learning pipeline (Milestones 7–8)

```
raw → clean → window (30 s, 50% overlap) → featurise → label (rubric)
    → split BY TRIP AND DRIVER PROFILE → train → evaluate → artefact
```

Feature engineering is **not implemented here**. It is imported from the
backend so that training and inference share one implementation — see
[ADR 0004](../docs/adr/0004-shared-feature-engineering.md).

## Running it

```
python -m pipelines.fetch_uah                 # UAH-DriveSet, pinned by digest
python -m pipelines.generate_sim_recordings   # 74 scripted simulator drives
python -m pipelines.featurise                 # -> data/processed/features_*.parquet
python -m pipelines.split                     # -> configs/fold_manifest_v1.json
python -m pipelines.train                     # -> artifacts/, reports/m8-evaluation.md
python -m pipelines.evaluate                  # score a saved model.json, no retraining
```

## Contents

- `pipelines/` — the stages above, each runnable and testable in isolation
- `configs/` — training configuration (`train_v1.yaml`) and the committed fold
  manifest, versioned
- `artifacts/` — `model.json` plus `metadata.json` recording ordered feature
  names, training date, dataset hash, git SHA and full metrics (gitignored)
- `reports/` — dataset summary and M8 evaluation: confusion matrices,
  per-class metrics (committed)
- `notebooks/` — exploration only; never imported by application code

## The split is by script variant, not by recording

`docs/architecture.md` requires splits by trip and driver profile. The group
this pipeline actually uses is stricter — the **script variant**
(`aggressive-b`) — because the six recordings of one variant differ only in
`sensor_noise_seed`: identical physics, identical authored driving, different
measurement noise. A per-recording split would satisfy the letter of the rule
and leak anyway. Leave-one-variant-out 3-fold cross-validation rotates every
variant through the test position exactly once; `tests/test_split.py` asserts
the leak guard.

## Baselines

Reported alongside the model: majority class, logistic regression, and the
labelling rubric itself (scored against script intent, since scoring it
against its own labels returns 1.000 by construction). A model that cannot
beat logistic regression is a finding worth reporting, not hiding.

**M8 produced exactly such a finding, in both directions.** A decision tree
beat the logistic regression on every simulator fold (macro-F1 0.944 vs
0.843) — and then predicted `HIGH_RISK` zero times across 1,709 windows of
real UAH telemetry. Neither model beats a majority-class baseline on real
data. See [`reports/m8-evaluation.md`](reports/m8-evaluation.md) and the
[model card](../docs/model-card.md); the headline is in section 0 of the
report, not buried at the end.

## The artefact is JSON, not a pickle

`model.json` is a hand-written coefficient dump (`pipelines/artifact.py`): the
standardiser's mean and scale, one coefficient row per class, and the decision
rule written out in the file. It is inspectable, carries no code-execution
surface for `backend/app/ml` to load, and does not embed scikit-learn's object
graph — so a scikit-learn upgrade cannot silently change what a committed
artefact predicts. Its round-trip against the fitted pipeline is asserted at
training time and in `tests/test_train.py`.
