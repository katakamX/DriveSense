# cv/ — Driver monitoring service (Milestone 10)

A standalone process that owns the camera, detects facial landmarks, and
estimates drowsiness and distraction from temporal statistics (PERCLOS, blink
rate, blink duration).

Runs **outside the FastAPI worker** — see
[ADR 0002](../docs/adr/0002-cv-separate-process.md). Raw frames never leave
this process; only derived scalars are pushed to the backend at 1 Hz via
`POST /api/v1/ingest/driver-state`.

Notes for implementation:

- MediaPipe FaceMesh rather than Haar cascades — the latter is fragile to head
  rotation, lighting and glasses.
- Eye-aspect-ratio thresholds are person-specific. A short neutral-face
  calibration at session start is required for this to work for anyone other
  than the developer.
- PERCLOS is an established drowsiness proxy and is cited as such, not invented.

**This is not a safety or medical device.** It estimates behavioural signals
for research and demonstration and makes no claim to detect real impairment.
