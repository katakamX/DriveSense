"""Command-line entry point.

python -m drivesense_sim                              interactive window
python -m drivesense_sim --record                     interactive, recording on
python -m drivesense_sim --headless                   scripted demo drive, no window
python -m drivesense_sim --headless --drive calm      a labelled profile drive
python -m drivesense_sim --headless --drive high_risk --variant c --seed 7
python -m drivesense_sim --headless --post-to http://localhost:8000 --backend-trip-id UUID
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from drivesense_contracts import TelemetrySink
from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.drives import PROFILE_DRIVES, get_drive, variants_for
from drivesense_sim.input.providers import ScriptedInputProvider
from drivesense_sim.source import SimulatorTelemetrySource
from drivesense_sim.telemetry.sinks import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_RECORDING_DIR,
    HttpSink,
    JsonlSink,
)

DRIVE_CHOICES = ["demo", *sorted(PROFILE_DRIVES)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="drivesense-sim", description=__doc__)
    parser.add_argument("--record", action="store_true", help="start with recording enabled")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run a scripted drive with no window and exit",
    )
    parser.add_argument(
        "--drive",
        choices=DRIVE_CHOICES,
        default="demo",
        help="which scripted drive to run headless (default: demo)",
    )
    parser.add_argument(
        "--variant",
        default="a",
        help="variant letter within the chosen drive profile (default: a)",
    )
    parser.add_argument(
        "--trip-id",
        default=None,
        help="recording id; defaults to {drive}-{variant}-seed{seed}",
    )
    parser.add_argument("--duration", type=float, default=None, help="headless duration, seconds")
    parser.add_argument("--vehicle", default="hatchback", help="vehicle specification name")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_RECORDING_DIR, help="recording directory"
    )
    parser.add_argument("--stall", action="store_true", help="enable engine stalling")
    parser.add_argument("--noise", action="store_true", help="enable sensor noise")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="sensor-noise seed; implies --noise when given",
    )
    parser.add_argument(
        "--post-to",
        default=None,
        metavar="BASE_URL",
        help="POST frames to a backend (e.g. http://localhost:8000) instead of writing JSONL",
    )
    parser.add_argument(
        "--backend-trip-id",
        default=None,
        metavar="UUID",
        help="existing backend trip to post into; required with --post-to",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"frames per POST when using --post-to (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="pace frames at telemetry_hz instead of running as fast as the CPU allows "
        "(for latency measurement against a live backend)",
    )
    return parser


def default_trip_id(drive: str, variant: str, seed: int | None) -> str:
    """A recording id that encodes what produced it.

    Deliberately not a fixed string: bulk generation writes many recordings
    into one directory, and a hardcoded id would have each run overwrite the
    last.
    """
    if drive == "demo":
        return "sim-demo" if seed is None else f"sim-demo-seed{seed:03d}"
    suffix = "" if seed is None else f"-seed{seed:03d}"
    return f"{drive}-{variant}{suffix}"


def run_headless(args: argparse.Namespace) -> int:
    noise_enabled = args.noise or args.seed is not None
    config = SimConfig(
        stall_enabled=args.stall,
        sensor_noise_enabled=noise_enabled,
        **({"sensor_noise_seed": args.seed} if args.seed is not None else {}),
    )

    steps = get_drive(args.drive, args.variant)
    provider = ScriptedInputProvider(steps, config)
    source = SimulatorTelemetrySource(
        provider, VehicleSpec.load(args.vehicle), config, duration_s=args.duration
    )

    trip_id = args.trip_id or default_trip_id(args.drive, args.variant, args.seed)

    meta = source.start(trip_id=trip_id)
    sink: HttpSink | JsonlSink = (
        HttpSink(args.post_to, args.backend_trip_id, batch_size=args.batch_size)
        if args.post_to
        else JsonlSink(args.out)
    )

    def pump(destination: TelemetrySink) -> None:
        destination.open(meta)
        try:
            for frame in source.frames(realtime=args.realtime):
                destination.write(frame)
        finally:
            destination.close()
            source.stop()

    pump(sink)

    if isinstance(sink, HttpSink):
        print(f"Posted {sink.frames_sent} frames in {sink.batches_sent} batches to {args.post_to}")
        if sink.frames_failed:
            print(f"FAILED to post {sink.frames_failed} frames ({sink.batches_failed} batches)")
            return 1
        return 0

    print(f"Wrote {sink.frames_written} frames to {sink.path}")
    print(f"Metadata: {sink.meta_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.post_to and not args.backend_trip_id:
        print("error: --post-to requires --backend-trip-id")
        return 2
    if args.post_to and not args.headless:
        # The interactive app owns its own sink wiring; --post-to would be
        # silently ignored there, which is worse than refusing it.
        print("error: --post-to is only supported with --headless")
        return 2
    if args.post_to:
        # Without this the sink's warnings about failed POSTs go nowhere and a
        # run that dropped every batch looks identical to one that worked.
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.drive != "demo" and args.variant not in variants_for(args.drive):
        available = ", ".join(variants_for(args.drive))
        print(
            f"error: drive {args.drive!r} has no variant {args.variant!r} (available: {available})"
        )
        return 2

    if args.headless:
        return run_headless(args)

    # Imported lazily so that headless use never initialises pygame.
    from drivesense_sim.render.app import AppOptions, SimulatorApp

    config = SimConfig(stall_enabled=args.stall, sensor_noise_enabled=args.noise)
    app = SimulatorApp(
        AppOptions(record=args.record, recording_dir=args.out, vehicle=args.vehicle), config
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
