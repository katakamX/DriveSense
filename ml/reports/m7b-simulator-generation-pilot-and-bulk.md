# M7b — Simulator profile drives: pilot and bulk generation

Covers the M7→M8 bridge work: four scripted driving profiles, a pilot to
check the rubric agrees with each script's intent, and bulk generation of
the training corpus. Nothing here is committed — the working tree is left
for review (see TODO at the end).

Generated artefacts (all gitignored under `data/**`):
`data/recordings/` (74 new JSONL + meta pairs), `data/processed/features_sim_v1.parquet`
(828 windows), `data/processed/features_uah_v1.parquet` (1,709 windows, regenerated
so its now-populated `rubric_label` column matches).

---

## 1. THE HEADLINE: simulator and UAH are not on the same scale

**The training corpus is not validated against real-world scale, and this
report does not claim it is.** Per the standing instruction, neither
`app/core/features/` nor `rubric.py` was altered to compensate.

Absolute-max comparison across the two corpora (1,709 UAH windows vs 827 sim):

| feature | sim p50 | sim abs-max | UAH p50 | UAH abs-max | ratio (abs-max) |
|---|---|---|---|---|---|
| `harsh_braking_per_min` | 0.000 | **108.361** | 0.000 | 30.120 | **3.60×** |
| `speed_cv` | 0.040 | **1.028** | 0.029 | 0.287 | **3.59×** |
| `lat_accel_std` | 0.000 | 4.932 | 0.267 | 1.736 | **2.84×** |
| `rapid_accel_per_min` | 0.000 | **36.120** | 0.000 | **0.000** | **∞** |
| `accel_std` | 0.127 | 2.529 | 0.229 | 1.311 | 1.93× |
| `lat_accel_max_abs` | 0.000 | 8.400 | 0.922 | 4.403 | 1.91× |
| `accel_max` | 0.232 | 3.258 | 0.677 | 2.432 | 1.34× |
| `accel_min` | −0.274 | −6.566 | −0.765 | −6.463 | 1.02× |
| `jerk_std` | 0.757 | 6.263 | 2.284 | 6.778 | 0.92× |

Three findings, in order of how much they matter:

**(a) `rapid_accel_per_min` is ∞× off — it is identically zero on UAH and
reaches 36.1 on the simulator.** This is the single sharpest divergence.
It is also why the recalibrated rubric replaced that rule with
`accel_max>=1.5`: on UAH the feature could never fire. The simulator shows
the feature is not inherently broken — real phone-accelerometer telemetry
simply never sustains +3.0 m/s². Whether a model trained on simulator data
should use a feature the validation set cannot express is a **judgment call
left open** (TODO 1).

**(b) `harsh_braking_per_min` differs 3.6× at the max, and far more in
character.** UAH is nonzero in only 1.3% of windows; the simulator's
HIGH_RISK profile averages ~60/min. Root cause is not the vehicle model but
the detector: `app.core.events.detectors.detect_harsh_braking` emits one
event **per frame** below −3.5 m/s², so at 10 Hz a single 1-second brake
application is already 20 events/min. Clean simulator physics holds a
deceleration steadily; a noisy phone accelerometer dips below the line for
one or two isolated samples. The same physical event is counted an order of
magnitude apart between the two corpora. **The rubric's `>=6.0` cutoff
therefore does not mean the same thing on the two corpora** — this is the
most consequential item in this report (TODO 2).

**(c) Medians tell the opposite story to maxima.** Sim `p50` is *lower* than
UAH `p50` on `accel_std` (0.127 vs 0.229), `accel_max` (0.232 vs 0.677) and
`jerk_std` (0.757 vs 2.284). The simulator is *smoother than real driving
most of the time and more extreme at the tails* — exactly what a clean
physics model with scripted inputs would produce. It is not uniformly "5×
hotter"; it has a different distribution shape. A model trained on it may
learn tail behaviour that real telemetry never shows and miss the
persistent low-level noise that real telemetry always shows.

