"""Leave-one-variant-out grouped k-fold assignment, and its committed manifest.

    python -m pipelines.split                 # write ml/configs/fold_manifest_v1.json
    python -m pipelines.split --check         # verify the committed manifest still fits the data

`docs/architecture.md` and ADR 0006 both require train/test splits **by trip
and by driver profile, never by row**. This module implements the stronger of
the two readings, for a reason the corpus itself forces:

The simulator corpus is `profile x variant x seed`, and the seed axis varies
`sensor_noise_seed` only — identical physics, identical script, different
measurement noise (see `pipelines.generate_sim_recordings`). Splitting by
*recording* would therefore put `aggressive-b-seed1100` in train and
`aggressive-b-seed1101` in test: two recordings of the same authored drive,
differing only in noise. That satisfies the letter of "split by trip" while
leaking the thing the split exists to prevent. The group here is consequently
the **variant** (`aggressive-b`), i.e. the authored script, and every
recording and window derived from it moves as one unit.

The fold structure is a partition, not a sample: each variant is held out in
exactly one fold, so the union of the test folds is the whole corpus and every
window has exactly one out-of-fold prediction. Variants are round-robined
across folds *within each profile*, so every fold's test set contains all four
classes rather than leaving a fold unable to score one of them.

`n_folds` may not exceed the smallest per-profile variant count (3 here:
calm/normal/aggressive have variants a-c, high_risk has a-d), or some fold
would hold out no variant at all for that class. The extra `high_risk`
variant simply lands in whichever fold the rotation reaches first — folds are
deliberately allowed to be uneven in size rather than dropping data to
balance them.

The manifest this writes is committed. It is not a cache: it pins which
variants sat on which side of which fold when the reported metrics were
produced, so a later corpus change shows up as a verification failure rather
than as silently different numbers.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pipelines.fetch_uah import git_sha

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SIM_PARQUET = REPO_ROOT / "data" / "processed" / "features_sim_v1.parquet"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "ml" / "configs" / "fold_manifest_v1.json"

MANIFEST_VERSION = "1"

# The four behaviour classes, in one fixed order used for every confusion
# matrix, coefficient row and per-class table in M8. Alphabetical is also what
# scikit-learn's `classes_` gives, so the two never drift apart.
CLASS_ORDER: tuple[str, ...] = ("AGGRESSIVE", "CALM", "HIGH_RISK", "NORMAL")

# Simulator profile name -> the class the script was authored to produce.
# This is the drive's *intent*, not its label: the rubric is the label of
# record (ADR 0006), and whether the two agree is the empirical question
# `ml/reports/m7b-simulator-generation-pilot-and-bulk.md` measures.
INTENT_BY_PROFILE: dict[str, str] = {
    "calm": "CALM",
    "normal": "NORMAL",
    "aggressive": "AGGRESSIVE",
    "high_risk": "HIGH_RISK",
}

# `sim-demo` is a pre-existing M2 demo artefact with no profile, no variant and
# no scripted intent — it contributes exactly one window. It is excluded from
# training, from every fold and from every reported metric, because a grouped
# split has nowhere to put a group of one that belongs to no class (M7b TODO 4).
EXCLUDED_RECORDING_IDS: tuple[str, ...] = ("sim-demo",)


class SplitError(RuntimeError):
    """The requested split cannot be built, or the manifest no longer fits the data."""


def drive_variant(recording_id: str) -> str:
    """`high_risk-c-seed1204` -> `high_risk-c`; anything else unchanged.

    The simulator encodes profile, variant and seed in the trip id (see
    `drivesense_sim.__main__.default_trip_id`). Only the profile+variant part
    identifies the *script*, which is the unit that has to stay on one side of
    a split — seeds of one script are the same driving with different noise.
    """
    parts = recording_id.rsplit("-", 1)
    if len(parts) == 2 and parts[1].startswith("seed"):
        return parts[0]
    return recording_id


def variant_profile(variant: str) -> str:
    """`high_risk-c` -> `high_risk`. Returns the variant unchanged if it has no suffix."""
    parts = variant.rsplit("-", 1)
    if len(parts) == 2 and parts[0] in INTENT_BY_PROFILE:
        return parts[0]
    return variant


def variant_intent(variant: str) -> str | None:
    """The class `variant`'s script was authored to produce, or None if unknown."""
    return INTENT_BY_PROFILE.get(variant_profile(variant))


