# Step 4 findings — OBD CSV vs the existing risk engine

**Status: findings only, no decision made, no code written.**

## What the sample file actually contains

`backend/tests/fixtures/sample_obd.csv`, 1780 data rows at a ~0.03s interval
(≈53s of driving). Columns: `Time_s, Speed_kmh, RPM, Gear, Throttle_pct,
Brake_pct, Boost_bar, Req_Fuel_pct, Inj_Fuel_pct, Torque_Nm, Power_HP,
Engine_Stress_pct, Drivetrain_Stress_pct, Clutch_Stress_pct,
Driver_Aggression_pct, Total_Vehicle_Stress_pct`. No lat/lon. No raw
accelerometer channel of any kind — longitudinal or lateral.

Inspecting actual rows (not just the header) shows the two precomputed
columns measure different things:

- **`Driver_Aggression_pct` tracks braking/throttle behaviour.** Its peak in
  this file (39) occurs at row 1324 — `Speed_kmh=14.5` falling fast,
  `Brake_pct=100`, `RPM=382` (near-stall), `Gear=5` (a mismatched high gear
  for that speed — a poorly executed hard stop). `Total_Vehicle_Stress_pct`
  is only 6 at that same row.
- **`Total_Vehicle_Stress_pct` tracks mechanical/drivetrain load, not driver
  behaviour.** Its peak (64) occurs at row 514 — mid-gearshift at high
  throttle (`Throttle_pct=54`, `RPM=3334`, `Clutch_Stress_pct=100`), while
  `Driver_Aggression_pct` is 1 at that same row.

So these are not one signal at two resolutions. They appear to be two
independently-computed axes from whatever generated this fixture (aggression
= how the pedals were used; vehicle stress = how hard the drivetrain worked),
and they visibly disagree on which moments in the drive mattered.

## Whether the existing rule engine (`app/core/risk/rules.py`) applies

`rules.evaluate()` reads exactly 9 keys out of the 26-feature vector:
`harsh_braking_per_min`, `rapid_accel_per_min`, `speeding_time_ratio`,
`accel_min`, `accel_max`, `accel_std`, `lat_accel_max_abs`, `lat_accel_std`,
`speed_cv`. Tracing each back through `app/core/features/extract.py` and
`app/core/events/detectors.py`:

- **7 of the 9 are derivable from `Speed_kmh` alone.** `speed_cv` is a
  straight function of the speed series. `accel_min/max/std`,
  `harsh_braking_per_min`, `rapid_accel_per_min` all reduce to
  longitudinal `accel_ms2`, which `detect_harsh_braking` /
  `detect_rapid_acceleration` / `FrameSample` need as `speed_kph` +
  `accel_ms2` only — no lat/lon. Differentiating `Speed_kmh` over
  `Time_s` (0.03s steps, so noise is a real concern — see below) gives a
  legitimate `accel_ms2`, not a fabricated one. `speeding_time_ratio` just
  compares `speed_kph` against a configured limit
  (`Settings.default_speed_limit_kph`, already used as a fallback
  elsewhere) — again no GPS needed.
- **2 of the 9 have no source signal in this file at all.**
  `lat_accel_max_abs` and `lat_accel_std` need lateral acceleration, which
  in the live pipeline comes from an IMU. This OBD export has no steering
  angle, no yaw rate, no lat/lon to derive heading change from — nothing
  lateral survives in these columns. There is no honest way to compute
  these two features from this file; the only way to "supply" them is to
  hardcode a value (almost certainly 0).

That hardcoding is not neutral. `lat_accel_max_abs >= 2.0` is one of five
independent ways the AGGRESSIVE band fires — pinning it to 0 permanently
disables that rule for every OBD-sourced drive. And CALM's rule is a
five-way conjunction that includes `lat_accel_std <= 0.25` — pinning that to
0 makes the *easiest* possible value for one leg of a conjunction that's
already calibrated assuming lateral data varies with real cornering,
silently loosening CALM's bar for OBD drives relative to GPS/IMU-sourced
ones. Either way the rule engine's output would depend on a value that was
never measured, which is the exact thing this codebase's risk engine is
built to refuse — `RiskAssessment`/`coverage_ratio`/`provenance` exist
precisely so a reader can tell measured from unmeasured, and the
scope-and-honesty section of the README states outright: "missing signals
are never imputed."

