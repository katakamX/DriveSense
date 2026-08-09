# ml/ — Offline machine-learning pipeline (Milestones 7–8)

```
raw → clean → window (30 s, 50% overlap) → featurise → label (rubric)
    → split BY TRIP AND DRIVER PROFILE → train → evaluate → artefact
```

Feature engineering is **not implemented here**. It is imported from the
backend so that training and inference share one implementation — see
[ADR 0004](../docs/adr/0004-shared-feature-engineering.md).

Planned contents:

- `pipelines/` — the stages above, each runnable and testable in isolation
- `configs/` — training configuration, versioned
- `artifacts/` — `model.json` plus `metadata.json` recording ordered feature
  names, training date, dataset hash, git SHA and full metrics (gitignored)
- `reports/` — confusion matrices, per-class metrics, SHAP plots (committed)
- `notebooks/` — exploration only; never imported by application code

Baselines reported alongside the model: majority class, logistic regression,
and the labelling rubric itself. A model that cannot beat logistic regression
is a finding worth reporting, not hiding.
