"""Split tests — chiefly the leak guard.

The property under test is the one every M8 number depends on: **no drive
variant appears on both sides of any fold**. If it did, the model would be
scored on 50%-overlapping windows from a script it had already fitted, and the
reported metrics would measure memorisation. That is not a hypothetical failure
mode for this corpus — six recordings of one variant differ only in
`sensor_noise_seed`, so a naive per-recording split leaks by construction.

These build synthetic frames rather than reading the real Parquet: the data is
gitignored, and the invariants here are properties of the assignment logic, not
of any particular corpus.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
import yaml

from pipelines.split import (
    CLASS_ORDER,
    EXCLUDED_RECORDING_IDS,
    SplitError,
    add_split_columns,
    assign_variants_to_folds,
    build_manifest,
    drive_variant,
    drop_excluded,
    read_manifest,
    variant_intent,
    variant_profile,
    verify_manifest,
    write_manifest,
)

PROFILES = {
    "calm": ["a", "b", "c"],
    "normal": ["a", "b", "c"],
    "aggressive": ["a", "b", "c"],
    "high_risk": ["a", "b", "c", "d"],
}
LABEL_BY_PROFILE = {
    "calm": "CALM",
    "normal": "NORMAL",
    "aggressive": "AGGRESSIVE",
    "high_risk": "HIGH_RISK",
}


def _corpus(seeds_per_variant: int = 3, windows_per_recording: int = 4) -> pd.DataFrame:
    """A frame shaped like `features_sim_v1.parquet`'s split-relevant columns."""
    rows: list[dict[str, object]] = []
    for profile, variants in PROFILES.items():
        for variant in variants:
            for seed in range(seeds_per_variant):
                recording_id = f"{profile}-{variant}-seed{1000 + seed}"
                for index in range(windows_per_recording):
                    rows.append(
                        {
                            "window_id": f"{recording_id}::{index:04d}",
                            "recording_id": recording_id,
                            "rubric_label": LABEL_BY_PROFILE[profile],
                        }
                    )
    rows.append(
        {"window_id": "sim-demo::0000", "recording_id": "sim-demo", "rubric_label": "NORMAL"}
    )
    return pd.DataFrame(rows)


# --- Recording-id parsing ------------------------------------------------------


def test_drive_variant_strips_the_seed_suffix_only() -> None:
    assert drive_variant("high_risk-c-seed1204") == "high_risk-c"
    assert drive_variant("aggressive-a-seed1000") == "aggressive-a"
    # No seed suffix: nothing to strip. `sim-demo` must not become `sim`.
    assert drive_variant("sim-demo") == "sim-demo"


def test_variant_profile_and_intent() -> None:
    assert variant_profile("high_risk-c") == "high_risk"
    assert variant_intent("high_risk-c") == "HIGH_RISK"
    assert variant_intent("calm-a") == "CALM"
    # An unknown profile has no intent rather than a guessed one.
    assert variant_intent("sim-demo") is None


# --- The leak guard ------------------------------------------------------------


def test_no_variant_spans_both_sides_of_any_fold() -> None:
    frame = _corpus()
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("f.parquet"))
    prepared = add_split_columns(drop_excluded(frame))

    for fold in manifest.folds:
        test_mask = prepared["variant"].isin(fold.test_variants)
        train_variants = set(prepared.loc[~test_mask, "variant"])
        test_variants = set(prepared.loc[test_mask, "variant"])
        assert not (train_variants & test_variants), (
            f"fold {fold.index} leaks variant(s): {sorted(train_variants & test_variants)}"
        )


def test_no_recording_spans_both_sides_of_any_fold() -> None:
    """The weaker per-recording property, checked too: variants contain whole recordings."""
    frame = _corpus()
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("f.parquet"))
    prepared = add_split_columns(drop_excluded(frame))

    for fold in manifest.folds:
        test_mask = prepared["variant"].isin(fold.test_variants)
        overlap = set(prepared.loc[~test_mask, "recording_id"]) & set(
            prepared.loc[test_mask, "recording_id"]
        )
        assert not overlap, f"fold {fold.index} leaks recording(s): {sorted(overlap)}"


def test_no_window_spans_both_sides_of_any_fold() -> None:
    frame = _corpus()
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("f.parquet"))
    prepared = add_split_columns(drop_excluded(frame))

    for fold in manifest.folds:
        test_mask = prepared["variant"].isin(fold.test_variants)
        overlap = set(prepared.loc[~test_mask, "window_id"]) & set(
            prepared.loc[test_mask, "window_id"]
        )
        assert not overlap


# --- Partition and coverage -----------------------------------------------------


def test_every_variant_is_held_out_exactly_once() -> None:
    frame = _corpus()
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("f.parquet"))
    held_out = manifest.all_test_variants

    assert len(held_out) == len(set(held_out)), "a variant is held out in more than one fold"
    prepared = add_split_columns(drop_excluded(frame))
    assert set(held_out) == set(prepared["variant"])