Per the decision rule given: nothing was rescaled, Phase 2 proceeded anyway,
and the distributions are now on record.

---

## 2. Pilot: rubric label vs script intent

Four pilot recordings (one per profile, variant `a`), featurised and passed
through `label_window_with_reason`. **Two real script bugs were found and
fixed before bulk generation**, which is what the pilot was for:

- **CALM and NORMAL drives never exceeded ~14 kph.** The original gentle
  launch throttles (0.30–0.42) could not pull this tall-geared car up to
  road speed; by 4th/5th the engine was bogged below 1200 rpm. The windows
  *were* labelled CALM — correctly, for a car crawling at walking pace —
  which would have produced a training set whose CALM class meant "barely
  moving" rather than "driving calmly". Fixed by raising launch throttle and
  documenting why in `_launch`'s docstring.
- **AGGRESSIVE saturated the tyre-grip limit.** `lat_accel_max_abs` sat at
  exactly 8.400 = `max_lateral_accel_ms2`, i.e. every corner was at the
  limit of adhesion, and `speeding_time_ratio` averaged 0.64, so 6 of 8
  windows tripped the HIGH_RISK compound rule instead. Fixed by reducing
  steering (0.45→0.10) and capping cruise speed below the 105 kph line.

Final pilot (v5, 45 windows), rubric label vs intent:

| intent | CALM | NORMAL | AGGRESSIVE | HIGH_RISK | match |
|---|---|---|---|---|---|
| CALM | **10** | 2 | 1 | 0 | 77% |
| NORMAL | 4 | **13** | 0 | 0 | 76% |
| AGGRESSIVE | 0 | 0 | **8** | 0 | 100% |
| HIGH_RISK | 0 | 0 | 1 | **6** | 86% |

82% overall. Judged good enough to proceed.

---

## 3. Bulk generation

`ml/pipelines/generate_sim_recordings.py` loops profile × variant × seed and
drives the simulator's headless entry point as a subprocess. **74 recordings,
0 failures.** Seeds vary `sensor_noise_seed` only — identical physics,
different measurement noise — so behavioural variety comes from the 13
hand-authored script variants, not from the seed axis.

| profile | variants | seeds each | recordings | windows |
|---|---|---|---|---|
| calm | a, b, c | 6 | 18 | 258 |
| normal | a, b, c | 6 | 18 | 300 |
| aggressive | a, b, c | 6 | 18 | 144 |
| high_risk | a, b, c, **d** | 5 | 20 | 125 |
| **total** | 13 | — | **74** | **827** |

HIGH_RISK gets a fourth variant deliberately — it is the rarest class in
real driving, so leaving its share to chance would under-represent exactly
the class the model most needs examples of.

**Intent vs rubric label across the full corpus** (827 windows, excluding
the pre-existing `sim-demo` recording):

| intent | CALM | NORMAL | AGGRESSIVE | HIGH_RISK | total | match |
|---|---|---|---|---|---|---|
| CALM | **174** | 71 | 13 | 0 | 258 | 67.4% |
| NORMAL | 73 | **227** | 0 | 0 | 300 | 75.7% |
| AGGRESSIVE | 0 | 0 | **144** | 0 | 144 | 100.0% |
| HIGH_RISK | 0 | 5 | 20 | **100** | 125 | 80.0% |

**Final class balance** (this is the training set):

| rubric_label | windows | share |
|---|---|---|
| NORMAL | 303 | 36.6% |
| CALM | 247 | 29.9% |
| AGGRESSIVE | 177 | 21.4% |
| HIGH_RISK | 100 | 12.1% |

Reasonably balanced; no class below 12%. Coverage-rejection rate for the sim
corpus: **11.7%** (110 of 938 windows dropped below `coverage_ratio` 0.8) —
higher than UAH's 3.6%, because each recording's final partial window is
short. UAH remains 1,709 kept / 64 rejected.

