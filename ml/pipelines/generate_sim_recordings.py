"""Bulk-generate labelled simulator recordings for the M8 training set.

    python -m pipelines.generate_sim_recordings              # the full corpus
    python -m pipelines.generate_sim_recordings --dry-run    # list what it would write
    python -m pipelines.generate_sim_recordings --profile high_risk

Loops `profile x variant x seed` and drives the simulator's own headless
entry point once per combination, writing JSONL + meta sidecars into
`data/recordings/`. The seed feeds `SimConfig.sensor_noise_seed`, which is
the cheap axis of variation: identical physics, different measurement noise,
so two recordings of the same script are not byte-identical rows.

Two things this deliberately does *not* do:

*It does not vary the physics.* Sensor noise perturbs what the logger sees,
not how the car was driven. Genuine behavioural variety has to come from
authoring more script variants in `drivesense_sim.drives` — the seed axis
multiplies recordings, it does not multiply driving styles. Both axes are
used here for that reason (3-4 variants per profile, several seeds each)
rather than one script and many seeds.

*It does not label anything.* Labels come from the rubric at featurise time
(`pipelines.labeling.rubric`), applied to windows rather than to whole
recordings. The profile name is the drive's *intent*; whether the rubric
agrees is an empirical question this pipeline leaves open on purpose, and
one worth checking (see ml/reports/m7b-simulator-generation-pilot-and-bulk.md).

The simulator is invoked as a subprocess rather than imported: `ml/` depends
on the backend package (ADR 0004), not on `drivesense_sim`, and importing it
here would add a dependency edge the architecture does not have.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SIMULATOR_DIR = REPO_ROOT / "simulator"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "recordings"

# Variants per profile, and how many seeds each gets. HIGH_RISK is
# deliberately over-scripted: it is the rarest class in real driving, so
# leaving its share of the corpus to chance would under-represent exactly the
# class the model most needs examples of.
PROFILE_PLAN: dict[str, tuple[list[str], int]] = {
    "calm": (["a", "b", "c"], 6),
    "normal": (["a", "b", "c"], 6),
    "aggressive": (["a", "b", "c"], 6),
    "high_risk": (["a", "b", "c", "d"], 5),
}

# Arbitrary but fixed, so a regenerated corpus is the same corpus.
SEED_BASE = 1000


class GenerationError(RuntimeError):
    """A simulator run failed and the corpus is therefore incomplete."""


@dataclass(frozen=True)
class Run:
    profile: str
    variant: str
    seed: int

    @property
    def trip_id(self) -> str:
        return f"{self.profile}-{self.variant}-seed{self.seed:03d}"


def plan_runs(profiles: list[str] | None = None) -> list[Run]:
    """Every (profile, variant, seed) combination, in a deterministic order."""
    runs: list[Run] = []
    for profile, (variants, seed_count) in PROFILE_PLAN.items():
        if profiles and profile not in profiles:
            continue
        for variant_index, variant in enumerate(variants):
            for seed_index in range(seed_count):
                seed = SEED_BASE + variant_index * 100 + seed_index
                runs.append(Run(profile=profile, variant=variant, seed=seed))
    return runs


def run_one(run: Run, out_dir: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "drivesense_sim",
        "--headless",
        "--drive",
        run.profile,
        "--variant",
        run.variant,
        "--seed",
        str(run.seed),
        "--trip-id",
        run.trip_id,
        "--out",
        str(out_dir),
    ]
    result = subprocess.run(command, cwd=SIMULATOR_DIR, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise GenerationError(
            f"{run.trip_id} failed (exit {result.returncode})\n"
            f"  stdout: {result.stdout.strip()}\n"
            f"  stderr: {result.stderr.strip()}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bulk-generate labelled simulator recordings into data/recordings."
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=sorted(PROFILE_PLAN),
        help="only generate this profile (repeatable; default: all)",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--dry-run", action="store_true", help="print the planned recordings and exit"
    )
    args = parser.parse_args(argv)

    runs = plan_runs(args.profile)
    if args.dry_run:
        for run in runs:
            print(run.trip_id)
        print(f"\n{len(runs)} recording(s) planned into {args.out}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for index, run in enumerate(runs, start=1):
        print(f"[{index:3d}/{len(runs)}] {run.trip_id}", flush=True)
        try:
            run_one(run, args.out)
        except GenerationError as exc:
            # One bad script must not cost the whole corpus; the run is
            # reported at the end rather than silently dropped.
            print(f"  FAILED: {exc}", file=sys.stderr)
            failures.append(run.trip_id)

    print(f"\nwrote {len(runs) - len(failures)} recording(s) to {args.out}")
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
