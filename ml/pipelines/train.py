"""Train the M8 baselines and the shipped model, and write the committed report.

    python -m pipelines.train                      # full run: folds, artefact, report
    python -m pipelines.train --skip-uah           # simulator folds only

What this runs, and why each piece is there:

**Three models, one split.** A majority-class baseline (the floor), a
multinomial logistic regression (`ml/README.md`'s stated bar), and a small
decision tree (the "can anything beat it" comparison). All three see exactly
the same folds, so their numbers are comparable by construction rather than by
assertion.

**Leave-one-variant-out cross-validation, not a single split.** Held-out
variants are whole authored drives (`pipelines.split`), and with three or four
per class a single held-out variant per class is a very small, very
lumpy test set — one unusual script would move the headline number more than
the model would. Rotating every variant through the test position uses every
window as test data exactly once and, more usefully, exposes how much the
score *moves* between scripts. That spread is reported alongside every mean,
because it is the honest width of the claim.

**The shipped artefact is refitted on everything.** `model.json` is a final
logistic regression fitted on every simulator window with no fold held out
— the cross-validated numbers estimate how that model generalises, they are
not measurements of it. This is stated in the report and the model card rather
than left implicit. The alternative (ensembling the three fold models) would
produce an artefact whose behaviour no reported metric describes.

**The tree is scored but not shipped.** `model.json`'s format is a coefficient
dump (`pipelines.artifact`); a tree would need a different serialisation. If
the tree wins by a margin worth having, that is a finding for the report to
state and for a follow-up to act on — not something to resolve silently by
swapping the artefact format mid-run.

**UAH is scored separately and never trained on.** No UAH row enters any fold
(ADR 0006). It is evaluated once, at the end, with the final model, against
`rubric_label` — and the report states plainly what that does and does not
prove.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import yaml
from app.core.features import FEATURE_NAMES, FEATURE_VERSION
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from pipelines import evaluate as ev
from pipelines.artifact import (
    MODEL_FORMAT,
    MODEL_FORMAT_VERSION,
    predict,
    read_model_json,
    serialise_logistic_regression,
    write_model_json,
)
from pipelines.fetch_uah import git_sha
from pipelines.split import (
    CLASS_ORDER,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_SIM_PARQUET,
    EXCLUDED_RECORDING_IDS,
    FoldManifest,
    add_split_columns,
    build_manifest,
    drop_excluded,
    read_manifest,
    verify_manifest,
    write_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG_PATH = REPO_ROOT / "ml" / "configs" / "train_v1.yaml"
DEFAULT_UAH_PARQUET = REPO_ROOT / "data" / "processed" / "features_uah_v1.parquet"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "ml" / "artifacts"
DEFAULT_REPORT_PATH = REPO_ROOT / "ml" / "reports" / "m8-evaluation.md"

LABEL_COLUMN = "rubric_label"

MAJORITY_MODEL = "majority-class baseline"
LOGREG_MODEL = "logistic regression"
TREE_MODEL = "decision tree"


# --- Configuration -----------------------------------------------------------


@dataclass(frozen=True)
class TrainConfig:
    config_version: int
    variant_shuffle_seed: int
    model_random_state: int
    n_folds: int
    excluded_features: dict[str, str]
    logistic_regression: dict[str, Any]
    decision_tree: dict[str, Any]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def feature_names(self) -> list[str]:
        """The shared feature list (ADR 0004) minus this config's exclusions, in order."""
        return [name for name in FEATURE_NAMES if name not in self.excluded_features]


def load_config(path: Path) -> TrainConfig:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    excluded: dict[str, str] = {
        name: " ".join(str(reason).split())
        for name, reason in (raw.get("features", {}).get("exclude") or {}).items()
    }
    unknown = sorted(set(excluded) - set(FEATURE_NAMES))
    if unknown:
        raise ValueError(f"config excludes feature(s) that do not exist: {unknown}")
    return TrainConfig(
        config_version=int(raw["config_version"]),
        variant_shuffle_seed=int(raw["variant_shuffle_seed"]),
        model_random_state=int(raw["model_random_state"]),
        n_folds=int(raw["split"]["n_folds"]),
        excluded_features=excluded,
        logistic_regression=dict(raw["models"]["logistic_regression"]),
        decision_tree=dict(raw["models"]["decision_tree"]),
        raw=raw,
    )


# --- Model construction -------------------------------------------------------


def build_logistic_regression(config: TrainConfig) -> Pipeline:
    """Standardise, then fit multinomial logistic regression.

    Standardisation is not cosmetic here: the features span `brake_time_ratio`
    in [0, 1] and `speed_max` in the tens, and an L2 penalty on unstandardised
    coefficients penalises them by unit rather than by importance.
    """
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "logreg",
                LogisticRegression(
                    random_state=config.model_random_state,
                    **config.logistic_regression,
                ),
            ),
        ]
    )


def build_decision_tree(config: TrainConfig) -> DecisionTreeClassifier:
    return DecisionTreeClassifier(
        random_state=config.model_random_state,
        **config.decision_tree,
    )


def _matrix(frame: pd.DataFrame, feature_names: list[str]) -> npt.NDArray[np.float64]:
    return np.asarray(frame[feature_names].to_numpy(dtype=np.float64))


def _labels(frame: pd.DataFrame, column: str = LABEL_COLUMN) -> list[str]:
    return [str(value) for value in frame[column]]


# --- Cross-validation ---------------------------------------------------------


@dataclass
class FoldRun:
    """Per-model metrics for every fold, plus one out-of-fold prediction per window."""

    summaries: dict[str, ev.FoldSummary]
    out_of_fold: dict[str, list[str]]
    fold_sizes: list[int]