def test_test_folds_partition_the_corpus() -> None:
    """Union of the test folds is the whole corpus, so every window gets one OOF prediction."""
    frame = _corpus()
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("f.parquet"))
    prepared = add_split_columns(drop_excluded(frame))

    assert sum(fold.test_windows for fold in manifest.folds) == len(prepared)


def test_every_fold_contains_every_class() -> None:
    """A fold missing a class could not score it — that is why the rotation is per profile."""
    frame = _corpus()
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("f.parquet"))
    prepared = add_split_columns(drop_excluded(frame))

    for fold in manifest.folds:
        rows = prepared[prepared["variant"].isin(fold.test_variants)]
        assert set(rows["rubric_label"]) == set(CLASS_ORDER), (
            f"fold {fold.index} cannot score every class: {sorted(set(rows['rubric_label']))}"
        )


def test_sim_demo_is_excluded_from_every_fold() -> None:
    frame = _corpus()
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("f.parquet"))

    assert "sim-demo" not in manifest.all_test_variants
    for fold in manifest.folds:
        assert "sim-demo" not in fold.test_recordings
    assert "sim-demo" in EXCLUDED_RECORDING_IDS
    assert "sim-demo" not in set(drop_excluded(frame)["recording_id"])


# --- Assignment mechanics --------------------------------------------------------


def _variants() -> dict[str, list[str]]:
    return {profile: [f"{profile}-{v}" for v in variants] for profile, variants in PROFILES.items()}


def test_assignment_is_deterministic_for_a_seed() -> None:
    variants = _variants()
    assert assign_variants_to_folds(variants, n_folds=3, seed=7) == assign_variants_to_folds(
        variants, n_folds=3, seed=7
    )


def test_a_different_seed_can_produce_a_different_assignment() -> None:
    variants = _variants()
    assignments = {
        tuple(tuple(fold) for fold in assign_variants_to_folds(variants, n_folds=3, seed=seed))
        for seed in range(12)
    }
    assert len(assignments) > 1, "the seed does not affect the assignment at all"


def test_more_folds_than_variants_is_rejected() -> None:
    with pytest.raises(SplitError, match="could not score it"):
        assign_variants_to_folds(_variants(), n_folds=4, seed=1)


def test_a_single_fold_is_rejected() -> None:
    with pytest.raises(SplitError, match="at least 2"):
        assign_variants_to_folds(_variants(), n_folds=1, seed=1)


# --- Manifest round-trip and verification -----------------------------------------


def test_manifest_round_trips_through_json(tmp_path: Path) -> None:
    frame = _corpus()
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("f.parquet"))
    path = tmp_path / "fold_manifest.json"
    write_manifest(manifest, path)

    assert read_manifest(path) == manifest
    # Committed artefact: it must be readable as plain JSON by a human or a tool.
    assert json.loads(path.read_text(encoding="utf-8"))["n_folds"] == 3


def test_verify_rejects_a_manifest_missing_a_variant_the_corpus_has(tmp_path: Path) -> None:
    frame = _corpus()
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("f.parquet"))

    extra = frame.copy()
    extra.loc[len(extra)] = {
        "window_id": "calm-z-seed1000::0000",
        "recording_id": "calm-z-seed1000",
        "rubric_label": "CALM",
    }
    with pytest.raises(SplitError, match="does not match the corpus"):
        verify_manifest(manifest, extra)


def test_verify_rejects_a_variant_held_out_twice() -> None:
    frame = _corpus()
    manifest = build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("f.parquet"))
    duplicated = manifest.folds[0].test_variants[0]
    leaky_fold = replace(
        manifest.folds[1], test_variants=manifest.folds[1].test_variants + (duplicated,)
    )
    broken = replace(manifest, folds=(manifest.folds[0], leaky_fold, *manifest.folds[2:]))

    with pytest.raises(SplitError, match="more than one fold"):
        verify_manifest(broken, frame)


def test_build_rejects_a_variant_with_no_known_profile() -> None:
    frame = _corpus()
    frame.loc[len(frame)] = {
        "window_id": "mystery-a-seed1000::0000",
        "recording_id": "mystery-a-seed1000",
        "rubric_label": "NORMAL",
    }
    with pytest.raises(SplitError, match="no known profile"):
        build_manifest(frame, n_folds=3, seed=1, source_parquet=Path("f.parquet"))


def test_the_committed_manifest_matches_the_committed_config() -> None:
    """The shipped manifest must be the one the shipped config describes."""
    repo_root = Path(__file__).resolve().parents[2]
    manifest_path = repo_root / "ml" / "configs" / "fold_manifest_v1.json"
    config_path = repo_root / "ml" / "configs" / "train_v1.yaml"
    if not manifest_path.is_file():
        pytest.skip("no committed fold manifest yet — run `python -m pipelines.split`")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    manifest = read_manifest(manifest_path)

    assert manifest.n_folds == config["split"]["n_folds"]
    assert manifest.variant_shuffle_seed == config["variant_shuffle_seed"]
    held_out = manifest.all_test_variants
    assert len(held_out) == len(set(held_out))