**The ML model is a separate, harder blocker.** `score.assess()` only
accepts a `model_output` produced by running the trained artefact over the
same 26-feature vector (`app.ml.predict`), which was trained on UAH-DriveSet
GPS/IMU-shaped features. There is no retraining path in scope here, so
*any* OBD-based analysis is rules-only by construction — `provenance` would
always be `RULES_ONLY`, never `MODEL_AND_RULES_AGREE` / `MODEL_ONLY`,
regardless of what we do with the two missing features.

**`Telemetry` (DB model) agrees with this reading.** `accel_ms2` and
`lateral_accel_ms2` are both non-nullable columns. Storing OBD samples as
real `Telemetry` rows to run through the existing live pipeline unmodified
would require satisfying both NOT NULL constraints — derivable for the
first, not for the second, same gap as above.

**One more real gap, not yet mentioned:** even the 7 "derivable" features
depend on differentiating `Speed_kmh` at a 0.03s step. That step is roughly
3x finer than the 10Hz (0.1s) the live pipeline and `Settings.telemetry_rate_hz`
assume, and naive frame-to-frame differentiation at 0.03s is usually noisy
enough that it needs smoothing before it resembles a real accelerometer
signal — otherwise `accel_std`/`jerk_std` will read high from quantization
noise alone, not from actual harsh driving. This is solvable (resample /
smooth before differentiating) but is real work, not a one-line `diff()`.

## The three-way decision (not made here)

The file already carries `Driver_Aggression_pct` and
`Total_Vehicle_Stress_pct`. Three options, tradeoffs only:

**(a) Display the precomputed columns as-is, alongside the replay.**
- For: Zero risk-engine involvement, so none of the lateral-feature gap
  above matters. Fast to build. The numbers are already per-sample, which
  fits a chunked replay naturally (no windowing math needed).
- Against: These values are provenance-less as far as this codebase's model
  is concerned — we don't know the formula, the calibration, or the
  intended scale behind them, so nothing ties them to this app's
  CALM/NORMAL/AGGRESSIVE/HIGH_RISK vocabulary or its evenly-spaced severity
  scale. Showing them next to a `Badge`/`Trace` built for that vocabulary
  (Phase 2 design work) would visually imply they mean the same thing as a
  live trip's risk band when they structurally can't (different scale,
  different source, no `RiskAssessment` at all). They'd need their own
  presentation, separate from the existing risk-band UI, to not mislead.

**(b) Compute risk independently via new OBD-native rules, ignore the
precomputed columns.**
- For: Produces an actual `RiskAssessment`-shaped result (or something
  compatible with it) using genuinely-measured OBD signals — harsh-braking
  via `Brake_pct` spike-rate, aggression via `Throttle_pct` volatility,
  mismatched-gear/RPM events, etc. Reuses the existing
  CALM/NORMAL/AGGRESSIVE/HIGH_RISK vocabulary honestly, since every input
  would be something this file actually measured.
- Against: This is new rule design and calibration work, not a reuse of
  `rules.py` — none of its 9 thresholds were calibrated against
  RPM/throttle/brake-pct, so the existing cutoffs (e.g. `accel_max >= 1.5`)
  don't transfer; new ones would need their own justification the way the
  current file's comments justify each threshold against UAH data. There is
  no calibration corpus for OBD-style signals in this repo today. Doing
  this properly is a scope well beyond "add an upload control."

**(c) Show both side by side.**
- For: Lets a reviewer see the vehicle's own computed aggression next to
  whatever this app independently concludes — arguably the most honest
  option if the two are presented as clearly distinct, unrelated numbers.
- Against: Combines both the "different vocabulary, needs its own
  presentation" problem from (a) and the "new rules need real calibration
  work" problem from (b). Most UI and engineering effort of the three
  options, and still doesn't resolve what a chunk with `Driver_Aggression_pct=8`
  vs. a from-scratch rule saying `AGGRESSIVE` should mean when they disagree
  (they will, per the row-514/row-1324 asymmetry found above) — that
  disagreement needs an explicit answer, not just two numbers next to each
  other.

## Route map: confirming, not assuming

The file has no `lat`/`lon` columns and no other positional signal. The
Driver Live Analysis page cannot show a route map for an OBD-sourced replay
— confirming this is fine (stats + drowsiness panel only) rather than
silently dropping the map. This only applies to this OBD-replay page; it
does not affect `LiveDrive`/`TripDetail`, which use real GPS-carrying
`Telemetry` rows from the existing ingest path.
