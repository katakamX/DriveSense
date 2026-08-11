"""Window and featurise both corpora into one Parquet row per window.

    python -m pipelines.featurise                # both corpora
    python -m pipelines.featurise --corpus uah    # UAH validation set only
    python -m pipelines.featurise --corpus sim    # simulator training set only

For each corpus this:

1. Loads recordings via the corpus's adapter (`pipelines.adapters.uah` or
   `pipelines.adapters.recordings`).
2. For UAH, resolves the axis mapping once across the whole dataset via
   `dataset_axis_mapping` and passes it to every `load_recording` call —
   *not* per-recording detection, which re-litigates a question that has
   exactly one right answer per capture rig (see the M7 axis-consensus fix
   in `pipelines.adapters.uah`).
3. Windows each recording with `app.core.features.windows.make_windows`
   (30s span, 50% overlap — the convention in `ml/README.md`).
4. Extracts the 26 shared features with `app.core.features.extract_features`
   (ADR 0004: the only implementation, imported from the backend).
5. Drops windows whose `coverage_ratio` falls below `COVERAGE_RATIO_THRESHOLD`
   — a window built from a gappy span understates variability and jerk
   features rather than measuring driving that didn't happen.
6. Writes one row per surviving window to
   `data/processed/features_<corpus>_v<FEATURE_VERSION>.parquet`.

It also writes `ml/reports/m7-dataset-summary.md`: row counts, class
balance, per-driver window counts and the coverage-rejection rate. That
report is committed (parquet output is gitignored, per `data/README.md`)
so the numbers are reviewable without the data itself.

If a corpus has no recordings to featurise, this reports that plainly and
skips writing its parquet file rather than fabricating rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from app.core.features import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    FeatureContext,
    FeatureSample,
    FeatureVector,
    extract_features,
)
from app.core.features.windows import make_windows

from pipelines.adapters import recordings as sim_adapter
from pipelines.adapters import uah as uah_adapter
from pipelines.fetch_uah import git_sha
from pipelines.labeling.rubric import label_window_with_reason
from pipelines.split import drive_variant

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_UAH_ROOT = REPO_ROOT / "data" / "raw" / "uah-driveset" / "UAH-DRIVESET-v1"
DEFAULT_UAH_MANIFEST = REPO_ROOT / "data" / "raw" / "uah-driveset" / "MANIFEST.json"
DEFAULT_SIM_ROOT = REPO_ROOT / "data" / "recordings"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "processed"
DEFAULT_REPORT_PATH = REPO_ROOT / "ml" / "reports" / "m7-dataset-summary.md"

# UAH-DriveSet's accelerometer grid is 10 Hz (see pipelines.adapters.uah); the
# simulator's rate is read per-recording from its meta sidecar instead, since
# it is a configured value, not a dataset constant.
UAH_SAMPLE_RATE_HZ = 10.0

# A 30 s window at 10 Hz expects 300 samples. Below 80% (240 samples, i.e.
# more than a 6 s gap inside the span) forward-filled GPS gaps and dropped
# accelerometer rows are enough to visibly flatten std/jerk features on a
# window that was not, in fact, fully observed. This is a pipeline policy
# choice — coverage_ratio itself carries no threshold — recorded here so it
# changes deliberately, not by drift.
COVERAGE_RATIO_THRESHOLD = 0.8

# UAH-DriveSet carries no posted speed limit; recordings were captured in
# Spain (Romera et al., ITSC 2016), where the general limits are 120 km/h on
# motorways and 90 km/h on conventional/secondary roads. Used only to derive
# the speeding-related features (23, 26); it is a labelled per-road-type
# constant, not a measurement.
UAH_SPEED_LIMIT_BY_ROAD_TYPE = {"MOTORWAY": 120.0, "SECONDARY": 90.0}

# Fallback for anything without a road-type-specific limit above: the same
# default the live ingest path uses (app.config.Settings.default_speed_limit_kph).
# Applies to every simulator row and to any UAH road_type this pipeline hasn't
# seen.
#
# **Why the simulator gets one flat limit, decided in M8's domain-gap work.**
# The M8 gap analysis flagged `speeding_time_ratio` as behaving incomparably
# across the two corpora: it was non-zero in 3.6% of simulator windows against
# 27% of UAH windows. The question was whether the simulator should get
# road-type-aware limits like UAH does.
#
# It cannot, and the reason is not a policy choice: **the simulator has no
# concept of a road.** There is no road type, no route, no posted limit
# anywhere in `simulator/` or in the shared `contracts` schema — a recording is
# a vehicle state trace and nothing else. Any road type attached here would be
# invented by this pipeline, not measured.
#
# Two ways of inventing one were considered and rejected:
#
#   * *Per driving profile* (give HIGH_RISK a lower limit so it speeds).
#     Rejected outright — it leaks the label into a feature. The rubric reads
#     `speeding_time_ratio`, so deriving the limit from the profile would make
#     the label partly a function of itself, which is exactly the circularity
#     ADR 0006 exists to avoid.
#   * *Alternating 120/90 by recording*, mimicking UAH's motorway/secondary
#     mix. Not circular, but it adds a random component to a rubric input:
#     identical driving would be labelled differently depending on a coin
#     flip this pipeline tossed. That is label noise manufactured to make a
#     histogram match.
#
# The measured cause turned out to be elsewhere anyway. The simulator's windows
# were not failing to speed because 100 kph was the wrong limit; they were
# failing because the scripted drives cruised at ~53 kph and never came near
# any plausible limit. With `drivesense_sim.drives` recalibrated to real
# highway speeds, one flat limit separates the classes as intended — CALM and
# NORMAL cruise below it, HIGH_RISK sits well above it — and no road type has
# to be fabricated to get there.
#
# The residual mismatch is stated rather than papered over: UAH's SECONDARY
# recordings sit at a median 88.7 kph against a 90 kph limit, so noise alone
# pushes 42% of those windows over the +5 margin, while its MOTORWAY
# recordings (98.0 median, 120 limit) cross it in 9%. No single simulator
# limit reproduces that split, because it is a property of where those cars
# were driven and the simulator does not model place.
DEFAULT_SPEED_LIMIT_KPH = 100.0

# NORMAL1/NORMAL2 are the secondary-road normal drives split for D1-D5 (see
# pipelines.adapters.uah); they are the same behaviour class as NORMAL, not a
# distinct one.
UAH_LABEL_BY_BEHAVIOUR = {
    "NORMAL": "normal",
    "NORMAL1": "normal",
    "NORMAL2": "normal",
    "AGGRESSIVE": "aggressive",
    "DROWSY": "drowsy",
}

PARQUET_COLUMNS = (
    "window_id",
    "corpus",
    "driver_id",
    "recording_id",
    "window_index",
    "window_start",
    "window_end",
    "road_type",
    "speed_limit_kph",
    "sample_count",
    "coverage_ratio",
    *FEATURE_NAMES,
    "uah_label",
    "rubric_label",
    "feature_version",
    "git_sha",
    "dataset_sha256",
    "generated_at",
)


@dataclass
class CorpusSummary:
    corpus: str
    output_path: Path | None
    recording_count: int
    kept_windows: int
    rejected_windows: int
    label_counts: Counter[str]
    driver_window_counts: Counter[str]
    # Rubric labels are the training signal; `label_counts` above is the
    # corpus's own ground-truth-ish label where it has one (UAH only).
    rubric_label_counts: Counter[str] = field(default_factory=Counter)
    # Simulator only: windows per scripted drive variant, so the by-trip /
    # by-driver-profile split commitment (ADR 0006) can be checked against
    # actual counts rather than assumed.
    variant_window_counts: Counter[str] = field(default_factory=Counter)
    missing_prerequisites: list[str] = field(default_factory=list)

    @property
    def total_windows(self) -> int:
        return self.kept_windows + self.rejected_windows

    @property
    def rejection_rate(self) -> float:
        return self.rejected_windows / self.total_windows if self.total_windows else 0.0


def _row(
    *,
    corpus: str,
    driver_id: str | None,
    recording_id: str,
    window_index: int,
    road_type: str | None,
    speed_limit_kph: float,
    vector: FeatureVector,
    uah_label: str | None,
    rubric_label: str | None,
    sha: str | None,
    dataset_sha256: str | None,
    generated_at: str,
) -> dict[str, object]:
    values = vector.as_dict()
    row: dict[str, object] = {
        "window_id": f"{recording_id}::{window_index:04d}",
        "corpus": corpus,
        "driver_id": driver_id,
        "recording_id": recording_id,
        "window_index": window_index,
        "window_start": vector.window_start.isoformat(),
        "window_end": vector.window_end.isoformat(),
        "road_type": road_type,
        "speed_limit_kph": speed_limit_kph,
        "sample_count": vector.sample_count,
        "coverage_ratio": vector.coverage_ratio,
        **{name: values[name] for name in FEATURE_NAMES},
        "uah_label": uah_label,
        "rubric_label": rubric_label,
        "feature_version": vector.feature_version,
        "git_sha": sha,
        "dataset_sha256": dataset_sha256,
        "generated_at": generated_at,
    }
    return row


def _windows_to_rows(
    *,
    corpus: str,
    driver_id: str | None,
    recording_id: str,
    road_type: str | None,
    speed_limit_kph: float,
    samples: list[FeatureSample],
    sample_rate_hz: float,
    uah_label: str | None,
    sha: str | None,
    dataset_sha256: str | None,
    generated_at: str,
) -> tuple[list[dict[str, object]], int, int]:
    """Window + featurise one recording. Returns (rows, kept, rejected)."""
    windows = make_windows(samples, expected_rate_hz=sample_rate_hz)
    rows: list[dict[str, object]] = []
    rejected = 0
    for index, window in enumerate(windows):
        if window.coverage_ratio < COVERAGE_RATIO_THRESHOLD:
            rejected += 1
            continue
        ctx = FeatureContext(speed_limit_kph=speed_limit_kph, coverage_ratio=window.coverage_ratio)
        vector = extract_features(list(window.samples), ctx)
        rows.append(
            _row(
                corpus=corpus,
                driver_id=driver_id,
                recording_id=recording_id,
                window_index=index,
                road_type=road_type,
                speed_limit_kph=speed_limit_kph,
                vector=vector,
                uah_label=uah_label,
                # Applied to both corpora: the simulator rows are the training
                # labels, the UAH rows exist only so the rubric can be
                # cross-tabbed against uah_label (ADR 0006) — UAH is never
                # trained on regardless of what the rubric says about it.
                rubric_label=label_window_with_reason(vector.as_dict())[0],
                sha=sha,
                dataset_sha256=dataset_sha256,
                generated_at=generated_at,
            )
        )
    return rows, len(rows), rejected


def _write_parquet(rows: list[dict[str, object]], path: Path) -> None:
    frame = pd.DataFrame(rows, columns=list(PARQUET_COLUMNS))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, engine="pyarrow", index=False)


def featurise_uah(
    *,
    uah_root: Path,
    manifest_path: Path,
    output_dir: Path,
    sha: str | None,
    generated_at: str,
) -> CorpusSummary:
    directories = uah_adapter.find_recordings(uah_root)
    if not directories:
        return CorpusSummary(
            corpus="uah",
            output_path=None,
            recording_count=0,
            kept_windows=0,
            rejected_windows=0,
            label_counts=Counter(),
            driver_window_counts=Counter(),
            missing_prerequisites=[
                f"no UAH-DriveSet recordings found under {uah_root} "
                "(run `python -m pipelines.fetch_uah` first)"
            ],
        )

    dataset_sha256 = None
    if manifest_path.is_file():
        dataset_sha256 = json.loads(manifest_path.read_text(encoding="utf-8")).get("sha256")

    consensus = uah_adapter.dataset_axis_mapping(directories)
    recordings = uah_adapter.load_recordings(directories, axis_mapping=consensus.mapping)

    rows: list[dict[str, object]] = []
    kept = 0
    rejected = 0
    label_counts: Counter[str] = Counter()
    driver_window_counts: Counter[str] = Counter()
    rubric_label_counts: Counter[str] = Counter()

    for recording in recordings:
        meta = recording.meta
        label = UAH_LABEL_BY_BEHAVIOUR.get(meta.behaviour)
        speed_limit_kph = UAH_SPEED_LIMIT_BY_ROAD_TYPE.get(meta.road_type, DEFAULT_SPEED_LIMIT_KPH)
        recording_rows, recording_kept, recording_rejected = _windows_to_rows(
            corpus="uah",
            driver_id=meta.driver_id,
            recording_id=meta.recording_id,
            road_type=meta.road_type,
            speed_limit_kph=speed_limit_kph,
            samples=recording.samples,
            sample_rate_hz=UAH_SAMPLE_RATE_HZ,
            uah_label=label,
            sha=sha,
            dataset_sha256=dataset_sha256,
            generated_at=generated_at,
        )
        rows.extend(recording_rows)
        kept += recording_kept
        rejected += recording_rejected
        if label is not None:
            label_counts[label] += recording_kept
        driver_window_counts[meta.driver_id] += recording_kept
        for row in recording_rows:
            rubric_label_counts[str(row["rubric_label"])] += 1

    output_path = None
    if rows:
        output_path = output_dir / f"features_uah_v{FEATURE_VERSION}.parquet"
        _write_parquet(rows, output_path)

    missing = []
    skipped_recordings = len(directories) - len(recordings)
    if skipped_recordings:
        missing.append(f"{skipped_recordings} UAH recording(s) failed to parse and were skipped")

    return CorpusSummary(
        corpus="uah",
        output_path=output_path,
        recording_count=len(recordings),
        kept_windows=kept,
        rejected_windows=rejected,
        label_counts=label_counts,
        driver_window_counts=driver_window_counts,
        rubric_label_counts=rubric_label_counts,
        missing_prerequisites=missing,
    )


def _sha256_of_files(paths: list[Path]) -> str:
    """Digest identifying exactly which recording bytes this run consumed.

    Simulator recordings have no fetch-time manifest (unlike UAH-DriveSet,
    which pins its archive digest) — this is the nearest equivalent: a
    digest over the sorted, concatenated raw file contents actually loaded.
    """
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def featurise_sim(
    *,
    sim_root: Path,
    output_dir: Path,
    sha: str | None,
    generated_at: str,
) -> CorpusSummary:
    paths = sim_adapter.find_recordings(sim_root)
    if not paths:
        return CorpusSummary(
            corpus="sim",
            output_path=None,
            recording_count=0,
            kept_windows=0,
            rejected_windows=0,
            label_counts=Counter(),
            driver_window_counts=Counter(),
            missing_prerequisites=[
                f"no simulator recordings (*.jsonl + *.meta.json) found under {sim_root}"
            ],
        )

    dataset_sha256 = _sha256_of_files(paths)
    recordings = sim_adapter.load_recordings(paths)

    rows: list[dict[str, object]] = []
    kept = 0
    rejected = 0
    driver_window_counts: Counter[str] = Counter()
    rubric_label_counts: Counter[str] = Counter()
    variant_window_counts: Counter[str] = Counter()

    for recording in recordings:
        meta = recording.meta
        recording_rows, recording_kept, recording_rejected = _windows_to_rows(
            corpus="sim",
            driver_id=meta.driver_id,
            recording_id=meta.recording_id,
            road_type=None,
            speed_limit_kph=DEFAULT_SPEED_LIMIT_KPH,
            samples=recording.samples,
            sample_rate_hz=meta.sample_rate_hz,
            uah_label=None,
            sha=sha,
            dataset_sha256=dataset_sha256,
            generated_at=generated_at,
        )
        rows.extend(recording_rows)
        kept += recording_kept
        rejected += recording_rejected
        driver_window_counts[meta.driver_id or "unknown"] += recording_kept
        # `pipelines.split` owns this parse: the same rule decides what counts
        # as one drive here and what stays on one side of a fold there, and two
        # copies of it would be free to drift apart.
        variant_window_counts[drive_variant(meta.recording_id)] += recording_kept
        for row in recording_rows:
            rubric_label_counts[str(row["rubric_label"])] += 1

    output_path = None
    if rows:
        output_path = output_dir / f"features_sim_v{FEATURE_VERSION}.parquet"
        _write_parquet(rows, output_path)

    missing: list[str] = []
    skipped_recordings = len(paths) - len(recordings)
    if skipped_recordings:
        missing.append(
            f"{skipped_recordings} simulator recording(s) failed to parse and were skipped"
        )

    return CorpusSummary(
        corpus="sim",
        output_path=output_path,
        recording_count=len(recordings),
        kept_windows=kept,
        rejected_windows=rejected,
        label_counts=Counter(),  # no ground-truth label exists for simulator rows
        driver_window_counts=driver_window_counts,
        rubric_label_counts=rubric_label_counts,
        variant_window_counts=variant_window_counts,
        missing_prerequisites=missing,
    )


# --- Report -----------------------------------------------------------------


def _label_table(counts: Counter[str]) -> str:
    if not counts:
        return "_no labels available_\n"
    total = sum(counts.values())
    lines = ["| label | windows | share |", "| --- | --- | --- |"]
    for label, count in counts.most_common():
        lines.append(f"| {label} | {count} | {count / total:.1%} |")
    return "\n".join(lines) + "\n"


def _driver_table(counts: Counter[str]) -> str:
    if not counts:
        return "_no windows_\n"
    lines = ["| driver | windows |", "| --- | --- |"]
    for driver, count in sorted(counts.items()):
        lines.append(f"| {driver} | {count} |")
    lines.append(f"| **total** | **{sum(counts.values())}** |")
    return "\n".join(lines) + "\n"


def write_report(
    summaries: list[CorpusSummary],
    *,
    path: Path,
    sha: str | None,
    generated_at: str,
) -> None:
    lines = [
        "# M7 dataset summary",
        "",
        "Generated by `python -m pipelines.featurise`. Row counts and class balance"
        " only — the underlying Parquet files are gitignored (`data/**`), so this is"
        " what a reviewer without the data can check.",
        "",
        f"- feature version: `{FEATURE_VERSION}`",
        f"- git sha: `{sha or 'unknown'}`",
        f"- coverage_ratio threshold: `{COVERAGE_RATIO_THRESHOLD}`",
        f"- generated at: `{generated_at}`",
        "",
    ]

    for summary in summaries:
        lines.append(f"## {summary.corpus}")
        lines.append("")
        if summary.output_path is None and not summary.kept_windows:
            for note in summary.missing_prerequisites:
                lines.append(f"**Missing prerequisite:** {note}")
            lines.append("")
            continue

        output_name = summary.output_path.name if summary.output_path else "n/a"
        lines.append(f"- output file: `{output_name}`")
        lines.append(f"- recordings loaded: {summary.recording_count}")
        lines.append(f"- windows kept: {summary.kept_windows}")
        lines.append(
            f"- windows rejected (coverage_ratio < {COVERAGE_RATIO_THRESHOLD}): "
            f"{summary.rejected_windows}"
        )
        lines.append(f"- coverage-rejection rate: {summary.rejection_rate:.1%}")
        lines.append("")
        lines.append("### Rubric class balance (the training label)")
        lines.append("")
        lines.append(_label_table(summary.rubric_label_counts))
        if summary.label_counts:
            lines.append("### Corpus's own labels (validation reference only)")
            lines.append("")
            lines.append(_label_table(summary.label_counts))
        lines.append("### Windows per driver")
        lines.append("")
        lines.append(_driver_table(summary.driver_window_counts))
        if summary.variant_window_counts:
            lines.append("### Windows per scripted drive variant")
            lines.append("")
            lines.append(_driver_table(summary.variant_window_counts))
        for note in summary.missing_prerequisites:
            lines.append(f"**Note:** {note}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# --- Entry point --------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Window and featurise the UAH and simulator corpora into Parquet."
    )
    parser.add_argument("--corpus", choices=["uah", "sim", "all"], default="all")
    parser.add_argument("--uah-root", type=Path, default=DEFAULT_UAH_ROOT)
    parser.add_argument("--uah-manifest", type=Path, default=DEFAULT_UAH_MANIFEST)
    parser.add_argument("--sim-root", type=Path, default=DEFAULT_SIM_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args(argv)

    sha = git_sha()
    generated_at = datetime.now(UTC).isoformat()

    summaries: list[CorpusSummary] = []
    if args.corpus in ("uah", "all"):
        summaries.append(
            featurise_uah(
                uah_root=args.uah_root,
                manifest_path=args.uah_manifest,
                output_dir=args.output_dir,
                sha=sha,
                generated_at=generated_at,
            )
        )
    if args.corpus in ("sim", "all"):
        summaries.append(
            featurise_sim(
                sim_root=args.sim_root,
                output_dir=args.output_dir,
                sha=sha,
                generated_at=generated_at,
            )
        )

    write_report(summaries, path=args.report_path, sha=sha, generated_at=generated_at)

    for summary in summaries:
        print(
            f"{summary.corpus}: {summary.kept_windows} windows kept, "
            f"{summary.rejected_windows} rejected "
            f"({summary.rejection_rate:.1%} rejection rate), "
            f"-> {summary.output_path or '(no file written)'}"
        )
        for note in summary.missing_prerequisites:
            print(f"  note: {note}", file=sys.stderr)
    print(f"wrote {args.report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