**Per-variant window counts** (the unit a by-driver-profile split must keep
intact, per ADR 0006) are in `ml/reports/m7-dataset-summary.md`, regenerated
with sim numbers included. Every variant has 5–6 recordings, so a per-trip
split has something to work with on both sides.

The residual CALM↔NORMAL confusion (71 CALM-intent windows → NORMAL, 73
NORMAL-intent → CALM) is the honest hard case: a smooth cruise genuinely is
calm, and the boundary between them is one `speed_cv`/`accel_std` cutoff.
Not treated as a bug.

---

## 4. Deviations from the brief, and why

1. **`featurise.py` rubric wiring did not already exist.** The brief assumed
   it; `rubric_label` was still hardcoded to `None`. Wired per your
   mid-task instruction: `label_window_with_reason(...)[0]`, both corpora,
   no other row-schema change.
2. **Report-side fields added to `CorpusSummary`** (`rubric_label_counts`,
   `variant_window_counts`) plus a `_drive_variant` helper. Needed for the
   per-variant counts you asked for. Not part of the parquet row schema.
3. **Removed a stale note** in `featurise_sim` that still said "labelling
   rubric is not implemented yet".
4. **`test_featurise.py` assertion updated** — it asserted
   `rubric_label is None`, which the wiring makes false. Now asserts the
   value is one of the four classes.
5. **`sim-demo.jsonl` left in place.** It is a pre-existing M2 demo artefact,
   not one of mine; deleting user data was not warranted. It contributes 1
   window to `features_sim_v1.parquet` (828 total vs 827 from the 74 new
   recordings) and is excluded from every intent-match table above, since it
   has no profile intent. See TODO 4.
6. **Drive durations 100–230 s**, slightly under the "2–4 min" band for
   AGGRESSIVE/HIGH_RISK (~110 s). Left as-is: window count per class was
   already adequate and lengthening would have cost another tuning round.
7. **Nothing staged in git.** "Leave everything staged" is ambiguous; the
   hard constraint was do-not-commit, so files are left modified in the
   working tree, unstaged.

---

## 5. TODO — needs your judgment before committing

1. **`rapid_accel_per_min` is unusable on UAH but active in the simulator.**
   Decide whether a model may train on a feature the validation corpus can
   never express. Options: exclude it from the model's feature subset, lower
   `RAPID_ACCELERATION_ACCEL_MS2` (affects live event detection too — a
   backend behaviour change, not just ML), or accept and document.
2. **`harsh_braking_per_min` counts frames, not brake applications.** This
   makes the rubric's `>=6.0` HIGH_RISK cutoff mean "≥3 harsh *frames*
   (~0.3 s)" — mild on the simulator, near-unreachable on UAH. Consider
   whether the detector should coalesce consecutive frames into one event.
   That is a change to `app/core/events/`, which I did not touch. **My ADR
   0006 text and `rubric.py`'s docstring both say "harsh brakes" where they
   mean "harsh-braking frames" — worth correcting whichever way you decide.**
3. **Is 82% intent-match good enough to train on?** The rubric, not the
   script name, is the label of record — so the mismatch is not
   automatically wrong. But if you want script intent to *be* the label,
   that is a different (and much stronger) design than ADR 0006 describes.
4. **`sim-demo` in the training corpus.** One unlabelled-intent window. Drop
   it, or leave it.
5. **Simulator scale mismatch (§1) is unresolved by design.** Before any M8
   metric is published, decide whether cross-corpus validation is meaningful
   given these distributions, or whether the model card should state that
   UAH validation tests generalisation across a *domain gap*, not just
   across unseen data.
6. **`data/recordings/` now holds 75 recordings (~74 new).** Gitignored, so
   nothing to commit — but regenerating is `python -m pipelines.generate_sim_recordings`
   if you want them rebuilt from a clean tree.