def run_cross_validation(
    frame: pd.DataFrame,
    manifest: FoldManifest,
    config: TrainConfig,
) -> FoldRun:
    feature_names = config.feature_names
    prepared = add_split_columns(frame)
    features = _matrix(prepared, feature_names)
    truth = _labels(prepared)

    per_model_folds: dict[str, list[ev.Metrics]] = {
        MAJORITY_MODEL: [],
        LOGREG_MODEL: [],
        TREE_MODEL: [],
    }
    # Folds partition the corpus, so every window gets exactly one prediction
    # from a model that never saw its variant. Pre-filled with "" so a gap
    # would be visible rather than silently defaulting to a real class.
    out_of_fold: dict[str, list[str]] = {
        LOGREG_MODEL: [""] * len(prepared),
        TREE_MODEL: [""] * len(prepared),
    }
    fold_sizes: list[int] = []

    for fold in manifest.folds:
        test_mask = prepared["variant"].isin(fold.test_variants).to_numpy()
        train_mask = ~test_mask
        fold_sizes.append(int(test_mask.sum()))

        train_x, test_x = features[train_mask], features[test_mask]
        train_y = [label for label, keep in zip(truth, train_mask, strict=True) if keep]
        test_y = [label for label, keep in zip(truth, test_mask, strict=True) if keep]

        # The honest baseline knows only the training fold's class balance.
        majority = ev.majority_label_of(train_y)
        name = str(fold.index)

        per_model_folds[MAJORITY_MODEL].append(
            ev.evaluate_predictions(
                test_y, [majority] * len(test_y), name=name, majority_label=majority
            )
        )

        logreg = build_logistic_regression(config)
        logreg.fit(train_x, train_y)
        logreg_pred = [str(value) for value in logreg.predict(test_x)]
        per_model_folds[LOGREG_MODEL].append(
            ev.evaluate_predictions(test_y, logreg_pred, name=name, majority_label=majority)
        )

        tree = build_decision_tree(config)
        tree.fit(train_x, train_y)
        tree_pred = [str(value) for value in tree.predict(test_x)]
        per_model_folds[TREE_MODEL].append(
            ev.evaluate_predictions(test_y, tree_pred, name=name, majority_label=majority)
        )

        test_positions = [position for position, keep in enumerate(test_mask) if keep]
        for offset, position in enumerate(test_positions):
            out_of_fold[LOGREG_MODEL][position] = logreg_pred[offset]
            out_of_fold[TREE_MODEL][position] = tree_pred[offset]

    missing = {model: predictions.count("") for model, predictions in out_of_fold.items()}
    if any(missing.values()):
        raise RuntimeError(
            f"folds do not cover the corpus — windows without an out-of-fold prediction: {missing}"
        )

    return FoldRun(
        summaries={
            model: ev.FoldSummary(name=model, folds=tuple(folds))
            for model, folds in per_model_folds.items()
        },
        out_of_fold=out_of_fold,
        fold_sizes=fold_sizes,
    )


# --- Final artefact -----------------------------------------------------------


def fit_final_logistic_regression(
    frame: pd.DataFrame, config: TrainConfig
) -> tuple[Pipeline, dict[str, Any]]:
    """Fit on the whole simulator corpus and serialise to the `model.json` payload."""
    feature_names = config.feature_names
    features = _matrix(frame, feature_names)
    labels = _labels(frame)

    pipeline = build_logistic_regression(config)
    pipeline.fit(features, labels)

    scaler: StandardScaler = pipeline.named_steps["scaler"]
    logreg: LogisticRegression = pipeline.named_steps["logreg"]

    payload = serialise_logistic_regression(
        scaler_mean=np.asarray(scaler.mean_, dtype=np.float64),
        scaler_scale=np.asarray(scaler.scale_, dtype=np.float64),
        coefficients=np.asarray(logreg.coef_, dtype=np.float64),
        intercepts=np.asarray(logreg.intercept_, dtype=np.float64),
        classes=[str(value) for value in logreg.classes_],
        feature_names=feature_names,
        excluded_features=config.excluded_features,
        metadata={
            "training_majority_class": ev.majority_label_of(labels),
            "training_windows": int(len(frame)),
            "feature_version": FEATURE_VERSION,
            "label_source": (
                "rubric (weak supervision) — see docs/adr/0006-training-label-rubric.md"
            ),
        },
    )

    # The artefact is only useful if it is exactly the fitted model, so this is
    # checked here as well as in the tests: a serialiser that quietly loses a
    # digit would otherwise be discovered by a wrong prediction in production.
    round_tripped = predict(payload, features)
    fitted = [str(value) for value in pipeline.predict(features)]
    if round_tripped != fitted:
        disagreements = sum(1 for a, b in zip(round_tripped, fitted, strict=True) if a != b)
        raise RuntimeError(
            f"model.json round-trip disagrees with the fitted pipeline on "
            f"{disagreements}/{len(fitted)} training windows"
        )

    return pipeline, payload


# --- Report -------------------------------------------------------------------


def _class_balance_table(labels: list[str]) -> str:
    counts = Counter(labels)
    total = sum(counts.values())
    lines = ["| class | windows | share |", "| --- | --- | --- |"]
    for label in CLASS_ORDER:
        count = counts.get(label, 0)
        lines.append(f"| {label} | {count} | {count / total:.1%} |")
    lines.append(f"| **total** | **{total}** | |")
    return "\n".join(lines)


def _majority_share(metrics: ev.Metrics) -> float:
    """Share of the *evaluation set's* own largest class.

    Distinct from `Metrics.majority_accuracy`, which scores the honest baseline:
    always predicting the majority class of the **training** corpus. On UAH the
    two differ a lot, and quoting one where the other is meant makes a model
    look better or worse than it is — so both are stated, side by side.
    """
    if metrics.n_windows == 0:
        return 0.0
    return max(entry.support for entry in metrics.per_class) / metrics.n_windows


def _fold_composition_table(manifest: FoldManifest, prepared: pd.DataFrame) -> str:
    lines = [
        "| fold | held-out variants | recordings | windows | class balance of the held-out fold |",
        "| --- | --- | --- | --- | --- |",
    ]
    for fold in manifest.folds:
        rows = prepared[prepared["variant"].isin(fold.test_variants)]
        counts = Counter(_labels(rows))
        balance = ", ".join(f"{label} {counts.get(label, 0)}" for label in CLASS_ORDER)
        lines.append(
            f"| {fold.index} | {', '.join(fold.test_variants)} | "
            f"{len(fold.test_recordings)} | {fold.test_windows} | {balance} |"
        )
    return "\n".join(lines)


