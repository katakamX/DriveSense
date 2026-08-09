"""Deterministic thresholds for driving-event detection.

Values follow common fleet-telematics / naturalistic-driving-study convention
(roughly 0.3-0.4g for harsh braking and rapid acceleration) rather than being
derived from a specific dataset. Treat as configurable, not authoritative.
"""

HARSH_BRAKING_ACCEL_MS2 = -3.5
RAPID_ACCELERATION_ACCEL_MS2 = 3.0
SPEEDING_MARGIN_KPH = 5.0
