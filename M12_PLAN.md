# M12: Dashboard Pages — Investigation

Existing routes (`frontend/src/app/App.tsx`): `/`, `/login`, `/signup`,
`/employee/login`, `/employee/review`, `/employee/review/:driverId`,
`/become-a-driver`, `/trips/:tripId/live`, `/driver-monitor`.

Existing role gating: `require_staff` in `app/core/deps.py` (employee or
admin). No `require_admin` yet. `UserRole` enum already has `ADMIN`
(`app/db/models/user.py`), just unused by any endpoint so far.

| # | Page | Backend status | Frontend status | What's actually needed |
|---|------|-----------------|-------------------|--------------------------|
| 1 | Driver dashboard (my trips, my risk score, my application status) | `GET /trips?driver_id=` exists (has `risk_score`/`risk_band` per trip). `GET /driver-applications/me` exists. **Missing:** no `/drivers/me` (or equivalent) to resolve the logged-in user → their `Driver` row; no driver-level aggregate risk score (only per-trip). | No page/route. | New endpoint: `GET /drivers/me` (pattern: `Driver.user_id == current_user.id`, like `driver_applications.py`'s `/me`). Aggregate risk score can be derived client-side from latest trip(s) — no new DB field needed. New page + route `/dashboard` (or reuse `/`). |
| 2 | Trip detail view (risk breakdown, events, route) | `GET /trips/{id}` exists (summary risk fields only). `RiskWindow` (per-window breakdown incl. contributions) and `DrivingEvent` rows are persisted per trip but **no endpoint exposes them**. `Telemetry` has `lat`/`lon` per trip (route), also **no endpoint**. | No page/route. | New read-only endpoints: `GET /trips/{id}/risk-windows`, `GET /trips/{id}/events`, `GET /trips/{id}/telemetry` (or a combined route-points endpoint). New page + route `/trips/:tripId`. |
| 3 | Employee: driver roster (filter by status) | `GET /drivers` exists, gated `require_staff`, filters: `name`, `code`. **No `status` filter** (field exists on `Driver`/`DriverRead`). | No page/route. | Add `status` query param to `list_drivers`. New page + route `/employee/drivers`. |
| 4 | Employee: vehicle roster (filter by **make only** — status descoped) | `GET /vehicles` exists, gated `require_staff` (correction: it was already gated — I misread it during investigation), filter: `make` only. | No page/route. | New page + route `/employee/vehicles`, make filter only. No backend change needed. |
| 5 | Employee: trips overview (filter/sort by risk) | `GET /trips` exists, filters: `driver_id`, `vehicle_id`, `status`. **No sort-by-risk param.** | No page/route. | Add `sort` param (e.g. by `risk_score`). New page + route `/employee/trips`. |
| 6 | Admin: user/role management (promote/demote staff) | Nothing. No endpoints on `User` at all beyond auth (register/login/me). No `require_admin` dep. `User.role` already supports `"admin"` (`UserRole.ADMIN` enum value exists, plain-string column, no migration needed). | No page/route. | New `require_admin` dep in `app/core/deps.py`. New endpoints: `GET /users` (list, admin-only), `PATCH /users/{id}/role` (promote/demote). New page + route `/admin/users`. |
| 7 | Admin: system health dashboard (**model version + risk engine version only** — recent errors descoped, no audit log table exists) | `GET /health` exists (process liveness only). Risk engine/model versions exist as per-assessment fields (`risk_engine_version`, `model_version` in `RiskOut`/`RiskWindow`), not as a "current version" summary. | No page/route. | New admin-gated endpoint surfacing current risk engine version + current model version (source: latest `RiskWindow` row, or a constants/config lookup — decide at build time). New page + route `/admin/system`. |

## Corrections after security fix (2026-08-18)
- `vehicles.py` was already gated with `require_staff` — my original read of it was wrong. Only `trips.py` was ungated; fixed separately (commit `b9aac84`), with 401/403 tests added to `test_route_protection.py`.
- Page 4: status filter descoped, make-only. No `Vehicle.status` migration.
- Page 7: "recent errors" descoped. Page ships as model version + risk engine version only.
- `require_admin` still needs to be built (page 6) — `User.role` itself already supports `"admin"` values, no DB change required first.

Proceeding to build pages 1–7 (per above), one step per page, stopping after each for confirmation.
