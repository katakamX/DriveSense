# DriveSense

**AI-powered driver intelligence platform** — analyses vehicle telemetry and
driver-camera signals to detect driving events, classify driving behaviour, and
produce an explainable real-time driver-risk score.

> **Status: Milestone 2 of 15 — interactive vehicle simulator.**
> A driveable manual-transmission simulator produces telemetry from a real
> simulated vehicle state, recordable as JSONL. The backend serves health
> endpoints and the frontend renders a status page. Backend telemetry ingest,
> event detection, ML, computer vision and the risk engine are **not**
> implemented yet. Nothing in this repository claims functionality it does not
> have.

## What this is

```
Telemetry source (simulator | OBD2)
        ↓
Telemetry processing  →  Driving event detection
        ↓                        ↓
   ML behaviour  ←  features     │      Computer vision (separate process)
        ↓                        ↓                ↓
              Explainable risk engine  ←──────────┘
                         ↓
        FastAPI  →  WebSocket / REST  →  React dashboard
```

Full detail in [docs/architecture.md](docs/architecture.md). Decisions with
real trade-offs are recorded as ADRs in [docs/adr/](docs/adr/):

- [0001 — Why the backend is stream-oriented](docs/adr/0001-stream-oriented-backend.md)
- [0002 — Why computer vision runs as a separate process](docs/adr/0002-cv-separate-process.md)
- [0003 — Why Redis is deferred](docs/adr/0003-defer-redis.md)
- [0004 — Why feature engineering has one implementation](docs/adr/0004-shared-feature-engineering.md)
- [0005 — Shared contracts package; `TelemetrySource` is producer-side](docs/adr/0005-shared-contracts-package.md)

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Recharts, Lucide |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 |
| Database | PostgreSQL 16 |
| Real-time | WebSockets (in-process fan-out — see ADR 0003) |
| ML | NumPy, pandas, scikit-learn, XGBoost |
| Computer vision | OpenCV, MediaPipe |
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

| Service | URL |
| --- | --- |
| Frontend (production build) | http://localhost:3000 |
| Frontend (dev server) | http://localhost:5173 |
| Backend API | http://localhost:8000/api/v1 |
| API docs | http://localhost:8000/docs |

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

### Without Docker

**Backend**

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on Unix
pip install -e ".[dev]"

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

A `Makefile` wraps these as `make backend-check`, `make frontend-check` and
`make check`. CI runs the same commands plus a Docker image build on every
push and pull request.

## API

Currently implemented:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Liveness. Never touches external systems. |
| `GET` | `/api/v1/health/ready` | Readiness. Verifies database connectivity; returns `503` when unreachable. |
| `GET` | `/openapi.json` | Generated OpenAPI schema. |

Drivers, vehicles, trips, telemetry, events, analytics, risk and the WebSocket
interface arrive in Milestones 3–5.

## Repository layout

```
contracts/   Shared TelemetryFrame and producer-side protocols
simulator/   Interactive vehicle simulator and telemetry producer
backend/     FastAPI application, database layer, pipeline, risk engine
frontend/    React dashboard
ml/          Offline ML pipeline and evaluation reports   (Milestone 7)
cv/          Driver-monitoring service, separate process  (Milestone 10)
docs/        Architecture and ADRs
data/        Datasets and recordings — gitignored, reproducible
```

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
- **Missing signals are never imputed.** When the camera is absent the risk
  engine renormalises over available inputs and marks the assessment as
  degraded, rather than inventing a score.

## Licence

MIT
