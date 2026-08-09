# ADR 0004 — Feature engineering has exactly one implementation

- **Status:** Accepted
- **Date:** 2026-08-09
- **Milestone:** 1 (decision), 7 (implementation)

## Context

Two places need to turn a window of telemetry into a feature vector: the
offline training pipeline in `ml/`, and online inference in the backend.

Writing these separately is the normal outcome — the training version grows out
of a notebook operating on a DataFrame, the serving version is written later
against a ring buffer. When the two drift, the model sees differently-computed
inputs in production than it saw in training. This is **training/serving skew**,
and it is silent: no error is raised, accuracy simply degrades in ways that do
not reproduce offline.

## Decision

Feature engineering lives in **one module**, imported by both paths. The
training pipeline depends on the backend package rather than reimplementing it.

Two guarantees enforce this:

1. The feature computation accepts a plain sequence of telemetry records, so it
   has no dependency on either the ring buffer or pandas.
2. A CI test asserts that a fixed telemetry fixture produces an **identical
   feature vector**, in identical order, through the training call path and the
   inference call path.

Additionally, the persisted model artefact records its ordered feature-name
list, and inference refuses to load a model whose feature names do not match
the code's current output.

## Consequences

**Positive**

- Training/serving skew becomes a test failure rather than a silent regression.
- Feature ordering — an easy and invisible way to corrupt a tree model's
  input — is checked mechanically.
- Adding a feature is a single edit rather than two edits that must agree.

**Negative**

- `ml/` takes a dependency on the backend package, which couples the two.
  Accepted deliberately: the coupling is real, and making it explicit is
  better than reproducing it by hand. If it becomes awkward, the shared code
  extracts cleanly into its own package because it is already dependency-free.

## Alternatives considered

**Duplicate implementations kept in sync by discipline.** Rejected. This is
the single most common way ML projects produce numbers that do not survive
contact with production.
