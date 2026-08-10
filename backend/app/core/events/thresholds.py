"""Deterministic thresholds for driving-event detection.

Values follow common fleet-telematics / naturalistic-driving-study convention
(roughly 0.3-0.4g for harsh braking and rapid acceleration) rather than being
derived from a specific dataset. Treat as configurable, not authoritative.

The *release* thresholds and frame counts below exist because a bare
threshold crossing is not an event. Two failure modes made this concrete
(see ml/reports/m7b-simulator-generation-pilot-and-bulk.md):

- Clean simulator physics holds a deceleration steadily past -3.5 m/s^2 for
  the whole brake application, so one real brake crossed the line on ~20
  consecutive 10 Hz frames.
- Real accelerometer telemetry (UAH-DriveSet) is noisy: during one real
  brake the signal dips past -3.5 for isolated single samples, many times,
  non-consecutively.

Counting raw crossings therefore made "one event" mean two entirely
different things depending on the data source. Requiring a crossing to
*persist* (MIN_*_FRAMES) rejects the isolated noise dips, and requiring a
*recovery* past a nearer release threshold (…_RELEASE_ACCEL_MS2) before the
event can close stops one brake being chopped into several as the signal
oscillates around the line.
"""

HARSH_BRAKING_ACCEL_MS2 = -3.5
RAPID_ACCELERATION_ACCEL_MS2 = 3.0
SPEEDING_MARGIN_KPH = 5.0

# Hysteresis band: an open event stays open until the signal recovers past
# these, 1.0 m/s^2 back from the trigger line. Both sit between the trigger
# and the "any acceleration/braking" 0.5 m/s^2 used by
# app.core.features.extract, so the band means "still braking/accelerating
# meaningfully", not "back to normal".
HARSH_BRAKING_RELEASE_ACCEL_MS2 = -2.5
RAPID_ACCELERATION_RELEASE_ACCEL_MS2 = 2.0

# Frames, at the 10 Hz telemetry rate this system samples at (see
# docs/architecture.md's frequency budget).
#
# MIN_EVENT_FRAMES = 3 (0.3 s): a real brake or throttle application lasts
# well over 0.3 s — human pedal inputs are ~0.5-3 s — while sensor noise
# crosses the line for one or two samples. Measured against the UAH corpus,
# single-frame crossings were the dominant nonzero case, which is exactly
# what this rejects.
#
# MIN_RELEASE_FRAMES = 5 (0.5 s): deliberately larger than the open count.
# Standard debounce asymmetry — hard to open, harder to spuriously close —
# so a momentary easing mid-brake does not split one event into two.
MIN_EVENT_FRAMES = 3
MIN_RELEASE_FRAMES = 5
