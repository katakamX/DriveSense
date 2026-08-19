# DriveSense

**AI-powered driver intelligence platform** — analyses vehicle telemetry and
driver-camera signals to detect driving events, classify driving behaviour, and
produce an explainable real-time driver-risk score.

> **Status: Milestones 1–12 and 14 of 15 complete.** Auth (Google OAuth + email/
> password login, sessions, role-gated routes) has also shipped, alongside the
> milestone track — including the driver application flow (basic info, 13
> required documents, submit for review) and the staff-side review queue
> (verify/reject an application, view its uploaded documents).
> The end-to-end path works: the simulator produces telemetry, the backend
> ingests it at 10 Hz into an in-process ring buffer, detects driving events,
> extracts features, runs a trained classifier and a rule-gated risk engine on
> a 1 Hz tick, and pushes the result to a React dashboard over a WebSocket. A
> separate CV process estimates drowsiness from a real webcam and posts driver
> state back at 1 Hz. The backend survives a restart without the browser
> needing a reload (M11), and the dashboard pages — driver self-service, trip
> detail, staff rosters, admin user/role management — are in place (M12).
> Measured end-to-end latency (M14) is well under the 150 ms target through 10
> concurrent trips, but the backend's default database connection pool
> collapses ingest entirely at 20 — see
> [Latency and throughput](#latency-and-throughput-m14) below.
>
> What is **not** done: there is no OBD2 integration (M13), and **the trained
> model is not fit for production use** — see [Model status](#model-status)
> below for the number that says so. Nothing here claims functionality it does
> not have.

## What this is

```
Telemetry source (simulator | OBD2)
        ↓
Telemetry processing  →  Driving event detection
        ↓                        ↓
   ML behaviour  ←  features     │      Computer vision (separate process)
        ↓                        ↓                ↓
              Explainable risk engine  ←──────────┘
                         ↓                    (not yet an input — see below)
        FastAPI  →  WebSocket / REST  →  React dashboard
```

The leg from computer vision into the risk engine is the one part of this
diagram that is not yet wired: driver state is persisted and broadcast to the
browser, but the risk engine does not consume it. The risk score is currently
derived from telemetry features alone.

Full detail in [docs/architecture.md](docs/architecture.md). Decisions with
real trade-offs are recorded as ADRs in [docs/adr/](docs/adr/):

- [0001 — Why the backend is stream-oriented](docs/adr/0001-stream-oriented-backend.md)
- [0002 — Why computer vision runs as a separate process](docs/adr/0002-cv-separate-process.md)
- [0003 — Why Redis is deferred](docs/adr/0003-defer-redis.md)
- [0004 — Why feature engineering has one implementation](docs/adr/0004-shared-feature-engineering.md)
- [0005 — Shared contracts package; `TelemetrySource` is producer-side](docs/adr/0005-shared-contracts-package.md)
- [0006 — The training-label rubric is weak supervision, not ground truth](docs/adr/0006-training-label-rubric.md)
- [0007 — The model can raise a risk band but never independently reach `HIGH_RISK`](docs/adr/0007-risk-engine-rule-gating.md)
- [0008 — Browser-camera driver monitor is an accepted exception to ADR 0002](docs/adr/0008-browser-camera-monitor-mode.md)
- [0009 — Driver documents are stored on local disk, not object storage](docs/adr/0009-local-disk-document-storage.md)

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, React Router, Lucide |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic |
| Auth | Session cookies (DB-backed opaque tokens) · bcrypt password hashing · Authlib (Google OAuth) |
| Database | PostgreSQL 16 |
| Real-time | WebSockets (in-process fan-out — see ADR 0003) |
| ML (offline) | pandas, PyArrow, scikit-learn — logistic regression and decision tree |
| ML (serving) | Plain NumPy over a JSON coefficient dump; no scikit-learn at runtime |
| Computer vision | OpenCV, MediaPipe Tasks (`FaceLandmarker`) |
| Infrastructure | Docker, Docker Compose, GitHub Actions |

## Quick start

### With Docker

```bash
cp .env.example .env          # then edit POSTGRES_PASSWORD
docker compose up --build     # frontend on :3000
```

Development stack with hot reload on both services:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Migrations are **not** run by the stack and the application does not create
tables implicitly. Apply them once the database is healthy:

```bash
docker compose exec backend alembic upgrade head
```

| Service | URL |
| --- | --- |
| Frontend (production build) | http://localhost:3000 |
| Frontend (dev server) | http://localhost:5173 |
| Backend API | http://localhost:8000/api/v1 |
| API docs | http://localhost:8000/docs |

Pages:

| Route | Page | Who sees it |
| --- | --- | --- |
| `/` | Role fork — renders the staff Dashboard, or redirects a driver to `/dashboard` | any |
| `/login`, `/signup`, `/employee/login` | Email/password or Google sign-in | unauthenticated |
| `/dashboard` | Driver self-service — my trips, my risk, my application status | driver |
| `/trips/:tripId` | Trip detail — risk-window breakdown, events, route | staff, or the trip's own driver |
| `/trips/:tripId/live` | Live Drive — real live data off the WebSocket | any |
| `/become-a-driver` | Driver application (basic info + 13 documents) | any |
| `/driver-monitor` | Browser-camera driver monitor (ADR 0008) | any |
| `/employee/review`, `/employee/review/:driverId` | Application review queue and detail | staff |
| `/employee/drivers`, `/employee/vehicles`, `/employee/trips` | Rosters and trips overview, filterable/sortable | staff |
| `/admin/users` | User/role management (promote/demote) | admin |
| `/admin/system` | Risk engine + model version | admin |

"Who sees it" describes what the **backend** enforces. Apart from `/`, which
forks on role, the routes are not guarded client-side and the nav bar is not
role-filtered: a driver can navigate to `/admin/users` and will get an error
from the API rather than a redirect. Authorisation is enforced server-side, in
one place — the pages just render what the API is willing to return. Role-aware
navigation is a UI gap, not an access-control one.

Create a driver, a vehicle and a trip through the API (or `/docs`), point the
simulator at that trip, then open its Live Drive URL.

### Vehicle simulator

```bash
cd simulator
python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate on Unix
pip install -e ../contracts       # shared contracts first — see ADR 0005
pip install -e ".[dev]"

python -m drivesense_sim          # interactive window
python -m drivesense_sim --headless   # scripted drive, records JSONL, no window
```

Controls: `W` throttle · `S` brake · `A`/`D` steer · `Shift` gear up ·
`Ctrl` gear down · `R` reverse · `N` neutral · `Space` clutch · `F1` record ·
`Esc` quit. Details in [simulator/README.md](simulator/README.md).

### Driver monitoring (camera)

Runs as its own process against a real webcam and posts derived scalars — never
frames — to the backend at 1 Hz. The trip must already exist, or the ingest
endpoint 404s.

```bash
cd cv
python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate on Unix
pip install -e .

python main.py --trip-id <uuid> --backend-url http://localhost:8000
```

Useful flags: `--device-index` (default 0), `--fps` (default 15),
`--calibration-samples` (default 30), `--debug-window` for a live preview with
the tracked eye contours. Eye-aspect-ratio thresholds are person-specific, so a
short neutral-face calibration runs at session start. Details in
[cv/README.md](cv/README.md).

### Without Docker

**Backend**

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on Unix
pip install -e ".[dev]"
pre-commit install               # once per clone — runs lint/format checks pre-commit
alembic upgrade head             # schema — nothing creates it implicitly

# Windows — recommended, frees the port first (see below)
powershell -ExecutionPolicy Bypass -File scripts/dev_server.ps1

uvicorn app.main:app --reload   # macOS/Linux
```

On Windows `uvicorn --reload` runs the application in a spawned child process.
Kill the reloader with its terminal and the child survives, keeps the listening
socket, and keeps answering requests — while the socket table still credits the
port to the parent PID, which no longer exists. The next start then loses the
bind, the error scrolls past, and requests keep hitting the stale process, so
tests pass against code that is no longer running.
[`scripts/dev_server.ps1`](backend/scripts/dev_server.ps1) clears that state and
refuses to start if the port is still answering. `python run.py` starts the
server directly, without the cleanup — it also sets the event loop policy
uvicorn needs for async psycopg.

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` to `http://localhost:8000`, so the browser
sees a single origin and no CORS configuration is needed locally.

## Development

```bash
# Backend — lint, format check, strict type check, tests
cd backend
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m mypy app
.venv/Scripts/python -m pytest -q

# Frontend — type check, lint, format check, production build
cd frontend
npm run typecheck && npm run lint && npm run format:check && npm run build
```

The same four commands (`ruff check`, `ruff format --check`, `mypy`, `pytest`)
run in `contracts/`, `simulator/`, `ml/` and `cv/` as well, each against its own
virtualenv.

A `Makefile` wraps the common ones as `make contracts-check`,
`make simulator-check`, `make backend-check`, `make frontend-check` and
`make check` (which runs those four — `ml` and `cv` are not in it yet). CI runs
six matching jobs plus a Docker image build on every push and pull request.

### Training the model

```bash
cd ml
python -m pipelines.train        # writes ml/artifacts/model.json + reports
```

The artefact is gitignored and regenerated from committed configs. Every number
in [ml/reports/](ml/reports/) is produced by that command; none is typed in by
hand. The backend loads `model.json` as an explicit coefficient dump, so the
serving path unpickles nothing and does not depend on scikit-learn. With no
artefact present the risk engine still runs, rule-only.

## API

All paths are under `/api/v1`. Generated schema at `/openapi.json`, interactive
docs at `/docs`.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness. Never touches external systems. |
| `GET` | `/health/ready` | Readiness. Verifies database connectivity; returns `503` when unreachable. |
| `POST` `GET` `PATCH` `DELETE` | `/drivers`, `/drivers/{id}` | Driver CRUD. `GET` filters by `name`, `code`, `status`. |
| `POST` `GET` `PATCH` `DELETE` | `/vehicles`, `/vehicles/{id}` | Vehicle CRUD. `GET` filters by `make`. |
| `POST` `GET` `PATCH` `DELETE` | `/trips`, `/trips/{id}` | Trip CRUD. `GET` filters by `driver_id`, `vehicle_id`, `status` and sorts by `sort=risk_score\|-risk_score` (never-scored trips always last). `PATCH` ends a trip, which flushes pending risk rows and stamps the trip's risk summary in one transaction. |
| `GET` | `/trips/me` | The current user's own trips, resolved via `Driver.user_id`. Self-service — never returns another driver's data. |
| `GET` | `/trips/{id}/risk-windows`, `/trips/{id}/events`, `/trips/{id}/telemetry` | Read-only trip detail: per-window risk breakdown, driving events, route/telemetry points. |
| `POST` | `/trips/{trip_id}/telemetry/batch` | Batched telemetry ingest. Feeds the ring buffer, event detection and the inference tick. |
| `POST` | `/ingest/driver-state` | Driver state from the CV process. `trip_id` travels in the payload, not the path — see ADR 0002. |
| `WS` | `/trips/{trip_id}/live` | Live stream. Envelope is `{ type, data }` with `type` one of `telemetry`, `event`, `risk`, `driver_state`. Closes `4404` for an unknown trip. |
| `POST` | `/auth/register`, `/auth/login`, `/auth/logout` | Email/password auth. Sessions are DB-backed opaque cookie tokens, not JWT. |
| `POST` | `/auth/verify-otp`, `/auth/resend-otp` | Email OTP verification for password accounts. |
| `GET` | `/auth/me` | Current session's user. |
| `GET` | `/auth/google/login`, `/auth/google/callback` | Google OAuth sign-in (Authlib). Finds-or-creates a `User` by email; Google-created accounts start `email_verified` with no local password. |
| `POST` `GET` | `/driver-applications`, `/driver-applications/me` | Start/read the current user's driver application (basic info + status). |
| `POST` `DELETE` | `/driver-applications/me/documents`, `/driver-applications/me/documents/{id}` | Upload/remove one of the 13 required documents (ADR 0009). |
| `POST` | `/driver-applications/me/submit` | Move a complete application to `pending` review. |
| `GET` | `/driver-review/applications`, `/driver-review/applications/{id}` | Staff review queue and one application's full detail, filterable by status. |
| `GET` | `/driver-review/applications/{id}/documents/{id}/file` | Stream one uploaded document's bytes back to a reviewer. |
| `POST` | `/driver-review/applications/{id}/verify`, `/driver-review/applications/{id}/reject` | Decide a `pending` application. |
| `GET` `PATCH` | `/users`, `/users/{id}/role` | Admin-only user list and role promote/demote, validated against `UserRole`. |
| `GET` | `/admin/system-health` | Admin-only. Current risk engine version and loaded model version (artefact fingerprint, or rule-only when no artefact is present). |

Three gates, in `app/core/deps.py`:

- `get_current_user` — any logged-in user. Self-service routes (`/trips/me`,
  `/driver-applications/me`) use this and resolve the caller's own records via
  `Driver.user_id`, so they can never return another user's data.
- `require_staff` — `employee` or `admin`. Gates `/drivers`, `/vehicles`,
  `/trips` and everything under `/driver-review`.
- `require_admin` — `admin` only. Gates `/users` and `/admin`, so an employee
  can review applications but cannot promote anyone.

The trip-detail routes (`/trips/{id}/risk-windows`, `/events`, `/telemetry`)
are the one mixed case: staff pass unconditionally, and otherwise the caller
must own the trip's driver record. A driver reading another driver's trip gets
`404`, not `403` — the same "wrong owner reads as missing" answer the document
endpoints give, so the API never confirms that a trip it will not show you
exists.

The historical read surface for driving events and risk windows is the
trip-detail routes above (M12). The **live** path remains the WebSocket; there
is still no bulk/cross-trip read endpoint for raw telemetry frames.

## Model status

The behaviour classifier is trained and evaluated, and the evaluation says not
to trust it. Full detail in [docs/model-card.md](docs/model-card.md) and
[ml/reports/m8-evaluation.md](ml/reports/m8-evaluation.md).

| | Result |
| --- | --- |
| Held-out simulator drives | macro-F1 **0.922 ± 0.016** |
| Real UAH-DriveSet telemetry (1,709 windows) | **0.520** accuracy, **0.451** macro-F1, against a **0.214** majority-class baseline |
| `HIGH_RISK` precision on real telemetry | **0.105** — 10 of 16 true windows recovered by predicting the class 95 times |

Better than guessing on real driving, and a long way from usable. That gap is
the reason for [ADR 0007](docs/adr/0007-risk-engine-rule-gating.md): the model
can raise a risk band but can never independently reach `HIGH_RISK`, so a
`HIGH_RISK` verdict always has a matched rule behind it.

The first M8 run scored *worse* than the baseline (0.302 against 0.650). The
cause was a defect in the simulator corpus, not the estimator, and both numbers
are kept in the model card rather than the bad one being deleted.

## Milestones

Each has an exit criterion it had to meet before the next one started; the full
table is in [docs/architecture.md](docs/architecture.md).

| # | Milestone | |
| --- | --- | --- |
| 1 | Architecture, scaffold, Docker skeleton, CI | ✅ |
| 2 | Interactive vehicle simulator + shared contracts | ✅ |
| 3 | FastAPI + PostgreSQL + migrations + CRUD | ✅ |
| 4 | Ingest pipeline + batched persistence | ✅ |
| 5 | Event detection + thin WebSocket path | ✅ |
| 6 | Design system + Dashboard + Live Drive | ✅ |
| 7 | Dataset + shared feature engineering | ✅ |
| 8 | Model training + honest evaluation | ✅ |
| 9 | Risk engine + explainability | ✅ |
| 10 | CV driver monitoring | ✅ |
| 11 | Real-time hardening — survives backend restart without UI breakage | ✅ |
| 12 | Remaining dashboard pages | ✅ |
| 13 | OBD2 / ELM327 integration | |
| 14 | Test hardening + benchmarking | ✅ |
| 15 | Deployment polish + documentation | |

Milestones 9 and 10 were live-verified against a real trained model and a real
webcam respectively, not only against tests.

### Latency and throughput (M14)

The end-to-end latency target (ingest → browser, < 150 ms) is stated in the
architecture document. It's now measured — with [`bench/`](bench/), a load
generator (`python -m drivesense_bench`) that POSTs real-time-paced 10 Hz
telemetry over HTTP while a real WebSocket client times each frame's round
trip, ramping concurrent trips until something breaks. Run against both the
local dev backend and the Docker Compose stack, on one 16-core dev machine:

| Concurrent trips | p95 latency (dev / docker) |
| --- | --- |
| 1  | 85.9 / 17.1 ms |
| 2  | 80.0 / 32.3 ms |
| 5  | 108.2 / 41.0 ms |
| 10 | 116.4 / 89.8 ms |
| 20 | every request failed |

**p95 stays under the 150 ms target through 10 concurrent trips.** At 20 it
doesn't degrade gracefully past the target — ingest collapses outright, in
both environments, with the identical error:

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached,
connection timed out, timeout 30.00
```

The backend's async engine (`app/db/session.py`) runs on SQLAlchemy's
default connection pool (15 connections total); each concurrent trip needs
one for its telemetry insert and another for its 1 Hz risk tick, and demand
outstrips the pool somewhere between 10 and 20 trips. Full numbers and the
method are in [`docs/architecture.md`](docs/architecture.md#frequency-budget).
Tuning the pool size is left to a future ops/perf pass — this milestone's
job was to measure and report, not to fix.

## Repository layout

```
contracts/   Shared TelemetryFrame and producer-side protocols
simulator/   Interactive vehicle simulator and telemetry producer
backend/     FastAPI application, database layer, pipeline, risk engine
  app/core/windowing/   Ring buffer + 1 Hz inference tick
  app/core/events/      Driving-event detection
  app/core/features/    Feature extraction — the one implementation (ADR 0004)
  app/core/risk/        Rule-gated risk engine, explainability, batched sink
  app/core/live/        In-process WebSocket fan-out (ADR 0003)
  app/ml/               Artefact loader and inference; no scikit-learn at runtime
  app/core/sessions.py, oauth.py   Session cookie + Google OAuth auth
frontend/    React dashboard — Login/Signup, Dashboard, Driver Dashboard,
             Trip Detail, Live Drive, Driver Monitor, Driver Application,
             Employee Login/Review, Employee rosters (drivers, vehicles,
             trips), Admin Users, Admin System
ml/          Offline training pipeline, artefacts and evaluation reports
cv/          Driver-monitoring service, separate process (ADR 0002)
docs/        Architecture, model card and ADRs
data/        Datasets and recordings — gitignored, reproducible
```

Database tables: `drivers`, `vehicles`, `trips`, `telemetry`, `driving_events`,
`risk_windows`, `driver_states`, `users`, `sessions`, `document_uploads`.

## Configuration

All configuration comes from environment variables; see
[.env.example](.env.example) for the full set. **No secrets are committed** —
`.env` is gitignored, and the example file contains placeholders only.

## Scope and honesty

This project deliberately prefers a smaller system that genuinely works over a
larger one with demo-only functionality.

- **No fabricated metrics.** Every number published here is produced by a
  committed, reproducible pipeline.
- **ML labels are rule-derived** and documented as weak supervision, validated
  against real public telemetry. See [docs/architecture.md](docs/architecture.md).
- **The driver-monitoring component is not a safety or medical device.** It
  estimates behavioural signals for research and demonstration purposes and
  makes no claim to detect real impairment.
- **Missing signals are never imputed.** A risk assessment carries its own
  provenance: whether a model artefact was loaded, whether the rule layer
  gated the model's band, which rules matched, and what fraction of the
  30-second window actually had samples. A fresh checkout with no `model.json`
  still produces assessments — rule-only ones, labelled as such — rather than
  a fabricated score.
- **The camera signal is not yet fused into the risk score.** It is captured,
  persisted and streamed, and that is all. Wiring it in without first deciding
  how a missing camera renormalises the score would be exactly the kind of
  demo-only functionality this section exists to prevent.

## Licence

MIT
