"""CLI entry point for the M14 load generator.

python -m drivesense_bench
python -m drivesense_bench --levels 1 5 10 25 50 --duration 20
python -m drivesense_bench --base-url http://127.0.0.1:8000 --ws-url ws://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.db.session import dispose_engine
from drivesense_bench.load_gen import DEFAULT_LEVELS, LATENCY_TARGET_MS, ramp
from drivesense_bench.report import format_report

if sys.platform == "win32":
    # psycopg's async mode cannot run on the default ProactorEventLoop
    # (backend/tests/conftest.py works around the same thing, for the same
    # reason: `SessionLocal` here is the identical async engine).
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="drivesense-bench", description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="backend HTTP base URL")
    parser.add_argument(
        "--ws-url", default="ws://127.0.0.1:8000", help="backend WebSocket base URL"
    )
    parser.add_argument(
        "--levels",
        type=int,
        nargs="+",
        default=list(DEFAULT_LEVELS),
        metavar="N",
        help=f"concurrent-trip levels to ramp through (default: {list(DEFAULT_LEVELS)})",
    )
    parser.add_argument("--drive", default="demo", help="scripted drive profile (default: demo)")
    parser.add_argument("--variant", default="a", help="drive variant letter (default: a)")
    parser.add_argument(
        "--duration", type=float, default=30.0, help="seconds of telemetry per trip (default: 30)"
    )
    parser.add_argument(
        "--grace",
        type=float,
        default=2.0,
        help="seconds to keep listening after a trip's last frame (default: 2)",
    )
    parser.add_argument(
        "--target-ms",
        type=float,
        default=LATENCY_TARGET_MS,
        help=f"p95 latency target to ramp against (default: {LATENCY_TARGET_MS:.0f})",
    )
    return parser


async def _run(args: argparse.Namespace) -> str:
    levels = await ramp(
        base_url=args.base_url,
        ws_base_url=args.ws_url,
        levels=tuple(args.levels),
        drive=args.drive,
        variant=args.variant,
        duration_s=args.duration,
        post_run_grace_s=args.grace,
        latency_target_ms=args.target_ms,
    )
    return format_report(levels, target_ms=args.target_ms)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        report = asyncio.run(_run(args))
    finally:
        asyncio.run(dispose_engine())
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
