# Synthetic UAH-DriveSet fixtures — NOT real data

Every file in this directory is **fabricated** for DriveSense's unit tests.
None of it comes from UAH-DriveSet. No real recording is committed to this
repository: the real dataset is downloaded to the gitignored `data/` tree
(see [`data/README.md`](../../../../data/README.md)).

The files reproduce UAH-DriveSet's **column layout** (confirmed against the
dataset author's reader tool, `Eromera/uah_driveset_reader`) so the adapter
is exercised against the real shape, with values chosen so the correct
answer is known in advance.

## Ground truth baked into `…-D1-NORMAL-MOTORWAY`

Constructed so the axis detector has something to find:

| Channel | Content |
| --- | --- |
| **Z** (col 4) | longitudinal — tracks d(speed)/dt from the GPS file |
| **Y** (col 3) | lateral — tracks speed × yaw_rate |
| **X** (col 2) | decoy — alternating noise, correlated with neither |

- **t = 0–10 s:** straight-line acceleration at a *varying* rate (1–3 m/s²),
  yaw constant. Varying rather than constant so the correlation is defined.
- **t = 10–20 s:** constant 72 km/h through a turn at 3–9 °/s, and the yaw
  **crosses the ±180° boundary** so wraparound handling is exercised on a
  realistic path rather than only in a unit test.
- The KF columns (5–7) carry the same signal with the jitter removed, which
  lets a test prove the adapter reads the raw columns and not the filtered
  ones.

## `…-D2-AGGRESSIVE-SECONDARY`

Deliberately corrupt, for the skip-and-log path: a truncated accelerometer
row, a non-numeric field, a blank line, and a truncated GPS row. It is too
short for axis detection and is expected to be skipped by the parametrised
axis test.

## Regenerating

These are static committed files, edited by hand when a case is added. They
are small enough to read directly, which is the point — a fixture whose
values require a generator to understand cannot serve as a test oracle.