def build_report(
    *,
    config: TrainConfig,
    manifest: FoldManifest,
    prepared: pd.DataFrame,
    run: FoldRun,
    payload: dict[str, Any],
    uah_metrics: dict[str, ev.Metrics] | None,
    uah_frame: pd.DataFrame | None,
    intent_metrics: dict[str, ev.Metrics],
    sha: str | None,
    generated_at: str,
) -> str:
    labels = _labels(prepared)
    summaries = [
        run.summaries[MAJORITY_MODEL],
        run.summaries[LOGREG_MODEL],
        run.summaries[TREE_MODEL],
    ]
    logreg_summary = run.summaries[LOGREG_MODEL]
    tree_summary = run.summaries[TREE_MODEL]

    all_flags: list[str] = []
    for summary in summaries[1:]:
        all_flags.extend(f"{summary.name}, {flag}" for flag in summary.flags)

    lines: list[str] = []
    add = lines.append

    add("# M8 — model training and evaluation")
    add("")
    add(
        "Generated by `python -m pipelines.train`. Every number here comes from that "
        "command; none was typed in by hand. The Parquet inputs are gitignored "
        "(`data/**`), so this report plus `ml/configs/fold_manifest_v1.json` is what a "
        "reviewer without the data can check."
    )
    add("")
    add(f"- config: `ml/configs/train_v1.yaml` (version {config.config_version})")
    add(f"- feature version: `{FEATURE_VERSION}`")
    add(f"- git sha: `{sha or 'unknown'}`")
    add(f"- generated at: `{generated_at}`")
    add("- label source: `rubric_label` — weak supervision (ADR 0006), not ground truth")
    add("")

    add("## 0. Bottom line")
    add("")
    add(
        f"On held-out simulator variants both models comfortably beat the majority-class "
        f"baseline: logistic regression reaches macro-F1 {logreg_summary.macro_f1}, the "
        f"decision tree {tree_summary.macro_f1}, against a baseline of "
        f"{run.summaries[MAJORITY_MODEL].macro_f1}."
    )
    add("")
    if uah_metrics is not None:
        logreg_uah = uah_metrics[LOGREG_MODEL]
        tree_uah = uah_metrics[TREE_MODEL]
        high_risk_index = CLASS_ORDER.index("HIGH_RISK")
        logreg_hr = logreg_uah.per_class[high_risk_index]
        tree_hr = tree_uah.per_class[high_risk_index]
        logreg_hr_hits = logreg_uah.confusion[high_risk_index][high_risk_index]
        tree_hr_hits = tree_uah.confusion[high_risk_index][high_risk_index]

        # Whether the models clear the baseline on real telemetry is the single
        # thing this section exists to state, so it is read off the metrics
        # rather than asserted — a rewritten corpus can flip it either way, and
        # a headline that has to be kept in sync by hand will not be.
        if logreg_uah.beats_majority and tree_uah.beats_majority:
            verdict_sentence = (
                "**On real UAH telemetry, both models beat the majority-class baseline.**"
            )
        elif not logreg_uah.beats_majority and not tree_uah.beats_majority:
            verdict_sentence = (
                "**On real UAH telemetry, neither beats the majority-class baseline.**"
            )
        elif logreg_uah.beats_majority:
            verdict_sentence = (
                "**On real UAH telemetry, only the logistic regression beats the majority-class "
                "baseline.**"
            )
        else:
            verdict_sentence = (
                "**On real UAH telemetry, only the decision tree beats the majority-class "
                "baseline.**"
            )
        add(
            f"{verdict_sentence} The logistic regression scores {logreg_uah.accuracy:.3f} "
            f"accuracy against a baseline of {logreg_uah.majority_accuracy:.3f} "
            f"(macro-F1 {logreg_uah.macro_f1:.3f}); the decision tree scores "
            f"{tree_uah.accuracy:.3f} against the same {tree_uah.majority_accuracy:.3f} "
            f"(macro-F1 {tree_uah.macro_f1:.3f}). This is the central result of M8 and it is "
            "stated first rather than at the end of section 7, because a reader who takes only "
            "one number away should take this one."
        )
        add("")
        add(
            "Note what that baseline is: the majority class *of the training corpus*, which is "
            "the only class an always-guess model could actually know. It is not UAH's own "
            f"majority class, which covers {_majority_share(logreg_uah):.1%} of these windows — "
            "see section 7."
        )
        add("")
        add("Two things follow, and they matter more than the headline simulator scores:")
        add("")
        sim_leader, sim_trailer = (
            (LOGREG_MODEL, TREE_MODEL)
            if logreg_summary.macro_f1.mean >= tree_summary.macro_f1.mean
            else (TREE_MODEL, LOGREG_MODEL)
        )
        uah_leader = LOGREG_MODEL if logreg_uah.macro_f1 >= tree_uah.macro_f1 else TREE_MODEL
        if sim_leader == uah_leader:
            add(
                f"1. **The in-domain winner is also the out-of-domain winner.** The "
                f"{sim_leader} leads on held-out simulator variants (macro-F1 "
                f"{logreg_summary.macro_f1.mean:.3f} vs {tree_summary.macro_f1.mean:.3f}) and "
                f"leads again on UAH ({logreg_uah.macro_f1:.3f} vs {tree_uah.macro_f1:.3f}). "
                "That agreement is worth something, but not much on its own: two folds' worth "
                f"of margin over the {sim_trailer} is well inside the fold-to-fold spread, and "
                "the ranking is not the interesting part of this table. The gap between the "
                "simulator column and the UAH column is."
            )
        else:
            add(
                f"1. **The in-domain winner is the out-of-domain loser.** The {sim_leader} wins "
                f"on the simulator folds (macro-F1 {logreg_summary.macro_f1.mean:.3f} vs "
                f"{tree_summary.macro_f1.mean:.3f}) and then loses on UAH "
                f"({logreg_uah.macro_f1:.3f} vs {tree_uah.macro_f1:.3f}). Its cross-validated "
                "score was not wrong; it simply measured generalisation to unseen *scripts*, "
                "which turns out to say little about generalisation to unseen *driving*."
            )
        add(
            f"2. **The two models fail differently on `HIGH_RISK`, and the difference is the "
            f"whole argument for the one that ships.** Of {logreg_hr.support} `HIGH_RISK` "
            f"windows in UAH the logistic regression recovers {logreg_hr_hits} "
            f"(recall {logreg_uah.high_risk_recall:.3f}) at the cost of predicting the class "
            f"{logreg_hr.predicted} times — precision {logreg_hr.precision:.3f}. The decision "
            f"tree recovers {tree_hr_hits} (recall {tree_uah.high_risk_recall:.3f}) from "
            f"{tree_hr.predicted} predictions. Over-prediction is a tuning problem with a "
            "visible cost; silence on the rarest and most consequential class is a failure "
            "nothing downstream can detect."
        )
        add("")
        add(
            'Section 7 sets out the three reasons this comparison is harder than "unseen data" '
            "— chiefly the simulator/real domain gap, measured there on the two corpora this "
            "run used. None of them make the result better or worse; they bound what it means."
        )
        add("")
        if logreg_uah.beats_majority:
            add(
                f"The honest reading: a model trained only on scripted simulator drives now "
                f"transfers to real telemetry well enough to be measurably better than guessing "
                f"({logreg_uah.macro_f1:.3f} macro-F1 against "
                f"{logreg_uah.majority_accuracy:.3f} accuracy for the baseline), and is still a "
                "long way from usable — `HIGH_RISK` precision of "
                f"{logreg_hr.precision:.3f} is the clearest single statement of that distance. "
                "Transfer being non-zero is a result; it is not a release criterion."
            )
        else:
            add(
                "The honest reading is that a model trained only on scripted simulator drives "
                "does not yet transfer to real telemetry, and `ml/README.md`'s standing "
                "instruction applies: that is a finding worth reporting, not hiding."
            )
        add("")

    add("## 1. What was trained on")
    add("")
    add(
        f"{len(prepared)} simulator windows from {prepared['recording_id'].nunique()} recordings "
        f"across {prepared['variant'].nunique()} authored script variants. "
        f"`{', '.join(EXCLUDED_RECORDING_IDS)}` is excluded outright: it is a pre-existing "
        "M2 demo artefact with no profile and no scripted intent, so a grouped split has "
        "nowhere to put it (M7b TODO 4)."
    )
    add("")
    add(_class_balance_table(labels))
    add("")
    add(
        f"**Features: {len(config.feature_names)} of {len(FEATURE_NAMES)}.** "
        "The excluded ones, and why:"
    )
    add("")
    for name, reason in config.excluded_features.items():
        add(f"- **`{name}`** — {reason}")
    add("")
    add(
        "No UAH row appears in any fold, in the final fit, or in any number in sections 2-6 "
        "(ADR 0006). Section 7 evaluates against UAH separately, and states what that is "
        "and is not evidence of."
    )
    add("")

    add("## 2. The split")
    add("")
    add(
        f"Leave-one-variant-out grouped {manifest.n_folds}-fold cross-validation. The group is "
        "the **script variant** (`aggressive-b`), not the recording: the six recordings of one "
        "variant differ only in `sensor_noise_seed`, so splitting by recording would put two "
        "near-copies of one authored drive on opposite sides and call the result generalisation. "
        "Every variant is held out exactly once, so the folds partition the corpus and each "
        "window has exactly one out-of-fold prediction."
    )
    add("")
    add(_fold_composition_table(manifest, prepared))
    add("")
    add(
        f"Fold assignment is pinned in `ml/configs/fold_manifest_v1.json` "
        f"(seed `{manifest.variant_shuffle_seed}`) and verified against the corpus on every run — "
        "if the corpus changes, training fails rather than quietly reporting numbers from a "
        "different split."
    )
    add("")

    add("## 3. Headline results (mean ± sd across folds)")
    add("")
    add(ev.render_headline_table(summaries))
    add("")
    sim_majority_share = max(Counter(labels).values()) / len(labels)
    uah_majority_clause = (
        f" — and on UAH, where one class is {_majority_share(uah_metrics[LOGREG_MODEL]):.0%}"
        if uah_metrics is not None
        else ""
    )
    add(
        "**Macro-F1 is the headline, not accuracy.** Accuracy is reported only next to the "
        f"majority-class baseline it has to beat, because on a corpus where one class is "
        f"{sim_majority_share:.0%} of windows{uah_majority_clause} — accuracy mostly measures "
        "the class balance. Macro-F1 weights all four classes equally, so a model that never "
        "predicts `HIGH_RISK` cannot hide behind the other three."
    )
    add("")

    logreg_leads = logreg_summary.macro_f1.mean > tree_summary.macro_f1.mean
    verdict = "beats" if logreg_leads else "does not beat"
    better_model = "logistic regression" if logreg_leads else "tree"
    add(
        f"On macro-F1 the logistic regression ({logreg_summary.macro_f1}) **{verdict}** the "
        f"decision tree ({tree_summary.macro_f1}). `ml/README.md` asks for this comparison to be "
        f"reported either way, so it is reported: on held-out simulator variants the "
        f"{better_model} is ahead, though by a margin the fold-to-fold standard deviations "
        "above do not clearly separate."
    )
    add("")
    shipped_reason = (
        "`model.json`'s format is a coefficient dump (`pipelines.artifact`), which a tree cannot "
        "use — a tree would need its own node serialisation."
    )
    # The format argument is the weaker of the two reasons for shipping the
    # logistic regression, and on its own it reads as a convenience. Where UAH
    # shows the tree collapsing on the class the product exists to catch, say
    # so: that is the reason that would still hold if both serialised equally.
    tree_hr_collapse = uah_metrics is not None and (
        uah_metrics[TREE_MODEL].high_risk_recall < 0.5 * uah_metrics[LOGREG_MODEL].high_risk_recall
    )
    if uah_metrics is not None and tree_hr_collapse:
        tree_uah_hr = uah_metrics[TREE_MODEL].high_risk_recall
        logreg_uah_hr = uah_metrics[LOGREG_MODEL].high_risk_recall
        silent_classes = uah_metrics[TREE_MODEL].zero_recall_labels
        silence = (
            f"never predicts {', '.join(silent_classes)} at all"
            if silent_classes
            else f"recovers {tree_uah_hr:.1%} of `HIGH_RISK` windows against the logistic "
            f"regression's {logreg_uah_hr:.1%}"
        )
        add(
            "**Whichever way that margin falls, it is not the reason for the artefact choice, "
            f"and neither is the file format.** {shipped_reason} That was the original "
            "justification; section 7 supplies a better one. The two models are close in domain "
            f"and far apart out of it: on UAH the tree {silence}. Shipping the model that "
            "degrades *loudly* rather than the one that degrades *silently* is the right call on "
            "a corpus this far from its target domain, independent of which scored higher above."
        )
    else:
        add(f"The shipped artefact is the logistic regression: {shipped_reason}")
    add("")

    for summary in summaries:
        add(f"### {summary.name} — per fold")
        add("")
        add(ev.render_per_fold_table(summary))
        add("")

    add("## 4. Per-class detail")
    add("")
    for summary in (logreg_summary, tree_summary):
        add(f"### {summary.name} — per class, mean ± sd across folds")
        add("")
        add(ev.render_per_class_spread_table(summary))
        add("")

    pooled: dict[str, ev.Metrics] = {}
    majority_overall = ev.majority_label_of(labels)
    for model in (LOGREG_MODEL, TREE_MODEL):
        pooled[model] = ev.evaluate_predictions(
            labels,
            run.out_of_fold[model],
            name=f"out-of-fold ({model})",
            majority_label=majority_overall,
        )

    add("### Pooled out-of-fold confusion matrix — logistic regression")
    add("")
    add(
        "Every window scored by the one fold model that never saw its variant, pooled into a "
        "single matrix. Rows are the rubric label, columns the prediction."
    )
    add("")
    add(ev.render_confusion(pooled[LOGREG_MODEL]))
    add("")
    add("Row-normalised (per-class recall on the diagonal):")
    add("")
    add(ev.render_confusion(pooled[LOGREG_MODEL], normalise=True))
    add("")
    add(ev.render_per_class_table(pooled[LOGREG_MODEL]))
    add("")

    add("### HIGH_RISK recall, specifically")
    add("")
    high_risk = logreg_summary.per_class_spread("HIGH_RISK", "recall")
    high_risk_support = logreg_summary.support_total("HIGH_RISK")
    high_risk_variants = prepared[prepared[LABEL_COLUMN] == "HIGH_RISK"]["variant"].nunique()
    add(
        f"**{high_risk.with_range()}** across folds, over {high_risk_support} `HIGH_RISK` windows "
        "in total. This is the number the product's usefulness rests on: a model that scores "
        "well overall while missing high-risk driving is worse than useless, because it is "
        "confidently quiet about the only thing worth being loud about. It is called out "
        "separately so it cannot be averaged away."
    )
    add("")
    add(
        f"For scale: those windows come from {high_risk_variants} "
        "script variants. Recall measured over that few authored drives has a wide confidence "
        "interval no matter what the point estimate says — the fold-to-fold spread above is a "
        "better guide to it than the mean."
    )
    add("")

    add("### Degenerate-outcome guard")
    add("")
    add(
        "Flagged automatically: any class with zero recall, any class the model never predicts "
        "at all, and any model that fails to beat its own majority-class baseline."
    )
    add("")
    add(ev.render_flags(all_flags))
    add("")

    add("## 5. Rubric as a classifier, against script intent")
    add("")
    add(
        "The rubric cannot be scored against `rubric_label`: it *is* `rubric_label`, so it would "
        "score 1.000 by construction and the number would mean nothing. The only non-circular "
        "check available is against **script intent** — the class each drive was authored to "
        "produce, recoverable from the recording id (`high_risk-c-seed1204` -> `HIGH_RISK`)."
    )
    add("")
    add(
        "Two caveats, both material. First, intent is a *per-recording* label applied to every "
        "window inside it — the same granularity objection ADR 0006 raises against UAH's "
        "trip-level labels, and it applies here too: the idle windows at the start of an "
        "aggressive drive are not aggressive. Intent is not ground truth; it is what the script "
        "was aiming at. Second, M7b's standalone 45-window pilot recordings no longer exist as "
        "separate artefacts — bulk generation superseded them — so this runs over the full "
        f"{len(prepared)}-window simulator corpus, which is the same comparison M7b section 3 "
        "reports, not the 45-window pilot table in its section 2."
    )
    add("")
    intent_rows = [
        ("rubric (the labeller itself)", intent_metrics["rubric"]),
        ("logistic regression (out-of-fold)", intent_metrics[LOGREG_MODEL]),
        ("decision tree (out-of-fold)", intent_metrics[TREE_MODEL]),
    ]
    add(
        "| scored against script intent | accuracy | majority baseline | macro-F1 | balanced acc. |"
    )
    add("| --- | --- | --- | --- | --- |")
    for label, metrics in intent_rows:
        add(
            f"| {label} | {metrics.accuracy:.3f} | {metrics.majority_accuracy:.3f} | "
            f"**{metrics.macro_f1:.3f}** | {metrics.balanced_accuracy:.3f} |"
        )
    add("")
    add(
        "The model is trained on rubric labels, so it can only recover intent to the extent the "
        "rubric does. Where it scores *lower* than the rubric, it has lost information the "
        "labeller had; it cannot score meaningfully higher, and if it appears to, that is a "
        "reason to look for a leak rather than to celebrate."
    )
    add("")
    rubric_intent_f1 = intent_metrics["rubric"].macro_f1
    logreg_intent_f1 = intent_metrics[LOGREG_MODEL].macro_f1
    if logreg_intent_f1 > rubric_intent_f1:
        add(
            f"**On this run it does appear to**: the logistic regression scores "
            f"{logreg_intent_f1:.3f} against the rubric's {rubric_intent_f1:.3f}, so the "
            "paragraph above is describing the current numbers, not a hypothetical. Two "
            "readings, and this report does not choose between them. The benign one: the "
            "rubric is a hard-threshold decision list, so a window a hair over one cutoff gets "
            "a different label from its neighbour, while a fitted model smooths across that "
            "boundary and lands nearer the intent the script was authored for — the model "
            "beating its own teacher on a *third* label is possible for the same reason "
            "label noise is not fatal. The one that would matter: `recording_id` determines "
            "intent, so any feature that encodes which recording a window came from is a "
            f"leak. The margin is {logreg_intent_f1 - rubric_intent_f1:.3f} macro-F1 over "
            f"{intent_metrics[LOGREG_MODEL].n_windows} windows from "
            f"{prepared['variant'].nunique()} variants, which is small enough that neither "
            "reading is established. Worth a look before anything is built on it."
        )
        add("")
    add("Rubric vs intent, as a confusion matrix (rows: intent, columns: rubric label):")
    add("")
    add(ev.render_confusion(intent_metrics["rubric"]))
    add("")

    add("## 6. The shipped artefact")
    add("")
    add(
        "`ml/artifacts/model.json` is a **multinomial logistic regression** "
        f"refitted on all {len(prepared)} simulator windows with no fold held out, serialised as "
        f"plain numbers by `pipelines.artifact` (format `{MODEL_FORMAT}` v{MODEL_FORMAT_VERSION}) "
        "rather than pickled. The cross-validated numbers above estimate how this model "
        "generalises; they are not measurements of this exact fit, and this report does not "
        "present them as such."
    )
    add("")
    add(
        f"The artefact carries {len(payload['feature_names'])} ordered feature names, a mean and "
        "scale per feature, and one coefficient row per class — everything needed to reproduce a "
        "prediction with arithmetic a reader can follow: "
        f"`{payload['decision_rule']}`. Its round-trip against the fitted scikit-learn pipeline "
        "is asserted at training time and in `ml/tests/test_train.py`, so an artefact that "
        "disagrees with the model it came from fails the build rather than shipping."
    )
    add("")
    add(
        "`metadata.json` alongside it records the ordered feature names, the deliberate feature "
        "exclusion and its reason, the training date, dataset hash, git SHA, the fold manifest "
        "and the full metrics from this run."
    )
    add("")

    if uah_metrics is not None and uah_frame is not None:
        logreg_uah = uah_metrics[LOGREG_MODEL]
        add("## 7. UAH validation — real telemetry, never trained on")
        add("")
        add(
            f"The final model predicting on all {logreg_uah.n_windows} UAH-DriveSet windows. No "
            "UAH row was in any fold or in the final fit. Scored against `rubric_label`, since "
            "UAH's own labels are a different taxonomy at a different granularity (ADR 0006)."
        )
        add("")
        add(
            "| model | accuracy | majority baseline | macro-F1 | balanced acc. | HIGH_RISK recall |"
        )
        add("| --- | --- | --- | --- | --- | --- |")
        for model in (LOGREG_MODEL, TREE_MODEL):
            metrics = uah_metrics[model]
            add(
                f"| {model} | {metrics.accuracy:.3f} | {metrics.majority_accuracy:.3f} | "
                f"**{metrics.macro_f1:.3f}** | {metrics.balanced_accuracy:.3f} | "
                f"{metrics.high_risk_recall:.3f} |"
            )
        add("")
        add(ev.render_per_class_table(logreg_uah))
        add("")
        add("Confusion matrix (rows: rubric label, columns: prediction):")
        add("")
        add(ev.render_confusion(logreg_uah))
        add("")
        add("Row-normalised:")
        add("")
        add(ev.render_confusion(logreg_uah, normalise=True))
        add("")
        add("### Degenerate-outcome guard, UAH")
        add("")
        uah_flags = [
            f"{model}, {flag}" for model in uah_metrics for flag in uah_metrics[model].flags
        ]
        add(ev.render_flags(uah_flags))
        add("")
        add("### What this number is not")
        add("")
        add(
            "**It is not a clean held-out test, and this report does not claim it is.** Three "
            "things stand between this figure and that claim:"
        )
        add("")
        add(
            "1. **The labels are rubric labels, and the rubric's cutoffs were calibrated on this "
            "corpus.** ADR 0006 is explicit: ten hand-set thresholds were chosen, once, by a "
            "human reading UAH's own feature percentiles. UAH's *labels* never trained or scored "
            "a model and no UAH row ever entered the training parquet — that guarantee holds — "
            "but the yardstick being measured against was shaped by the thing being measured."
        )
        # Measured here rather than quoted from M7b: that report's figures were
        # taken on a corpus that has since been regenerated, and a domain-gap
        # claim carried forward by hand is exactly the kind that goes stale
        # without anyone noticing.
        gap_lines: list[str] = []
        for feature in ("speed_mean", "accel_std", "lat_accel_std"):
            if feature not in prepared or feature not in uah_frame:
                continue
            gap_lines.append(
                f"`{feature}` p50 {prepared[feature].median():.3f} against UAH's "
                f"{uah_frame[feature].median():.3f} (max {prepared[feature].max():.3f} "
                f"against {uah_frame[feature].max():.3f})"
            )
        add(
            "2. **There is a domain gap, not just unseen data.** Measured on the two corpora "
            "this run actually used: " + "; ".join(gap_lines) + ". This tests generalisation "
            "across two differently-shaped distributions, which is a harder and less "
            "interpretable question than generalisation to unseen samples of one."
        )
        train_hr_share = Counter(labels).get("HIGH_RISK", 0) / len(labels)
        uah_hr_support = logreg_uah.per_class[CLASS_ORDER.index("HIGH_RISK")].support
        add(
            f"3. **The class balance differs sharply.** `HIGH_RISK` is {train_hr_share:.1%} of "
            f"the training corpus and {uah_hr_support / logreg_uah.n_windows:.1%} of UAH "
            f"({uah_hr_support} windows). Per-class figures on that few windows carry confidence "
            "intervals wide enough to swallow most conclusions."
        )
        add("")
        add("### Cross-tab against UAH's own labels (qualitative only)")
        add("")
        add(
            "Not a metric — the taxonomies do not correspond and the granularities differ. It is "
            "a smell test: windows from trips UAH itself called `aggressive` should skew towards "
            "predicted `AGGRESSIVE`/`HIGH_RISK` more than windows from `normal` trips do. If "
            "they do not, something is wrong somewhere upstream."
        )
        add("")
        add(ev.render_crosstab(uah_frame, rows="uah_label", columns="prediction"))
        add("")
        add("Read as shares of each UAH label, which is the only way the skew is visible:")
        add("")
        add("| UAH's own label | HIGH_RISK | AGGRESSIVE or HIGH_RISK | windows |")
        add("| --- | --- | --- | --- |")
        for uah_label in sorted(set(uah_frame["uah_label"].dropna())):
            rows = uah_frame[uah_frame["uah_label"] == uah_label]
            high_risk_share = float((rows["prediction"] == "HIGH_RISK").mean())
            risky_share = float(rows["prediction"].isin(["AGGRESSIVE", "HIGH_RISK"]).mean())
            add(f"| {uah_label} | {high_risk_share:.1%} | {risky_share:.1%} | {len(rows)} |")
        add("")

        def _risky_share(uah_label: str) -> float:
            rows = uah_frame[uah_frame["uah_label"] == uah_label]
            if rows.empty:
                return float("nan")
            return float(rows["prediction"].isin(["AGGRESSIVE", "HIGH_RISK"]).mean())

        normal_risky = _risky_share("normal")
        aggressive_risky = _risky_share("aggressive")
        drowsy_risky = _risky_share("drowsy")
        # The check the cross-tab exists to make, asserted from the numbers
        # rather than described from memory of them.
        ordering_holds = aggressive_risky > normal_risky and aggressive_risky > drowsy_risky
        if ordering_holds:
            add(
                "The smell test half-passes, and the half that fails is the informative half. "
                "The **ordering is right**: trips UAH itself called `aggressive` draw an "
                f"`AGGRESSIVE`-or-`HIGH_RISK` prediction on {aggressive_risky:.1%} of their "
                f"windows against {normal_risky:.1%} for `normal` trips and "
                f"{drowsy_risky:.1%} for `drowsy` ones. The model has not inverted the problem, "
                "and on a corpus it was never trained on that is worth something."
            )
        else:
            add(
                "**The smell test fails outright, and that is a finding about the pipeline "
                "rather than about the model.** Trips UAH itself called `aggressive` draw an "
                f"`AGGRESSIVE`-or-`HIGH_RISK` prediction on {aggressive_risky:.1%} of their "
                f"windows against {normal_risky:.1%} for `normal` trips — the severity ordering "
                "does not hold even qualitatively, which points upstream at the features or the "
                "rubric before it points at the classifier."
            )
        add("")
        add(
            f"The **floor is what fails**: {normal_risky:.1%} of windows from trips UAH called "
            "`normal` are predicted `AGGRESSIVE` or `HIGH_RISK`. A severity ordering that only "
            "holds above a floor that high is not usable — it is the same over-prediction the "
            "per-class precision figures show from the other side, seen here against an "
            "independent set of labels rather than against the rubric's."
        )
        add("")
        add(
            "`drowsy` has no DriveSense equivalent and is expected to spread across the "
            "behaviour classes rather than concentrate — ADR 0006's stated limitation, that a "
            "vehicle-telemetry rubric cannot separate drowsiness from aggression as a *cause*, "
            "applies unchanged to a model trained on that rubric."
        )
        add("")

    return "\n".join(lines).rstrip() + "\n"


