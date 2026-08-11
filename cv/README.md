# cv/ — Driver monitoring service (Milestone 10)

A standalone process that owns the camera, detects facial landmarks, and
estimates drowsiness and distraction from temporal statistics (PERCLOS, blink
rate, blink duration).

Runs **outside the FastAPI worker** — see
[ADR 0002](../docs/adr/0002-cv-separate-process.md). Raw frames never leave
this process; only derived scalars are pushed to the backend at 1 Hz via
`POST /api/v1/ingest/driver-state`.

Notes for implementation:

- MediaPipe rather than Haar cascades — the latter is fragile to head
  rotation, lighting and glasses. The pip package's older `mp.solutions`
  API was removed in mediapipe 1.0; `landmarks.py` uses the newer Tasks API
  (`mediapipe.tasks.python.vision.FaceLandmarker`) against the same
  underlying 468-point face model.
- Eye-aspect-ratio thresholds are person-specific. A short neutral-face
  calibration at session start is required for this to work for anyone other
  than the developer.
- PERCLOS is an established drowsiness proxy and is cited as such, not invented.
  `drowsiness` in `DriverStateFrame` *is* the PERCLOS value — there is no
  separate drowsiness model. Reporting the same number under two names would
  be redundant; naming it `drowsiness` in the contract keeps the field
  self-explanatory to a consumer who doesn't know what PERCLOS is, while
  `perclos` stays for anyone who wants the named metric directly.
- `distraction` exists in the contract (ADR 0002 names it) but is always
  `None` from this process. No gaze or head-pose estimation is implemented —
  scope was PERCLOS/blink-based drowsiness only. Reporting a number here
  without a model behind it would be exactly the kind of overclaiming this
  project's model card (`docs/model-card.md`) argues against.

**This is not a safety or medical device.** It estimates behavioural signals
for research and demonstration and makes no claim to detect real impairment.

## Setup

```
pip install -e .          # from cv/, installs opencv-python, mediapipe, httpx, pydantic
# or: pip install -e ".[dev]"   # adds pytest, ruff for running the test suite
```

The face-landmark model bundle (`face_landmarker.task`, ~4 MB) is not
shipped in the `mediapipe` pip package. `landmarks.py` downloads it once from
Google's official model host on first run and caches it under
`cv/.models/` (gitignored). No manual step is needed with network access; if
running offline, place a copy at `cv/.models/face_landmarker.task` in advance.

## Running

```
python main.py --trip-id <uuid> --backend-url http://localhost:8000
```

The trip must already exist in the backend (`POST /api/v1/trips`) — the
ingest endpoint 404s otherwise. Useful flags: `--device-index` (default 0),
`--fps` (target analysis rate, default 15), `--calibration-samples` (default
30, ~2s of open-eye frames at 15 FPS), `--debug-window`.

`--debug-window` opens a live preview with the tracked eye contours and a
status readout drawn on the feed — for manually confirming face detection,
not for normal running. Press `q` or ESC (or close the window) to stop.
Either way, the loop logs a status line every 2s:

```
face detected in 30/30 frames | calibrating: 17/30 frames | 14.9 FPS
face detected in 30/30 frames | calibration complete (baseline EAR=0.287) | 14.9 FPS
```

A missing or disconnected camera is logged clearly and ends the process
without a crash — see `capture.py`.

## Testing

```
pytest          # from cv/
```

Covers the pure logic in `drowsiness.py` — eye-aspect-ratio, calibration,
PERCLOS, blink-rate windowing — against synthetic landmark arrays. It does
not cover `capture.py` (needs a real camera) or `landmarks.py` (needs the
MediaPipe model and a real or recorded frame); those were verified manually
against a live webcam instead of by an automated test.

## Known duplication

`DriverStateFrame` is defined twice: here in `cv/contracts.py`, and
independently in `backend/app/schemas/driver_state.py`. ADR 0002 names the
mitigation as generating both from the backend's OpenAPI schema once
Milestone 3 lands that tooling — it was never built, so this is still two
hand-maintained copies. Accepted debt, not an oversight; keep both in sync by
hand until that generation exists.
