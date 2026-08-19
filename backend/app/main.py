"""FastAPI application factory and process lifecycle.

The backend is stream-oriented (see docs/adr/0001-stream-oriented-backend.md):
later milestones attach an in-process telemetry pipeline to this application's
lifespan. Milestone 1 establishes the shell — configuration, logging, CORS,
routing, and clean engine disposal on shutdown.
"""

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

if sys.platform == "win32":
    # psycopg's async driver requires a selector event loop; Windows defaults
    # to ProactorEventLoop, which it cannot use.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.api.v1 import (
    auth,
    driver_applications,
    driver_dashboard,
    driver_monitor,
    driver_review,
    drivers,
    health,
    ingest,
    live,
    telemetry,
    trips,
    users,
    vehicles,
)
from app.config import get_settings
from app.core.risk import sink as risk_sink
from app.core.windowing import stop_all
from app.db.session import dispose_engine
from app.ml import load_model

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info("Starting %s v%s (%s)", settings.app_name, settings.version, settings.environment)
    # Read once, here, rather than per request. A missing artefact is not a
    # startup failure — the backend serves rule-only (see app/ml/loader.py).
    load_model()
    yield
    # Per-trip inference ticks are asyncio tasks; a trip still live at
    # shutdown has one running, and it has to be cancelled before the loop
    # closes underneath it.
    await stop_all()
    # Then drain whatever those ticks had queued but not yet written. Order
    # matters twice over: after `stop_all` so nothing can enqueue behind the
    # drain, and before `dispose_engine` so the drain still has a pool to
    # write through.
    await risk_sink.stop_all()
    await dispose_engine()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Carries Authlib's OAuth `state` between /google/login and
    # /google/callback (app.core.oauth). A separate, short-lived cookie from
    # the app's own login session - see `oauth_state_secret_key`.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.oauth_state_secret_key,
        session_cookie="ds_oauth_state",
        max_age=600,
        same_site="lax",
        https_only=settings.session_cookie_secure,
    )

    v1 = APIRouter(prefix=settings.api_prefix)
    v1.include_router(health.router)
    v1.include_router(auth.router)
    v1.include_router(drivers.router)
    v1.include_router(driver_applications.router)
    v1.include_router(driver_review.router)
    v1.include_router(vehicles.router)
    # driver_dashboard's literal "/trips/me" must be registered before
    # trips.router, or "/trips/{trip_id}" would swallow it (Starlette
    # matches routes in registration order, not by specificity).
    v1.include_router(driver_dashboard.router)
    v1.include_router(trips.router)
    v1.include_router(telemetry.router)
    v1.include_router(ingest.router)
    v1.include_router(live.router)
    v1.include_router(driver_monitor.router)
    v1.include_router(users.router)
    app.include_router(v1)

    return app


app = create_app()