def add_split_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with `variant`, `profile` and `intent` derived from `recording_id`."""
    out = frame.copy()
    out["variant"] = out["recording_id"].map(drive_variant)
    out["profile"] = out["variant"].map(variant_profile)
    out["intent"] = out["variant"].map(variant_intent)
    return out


def drop_excluded(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop recordings that have no home in a grouped split (see EXCLUDED_RECORDING_IDS)."""
    return frame[~frame["recording_id"].isin(EXCLUDED_RECORDING_IDS)].reset_index(drop=True)


@dataclass(frozen=True)
class Fold:
    index: int
    test_variants: tuple[str, ...]
    test_recordings: tuple[str, ...]
    test_windows: int


@dataclass(frozen=True)
class FoldManifest:
    manifest_version: str
    n_folds: int
    variant_shuffle_seed: int
    excluded_recordings: tuple[str, ...]
    folds: tuple[Fold, ...]
    generated_at: str
    git_sha: str | None
    source_parquet: str

    @property
    def all_test_variants(self) -> list[str]:
        return [variant for fold in self.folds for variant in fold.test_variants]


def assign_variants_to_folds(
    variants_by_profile: dict[str, list[str]],
    *,
    n_folds: int,
    seed: int,
) -> list[list[str]]:
    """Round-robin each profile's variants across folds; every variant lands in exactly one.

    The rotation runs per profile so each fold receives at least one variant of
    every class. Profiles with more variants than folds contribute more than one
    variant to some fold; that is preferred to discarding a variant to keep the
    folds even, since `high_risk`'s fourth variant exists precisely because the
    class is scarce.
    """
    if n_folds < 2:
        raise SplitError(f"n_folds must be at least 2, got {n_folds}")

    for profile, variants in sorted(variants_by_profile.items()):
        if len(variants) < n_folds:
            raise SplitError(
                f"profile {profile!r} has {len(variants)} variant(s) but n_folds={n_folds}: "
                "some fold would hold out no variant of that class and could not score it"
            )

    folds: list[list[str]] = [[] for _ in range(n_folds)]
    for profile, variants in sorted(variants_by_profile.items()):
        order = sorted(variants)
        # Seeded per profile so each class's rotation is independent, and so the
        # whole assignment is reproducible from the single seed in the config.
        random.Random(f"{seed}:{profile}").shuffle(order)
        for position, variant in enumerate(order):
            folds[position % n_folds].append(variant)
    return [sorted(fold) for fold in folds]


def build_manifest(
    frame: pd.DataFrame,
    *,
    n_folds: int,
    seed: int,
    source_parquet: Path,
    generated_at: str | None = None,
    sha: str | None = None,
) -> FoldManifest:
    """Build a fold manifest from an already-featurised simulator frame."""
    prepared = add_split_columns(drop_excluded(frame))

    unknown = sorted(set(prepared.loc[prepared["intent"].isna(), "variant"]))
    if unknown:
        raise SplitError(
            f"{len(unknown)} variant(s) map to no known profile and cannot be assigned "
            f"to a class-balanced fold: {unknown}"
        )

    variants_by_profile: dict[str, list[str]] = defaultdict(list)
    for profile, variant in sorted(set(zip(prepared["profile"], prepared["variant"], strict=True))):
        variants_by_profile[profile].append(variant)

    assignment = assign_variants_to_folds(dict(variants_by_profile), n_folds=n_folds, seed=seed)

    folds: list[Fold] = []
    for index, test_variants in enumerate(assignment):
        rows = prepared[prepared["variant"].isin(test_variants)]
        folds.append(
            Fold(
                index=index,
                test_variants=tuple(test_variants),
                test_recordings=tuple(sorted(set(rows["recording_id"]))),
                test_windows=int(len(rows)),
            )
        )

    return FoldManifest(
        manifest_version=MANIFEST_VERSION,
        n_folds=n_folds,
        variant_shuffle_seed=seed,
        excluded_recordings=EXCLUDED_RECORDING_IDS,
        folds=tuple(folds),
        generated_at=generated_at or datetime.now(UTC).isoformat(),
        git_sha=sha if sha is not None else git_sha(),
        source_parquet=source_parquet.name,
    )


def manifest_to_dict(manifest: FoldManifest) -> dict[str, Any]:
    return {
        "manifest_version": manifest.manifest_version,
        "n_folds": manifest.n_folds,
        "variant_shuffle_seed": manifest.variant_shuffle_seed,
        "excluded_recordings": list(manifest.excluded_recordings),
        "source_parquet": manifest.source_parquet,
        "generated_at": manifest.generated_at,
        "git_sha": manifest.git_sha,
        "folds": [
            {
                "fold": fold.index,
                "test_variants": list(fold.test_variants),
                "test_recordings": list(fold.test_recordings),
                "test_windows": fold.test_windows,
            }
            for fold in manifest.folds
        ],
    }