# --- Metadata -----------------------------------------------------------------


def build_metadata(
    *,
    config: TrainConfig,
    config_path: Path,
    manifest: FoldManifest,
    prepared: pd.DataFrame,
    run: FoldRun,
    uah_metrics: dict[str, ev.Metrics] | None,
    intent_metrics: dict[str, ev.Metrics],
    dataset_sha256: str | None,
    sha: str | None,
    generated_at: str,
) -> dict[str, Any]:
    labels = _labels(prepared)
    return {
        "model_format": MODEL_FORMAT,
        "model_format_version": MODEL_FORMAT_VERSION,
        "model_type": "multinomial logistic regression (StandardScaler + LogisticRegression)",
        "generated_at": generated_at,
        "git_sha": sha,
        "dataset_sha256": dataset_sha256,
        "feature_version": FEATURE_VERSION,
        "feature_names": config.feature_names,
        "excluded_features": config.excluded_features,
        "all_shared_features": list(FEATURE_NAMES),
        "classes": list(CLASS_ORDER),
        "label_column": LABEL_COLUMN,
        "label_source": {
            "kind": "rubric (weak supervision)",
            "adr": "docs/adr/0006-training-label-rubric.md",
            "note": "Rule-based labeller over simulator windows, not human-annotated ground truth.",
        },
        "training_corpus": {
            "corpus": "sim",
            "windows": int(len(prepared)),
            "recordings": int(prepared["recording_id"].nunique()),
            "variants": int(prepared["variant"].nunique()),
            "excluded_recordings": list(EXCLUDED_RECORDING_IDS),
            "class_balance": {label: labels.count(label) for label in CLASS_ORDER},
            "training_majority_class": ev.majority_label_of(labels),
        },
        "config": {"path": config_path.name, "version": config.config_version, **config.raw},
        "fold_manifest": {
            "path": DEFAULT_MANIFEST_PATH.name,
            "n_folds": manifest.n_folds,
            "variant_shuffle_seed": manifest.variant_shuffle_seed,
            "folds": [
                {"fold": fold.index, "test_variants": list(fold.test_variants)}
                for fold in manifest.folds
            ],
        },
        "metrics": {
            "cross_validation": {
                model: ev.summary_to_dict(summary) for model, summary in run.summaries.items()
            },
            "uah_validation": (
                {model: ev.metrics_to_dict(metrics) for model, metrics in uah_metrics.items()}
                if uah_metrics
                else None
            ),
            "script_intent": {
                model: ev.metrics_to_dict(metrics) for model, metrics in intent_metrics.items()
            },
        },
    }


