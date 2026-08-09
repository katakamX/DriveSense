"""Command-line entry point.

python -m drivesense_sim                     interactive window
python -m drivesense_sim --record            interactive, recording on
python -m drivesense_sim --headless          scripted drive, no window
"""

from __future__ import annotations

import argparse
from pathlib import Path

from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.drives import DEMO_DRIVE
from drivesense_sim.input.providers import ScriptedInputProvider
from drivesense_sim.source import SimulatorTelemetrySource
from drivesense_sim.telemetry.sinks import DEFAULT_RECORDING_DIR, JsonlSink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="drivesense-sim", description=__doc__)
    parser.add_argument("--record", action="store_true", help="start with recording enabled")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run the scripted demo drive with no window and exit",
    )
    parser.add_argument("--duration", type=float, default=None, help="headless duration, seconds")
    parser.add_argument("--vehicle", default="hatchback", help="vehicle specification name")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_RECORDING_DIR, help="recording directory"
    )
    parser.add_argument("--stall", action="store_true", help="enable engine stalling")
    parser.add_argument("--noise", action="store_true", help="enable sensor noise")
    return parser


def run_headless(args: argparse.Namespace) -> int:
    config = SimConfig(stall_enabled=args.stall, sensor_noise_enabled=args.noise)
    provider = ScriptedInputProvider(DEMO_DRIVE, config)
    source = SimulatorTelemetrySource(
        provider, VehicleSpec.load(args.vehicle), config, duration_s=args.duration
    )

    meta = source.start(trip_id="sim-demo")
    sink = JsonlSink(args.out)
    sink.open(meta)
    try:
        for frame in source.frames():
            sink.write(frame)
    finally:
        sink.close()
        source.stop()

    print(f"Wrote {sink.frames_written} frames to {sink.path}")
    print(f"Metadata: {sink.meta_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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