def manifest_from_dict(payload: dict[str, Any]) -> FoldManifest:
    folds = tuple(
        Fold(
            index=int(entry["fold"]),
            test_variants=tuple(str(value) for value in entry["test_variants"]),
            test_recordings=tuple(str(value) for value in entry["test_recordings"]),
            test_windows=int(entry["test_windows"]),
        )
        for entry in payload["folds"]
    )
    return FoldManifest(
        manifest_version=str(payload["manifest_version"]),
        n_folds=int(payload["n_folds"]),
        variant_shuffle_seed=int(payload["variant_shuffle_seed"]),
        excluded_recordings=tuple(str(value) for value in payload["excluded_recordings"]),
        folds=folds,
        generated_at=str(payload["generated_at"]),
        git_sha=None if payload["git_sha"] is None else str(payload["git_sha"]),
        source_parquet=str(payload["source_parquet"]),
    )


def write_manifest(manifest: FoldManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest_to_dict(manifest), indent=2) + "\n",
        encoding="utf-8",
    )


def read_manifest(path: Path) -> FoldManifest:
    return manifest_from_dict(json.loads(path.read_text(encoding="utf-8")))


def verify_manifest(manifest: FoldManifest, frame: pd.DataFrame) -> None:
    """Raise `SplitError` unless the manifest still describes exactly this corpus.

    Checks the three properties the reported metrics depend on: every variant
    is held out exactly once (a partition, so out-of-fold predictions cover the
    corpus), no variant spans both sides of any fold, and the manifest's
    variants are the corpus's variants.
    """
    prepared = add_split_columns(drop_excluded(frame))
    data_variants = set(prepared["variant"])
    listed = manifest.all_test_variants

    duplicated = sorted({variant for variant in listed if listed.count(variant) > 1})
    if duplicated:
        raise SplitError(f"variant(s) held out in more than one fold: {duplicated}")

    missing = sorted(data_variants - set(listed))
    extra = sorted(set(listed) - data_variants)
    if missing or extra:
        raise SplitError(
            "manifest does not match the corpus — "
            f"variants in data but not in manifest: {missing}; "
            f"variants in manifest but not in data: {extra}. "
            "Regenerate with `python -m pipelines.split`, and re-run training: "
            "the committed metrics were produced against the old split."
        )

    for fold in manifest.folds:
        test_mask = prepared["variant"].isin(fold.test_variants)
        overlap = sorted(
            set(prepared.loc[test_mask, "variant"]) & set(prepared.loc[~test_mask, "variant"])
        )
        if overlap:
            raise SplitError(f"fold {fold.index}: variant(s) on both sides of the split: {overlap}")


def fold_indices(
    frame: pd.DataFrame,
    manifest: FoldManifest,
) -> list[tuple[int, pd.Series[bool]]]:
    """(fold index, boolean test mask) per fold, aligned to `frame`'s own index."""
    prepared = add_split_columns(frame)
    return [(fold.index, prepared["variant"].isin(fold.test_variants)) for fold in manifest.folds]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assign simulator drive variants to leave-one-variant-out folds."
    )
    parser.add_argument("--sim-parquet", type=Path, default=DEFAULT_SIM_PARQUET)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--n-folds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260810)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed manifest against the corpus instead of rewriting it",
    )
    args = parser.parse_args(argv)

    if not args.sim_parquet.is_file():
        print(
            f"missing {args.sim_parquet} — run `python -m pipelines.featurise --corpus sim` first"
        )
        return 1

    frame = pd.read_parquet(args.sim_parquet)

    if args.check:
        manifest = read_manifest(args.manifest_path)
        verify_manifest(manifest, frame)
        print(f"{args.manifest_path.name}: {manifest.n_folds} folds, split verified against corpus")
        return 0

    manifest = build_manifest(
        frame,
        n_folds=args.n_folds,
        seed=args.seed,
        source_parquet=args.sim_parquet,
    )
    verify_manifest(manifest, frame)
    write_manifest(manifest, args.manifest_path)

    print(f"wrote {args.manifest_path}")
    for fold in manifest.folds:
        print(
            f"  fold {fold.index}: {len(fold.test_variants)} variants, "
            f"{len(fold.test_recordings)} recordings, {fold.test_windows} windows "
            f"({', '.join(fold.test_variants)})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