# --- Entry point ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and evaluate the M8 behaviour classifier.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--sim-parquet", type=Path, default=DEFAULT_SIM_PARQUET)
    parser.add_argument("--uah-parquet", type=Path, default=DEFAULT_UAH_PARQUET)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--skip-uah", action="store_true")
    args = parser.parse_args(argv)

    if not args.sim_parquet.is_file():
        print(
            f"missing {args.sim_parquet} — run `python -m pipelines.featurise --corpus sim` first"
        )
        return 1

    config = load_config(args.config)
    sha = git_sha()
    generated_at = datetime.now(UTC).isoformat()

    raw_frame = pd.read_parquet(args.sim_parquet)
    prepared = add_split_columns(drop_excluded(raw_frame))

    if args.manifest_path.is_file():
        manifest = read_manifest(args.manifest_path)
    else:
        manifest = build_manifest(
            raw_frame,
            n_folds=config.n_folds,
            seed=config.variant_shuffle_seed,
            source_parquet=args.sim_parquet,
            generated_at=generated_at,
            sha=sha,
        )
        write_manifest(manifest, args.manifest_path)
        print(f"wrote {args.manifest_path}")
    verify_manifest(manifest, raw_frame)

    run = run_cross_validation(prepared, manifest, config)

    _, payload = fit_final_logistic_regression(prepared, config)

    # Script intent: the class each drive was authored to produce. Only a
    # comparison, never a training signal — the rubric is the label of record.
    intent = [str(value) for value in prepared["intent"]]
    majority_overall = ev.majority_label_of(_labels(prepared))
    intent_metrics = {
        "rubric": ev.evaluate_predictions(
            intent, _labels(prepared), name="rubric vs intent", majority_label=majority_overall
        ),
        LOGREG_MODEL: ev.evaluate_predictions(
            intent,
            run.out_of_fold[LOGREG_MODEL],
            name="logreg vs intent",
            majority_label=majority_overall,
        ),
        TREE_MODEL: ev.evaluate_predictions(
            intent,
            run.out_of_fold[TREE_MODEL],
            name="tree vs intent",
            majority_label=majority_overall,
        ),
    }

    uah_metrics: dict[str, ev.Metrics] | None = None
    uah_frame: pd.DataFrame | None = None
    if not args.skip_uah:
        if not args.uah_parquet.is_file():
            print(f"note: {args.uah_parquet} missing — skipping UAH validation")
        else:
            uah_frame = pd.read_parquet(args.uah_parquet)
            uah_truth = _labels(uah_frame)
            uah_features = _matrix(uah_frame, config.feature_names)
            logreg_uah = predict(payload, uah_features)
            uah_frame = uah_frame.assign(prediction=logreg_uah)

            tree = build_decision_tree(config)
            tree.fit(_matrix(prepared, config.feature_names), _labels(prepared))
            tree_uah = [str(value) for value in tree.predict(uah_features)]

            uah_metrics = {
                LOGREG_MODEL: ev.evaluate_predictions(
                    uah_truth, logreg_uah, name="uah", majority_label=majority_overall
                ),
                TREE_MODEL: ev.evaluate_predictions(
                    uah_truth, tree_uah, name="uah", majority_label=majority_overall
                ),
            }

    dataset_sha256 = None
    if "dataset_sha256" in prepared.columns and len(prepared):
        value = prepared["dataset_sha256"].iloc[0]
        dataset_sha256 = None if pd.isna(value) else str(value)

    metadata = build_metadata(
        config=config,
        config_path=args.config,
        manifest=manifest,
        prepared=prepared,
        run=run,
        uah_metrics=uah_metrics,
        intent_metrics=intent_metrics,
        dataset_sha256=dataset_sha256,
        sha=sha,
        generated_at=generated_at,
    )

    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.artifact_dir / "model.json"
    metadata_path = args.artifact_dir / "metadata.json"
    write_model_json(payload, model_path)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    # Read it back the way the backend will, rather than trusting what was written.
    read_model_json(model_path)

    report = build_report(
        config=config,
        manifest=manifest,
        prepared=prepared,
        run=run,
        payload=payload,
        uah_metrics=uah_metrics,
        uah_frame=uah_frame,
        intent_metrics=intent_metrics,
        sha=sha,
        generated_at=generated_at,
    )
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(report, encoding="utf-8")

    logreg_summary = run.summaries[LOGREG_MODEL]
    print(f"trained on {len(prepared)} windows, {manifest.n_folds} folds")
    for model, summary in run.summaries.items():
        print(
            f"  {model:<24} macro-F1 {summary.macro_f1}  "
            f"accuracy {summary.accuracy}  "
            f"HIGH_RISK recall {summary.per_class_spread('HIGH_RISK', 'recall')}"
        )
    for flag in logreg_summary.flags:
        print(f"  flag: {flag}")
    if uah_metrics is not None:
        uah = uah_metrics[LOGREG_MODEL]
        print(
            f"  UAH ({uah.n_windows} windows): macro-F1 {uah.macro_f1:.3f}, "
            f"accuracy {uah.accuracy:.3f} vs majority {uah.majority_accuracy:.3f}, "
            f"HIGH_RISK recall {uah.high_risk_recall:.3f}"
        )
        for flag in uah.flags:
            print(f"  flag: UAH, {flag}")
    print(f"wrote {model_path}")
    print(f"wrote {metadata_path}")
    print(f"wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
