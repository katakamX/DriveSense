"""Metrics for M8, and the guards that stop a flattering number being reported.

    python -m pipelines.evaluate                       # score ml/artifacts/model.json on UAH
    python -m pipelines.evaluate --parquet <path>      # ...on any featurised corpus

Accuracy alone is not reportable here, and the reason is arithmetic rather
than principle. On the UAH validation corpus the rubric labels are 65.0%
`NORMAL` and 0.9% `HIGH_RISK` (16 windows of 1,709). A classifier that
answers `NORMAL` to everything scores 0.65 accuracy and never once identifies
the class the product exists to identify; a classifier that finds every
`HIGH_RISK` window but is otherwise mediocre can easily score lower. Any
metric that ranks the first above the second is measuring the class balance,
not the model.

So every evaluation this module produces carries, together and never
separately:

- **the majority-class baseline's accuracy alongside the model's**, so the
  floor is always visible next to the number being claimed;
- **macro-F1 as the headline**, which weights `HIGH_RISK` equally with
  `NORMAL` and therefore scores the always-`NORMAL` predictor around 0.20
  instead of 0.65;
- **balanced accuracy**, the same correction applied to recall;
- **per-class precision/recall/F1 with support counts**, so a 1.00 over three
  windows cannot pass for a result;
- **the full 4x4 confusion matrix**, raw and row-normalised, because the known
  hard case (CALM vs NORMAL — a smooth cruise genuinely is both) is a
  structural finding that an averaged score hides;
- **`HIGH_RISK` recall, called out on its own**, since it is the number the
  product's usefulness actually rests on;
- **a degenerate-outcome guard**: any class with zero recall, any class never
  predicted at all, and any model failing to beat the majority baseline are
  flagged explicitly in the report rather than left for a reader to notice.

`evaluate_predictions` is deliberately model-agnostic — it takes two label
sequences. The rubric-as-classifier baseline, the majority baseline, the tree
and the logistic regression all go through the same code, so their numbers are
comparable by construction.
"""

from __future__ import annotations

import argparse
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

from pipelines.artifact import feature_matrix, predict, read_model_json
from pipelines.split import CLASS_ORDER

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = REPO_ROOT / "ml" / "artifacts" / "model.json"
DEFAULT_UAH_PARQUET = REPO_ROOT / "data" / "processed" / "features_uah_v1.parquet"


@dataclass(frozen=True)
class ClassMetrics:
    label: str
    precision: float
    recall: float
    f1: float
    support: int
    predicted: int


@dataclass(frozen=True)
class Metrics:
    """One model's scores on one evaluation set."""

    name: str
    n_windows: int
    accuracy: float
    majority_label: str
    majority_accuracy: float
    macro_f1: float
    balanced_accuracy: float
    per_class: tuple[ClassMetrics, ...]
    confusion: tuple[tuple[int, ...], ...]

    @property
    def high_risk_recall(self) -> float:
        return self.recall_of("HIGH_RISK")

    def recall_of(self, label: str) -> float:
        for entry in self.per_class:
            if entry.label == label:
                return entry.recall
        return float("nan")

    @property
    def zero_recall_labels(self) -> tuple[str, ...]:
        """Present in the truth but never once recovered — the degenerate outcome."""
        return tuple(e.label for e in self.per_class if e.support > 0 and e.recall == 0.0)

    @property
    def never_predicted_labels(self) -> tuple[str, ...]:
        return tuple(e.label for e in self.per_class if e.predicted == 0)

    @property
    def beats_majority(self) -> bool:
        return self.accuracy > self.majority_accuracy

    @property
    def flags(self) -> tuple[str, ...]:
        notes: list[str] = []
        if self.zero_recall_labels:
            notes.append("DEGENERATE: zero recall on " + ", ".join(self.zero_recall_labels))
        for label in self.never_predicted_labels:
            if label not in self.zero_recall_labels:
                notes.append(f"DEGENERATE: never predicts {label}")
        if not self.beats_majority:
            notes.append(
                f"does not beat the majority-class baseline "
                f"({self.accuracy:.3f} vs {self.majority_accuracy:.3f})"
            )
        return tuple(notes)


def majority_label_of(labels: Sequence[str]) -> str:
    """The most common label, ties broken by CLASS_ORDER so it is deterministic."""
    counts = Counter(labels)
    return max(sorted(counts, key=CLASS_ORDER.index), key=lambda label: counts[label])


def evaluate_predictions(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    *,
    name: str,
    majority_label: str,
) -> Metrics:
    """Score one set of predictions against one set of labels.

    `majority_label` is passed in rather than derived from `y_true`: the honest
    baseline predicts the majority class *of the training data*, which is the
    only thing a real always-guess model could know. Deriving it from the test
    labels would hand the baseline information the model does not have.
    """
    truth = list(y_true)
    predicted = list(y_pred)
    labels = list(CLASS_ORDER)

    precision, recall, f1, support = precision_recall_fscore_support(
        truth, predicted, labels=labels, zero_division=0
    )
    predicted_counts = Counter(predicted)
    per_class = tuple(
        ClassMetrics(
            label=label,
            precision=float(precision[index]),
            recall=float(recall[index]),
            f1=float(f1[index]),
            support=int(support[index]),
            predicted=int(predicted_counts.get(label, 0)),
        )
        for index, label in enumerate(labels)
    )

    matrix = confusion_matrix(truth, predicted, labels=labels)
    majority_accuracy = (
        sum(1 for label in truth if label == majority_label) / len(truth) if truth else 0.0
    )

    return Metrics(
        name=name,
        n_windows=len(truth),
        accuracy=float(accuracy_score(truth, predicted)),
        majority_label=majority_label,
        majority_accuracy=majority_accuracy,
        macro_f1=float(f1_score(truth, predicted, labels=labels, average="macro", zero_division=0)),
        balanced_accuracy=float(balanced_accuracy_score(truth, predicted)),
        per_class=per_class,
        confusion=tuple(tuple(int(value) for value in row) for row in matrix),
    )


# --- Aggregation across folds ------------------------------------------------


@dataclass(frozen=True)
class Spread:
    """A metric summarised over folds. `std` is the population standard deviation."""

    mean: float
    std: float
    minimum: float
    maximum: float

    def __str__(self) -> str:
        return f"{self.mean:.3f} ± {self.std:.3f}"

    def with_range(self) -> str:
        return f"{self.mean:.3f} ± {self.std:.3f} (min {self.minimum:.3f}, max {self.maximum:.3f})"


def spread_of(values: Sequence[float]) -> Spread:
    usable = [value for value in values if not np.isnan(value)]
    if not usable:
        return Spread(
            mean=float("nan"), std=float("nan"), minimum=float("nan"), maximum=float("nan")
        )
    return Spread(
        mean=statistics.fmean(usable),
        std=statistics.pstdev(usable) if len(usable) > 1 else 0.0,
        minimum=min(usable),
        maximum=max(usable),
    )


@dataclass(frozen=True)
class FoldSummary:
    """One model's per-fold metrics, and their mean ± spread."""

    name: str
    folds: tuple[Metrics, ...]

    def _values(self, attribute: str) -> list[float]:
        return [float(getattr(metrics, attribute)) for metrics in self.folds]

    @property
    def accuracy(self) -> Spread:
        return spread_of(self._values("accuracy"))

    @property
    def majority_accuracy(self) -> Spread:
        return spread_of(self._values("majority_accuracy"))

    @property
    def macro_f1(self) -> Spread:
        return spread_of(self._values("macro_f1"))

    @property
    def balanced_accuracy(self) -> Spread:
        return spread_of(self._values("balanced_accuracy"))

    def per_class_spread(self, label: str, attribute: str) -> Spread:
        values: list[float] = []
        for metrics in self.folds:
            for entry in metrics.per_class:
                if entry.label == label and entry.support > 0:
                    values.append(float(getattr(entry, attribute)))
        return spread_of(values)

    def support_total(self, label: str) -> int:
        return sum(
            entry.support
            for metrics in self.folds
            for entry in metrics.per_class
            if entry.label == label
        )

    @property
    def flags(self) -> tuple[str, ...]:
        notes: list[str] = []
        for metrics in self.folds:
            notes.extend(f"fold {metrics.name}: {flag}" for flag in metrics.flags)
        return tuple(notes)


# --- Serialisation for metadata.json -----------------------------------------


def metrics_to_dict(metrics: Metrics) -> dict[str, object]:
    return {
        "name": metrics.name,
        "n_windows": metrics.n_windows,
        "accuracy": metrics.accuracy,
        "majority_class": metrics.majority_label,
        "majority_class_accuracy": metrics.majority_accuracy,
        "macro_f1": metrics.macro_f1,
        "balanced_accuracy": metrics.balanced_accuracy,
        "high_risk_recall": metrics.high_risk_recall,
        "per_class": {
            entry.label: {
                "precision": entry.precision,
                "recall": entry.recall,
                "f1": entry.f1,
                "support": entry.support,
                "predicted": entry.predicted,
            }
            for entry in metrics.per_class
        },
        "confusion_matrix": {
            "labels": list(CLASS_ORDER),
            "rows_are": "true label",
            "counts": [list(row) for row in metrics.confusion],
        },
        "flags": list(metrics.flags),
    }


def _spread_to_dict(spread: Spread) -> dict[str, float]:
    return {"mean": spread.mean, "std": spread.std, "min": spread.minimum, "max": spread.maximum}


def summary_to_dict(summary: FoldSummary) -> dict[str, object]:
    return {
        "model": summary.name,
        "n_folds": len(summary.folds),
        "aggregate": {
            "accuracy": _spread_to_dict(summary.accuracy),
            "majority_class_accuracy": _spread_to_dict(summary.majority_accuracy),
            "macro_f1": _spread_to_dict(summary.macro_f1),
            "balanced_accuracy": _spread_to_dict(summary.balanced_accuracy),
            "per_class": {
                label: {
                    "precision": _spread_to_dict(summary.per_class_spread(label, "precision")),
                    "recall": _spread_to_dict(summary.per_class_spread(label, "recall")),
                    "f1": _spread_to_dict(summary.per_class_spread(label, "f1")),
                    "support_total": summary.support_total(label),
                }
                for label in CLASS_ORDER
            },
        },
        "per_fold": [metrics_to_dict(metrics) for metrics in summary.folds],
        "flags": list(summary.flags),
    }


# --- Markdown rendering ------------------------------------------------------


def render_headline_table(summaries: Sequence[FoldSummary]) -> str:
    lines = [
        "| model | accuracy | majority baseline | macro-F1 | balanced acc. | HIGH_RISK recall |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for summary in summaries:
        high_risk = summary.per_class_spread("HIGH_RISK", "recall")
        lines.append(
            f"| {summary.name} | {summary.accuracy} | {summary.majority_accuracy} | "
            f"**{summary.macro_f1}** | {summary.balanced_accuracy} | {high_risk} |"
        )
    return "\n".join(lines)


def render_per_fold_table(summary: FoldSummary) -> str:
    lines = [
        "| fold | windows | accuracy | majority baseline | macro-F1 | balanced acc. | "
        "HIGH_RISK recall |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for metrics in summary.folds:
        lines.append(
            f"| {metrics.name} | {metrics.n_windows} | {metrics.accuracy:.3f} | "
            f"{metrics.majority_accuracy:.3f} ({metrics.majority_label}) | "
            f"{metrics.macro_f1:.3f} | {metrics.balanced_accuracy:.3f} | "
            f"{metrics.high_risk_recall:.3f} |"
        )
    accuracy = summary.accuracy
    lines.append(
        f"| **mean ± sd** | — | **{accuracy}** | {summary.majority_accuracy} | "
        f"**{summary.macro_f1}** | {summary.balanced_accuracy} | "
        f"{summary.per_class_spread('HIGH_RISK', 'recall')} |"
    )
    return "\n".join(lines)


def render_per_class_spread_table(summary: FoldSummary) -> str:
    lines = [
        "| class | precision | recall | F1 | support (all folds) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label in CLASS_ORDER:
        lines.append(
            f"| {label} | {summary.per_class_spread(label, 'precision')} | "
            f"{summary.per_class_spread(label, 'recall')} | "
            f"{summary.per_class_spread(label, 'f1')} | {summary.support_total(label)} |"
        )
    return "\n".join(lines)


def render_per_class_table(metrics: Metrics) -> str:
    lines = [
        "| class | precision | recall | F1 | support | predicted |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in metrics.per_class:
        lines.append(
            f"| {entry.label} | {entry.precision:.3f} | {entry.recall:.3f} | {entry.f1:.3f} | "
            f"{entry.support} | {entry.predicted} |"
        )
    return "\n".join(lines)


def render_confusion(metrics: Metrics, *, normalise: bool = False) -> str:
    header = "| true \\ predicted | " + " | ".join(CLASS_ORDER) + " | total |"
    divider = "| --- | " + " | ".join("---" for _ in CLASS_ORDER) + " | --- |"
    lines = [header, divider]
    for index, label in enumerate(CLASS_ORDER):
        row = metrics.confusion[index]
        total = sum(row)
        if normalise:
            cells = [f"{(value / total):.3f}" if total else "—" for value in row]
        else:
            cells = [str(value) for value in row]
        marked = [
            f"**{cell}**" if position == index else cell for position, cell in enumerate(cells)
        ]
        lines.append(f"| {label} | " + " | ".join(marked) + f" | {total} |")
    return "\n".join(lines)


def render_flags(flags: Sequence[str]) -> str:
    if not flags:
        return (
            "No degenerate outcomes flagged: every class has non-zero recall, every class is "
            "predicted at least once, and every model beats its majority-class baseline."
        )
    return "\n".join(f"- **{flag}**" for flag in flags)


def render_crosstab(frame: pd.DataFrame, *, rows: str, columns: str) -> str:
    table = pd.crosstab(frame[rows], frame[columns])
    column_labels = [str(value) for value in table.columns]
    lines = [
        f"| {rows} \\ {columns} | " + " | ".join(column_labels) + " | total |",
        "| --- | " + " | ".join("---" for _ in column_labels) + " | --- |",
    ]
    for label, row in table.iterrows():
        values = [int(value) for value in row]
        lines.append(f"| {label} | " + " | ".join(str(v) for v in values) + f" | {sum(values)} |")
    return "\n".join(lines)


# --- Standalone entry point ---------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Score a saved `model.json` against a featurised corpus, without retraining."""
    parser = argparse.ArgumentParser(
        description="Evaluate a committed model.json against a featurised corpus."
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--parquet", type=Path, default=DEFAULT_UAH_PARQUET)
    parser.add_argument("--label-column", default="rubric_label")
    args = parser.parse_args(argv)

    if not args.model.is_file():
        print(f"missing {args.model} — run `python -m pipelines.train` first")
        return 1
    if not args.parquet.is_file():
        print(f"missing {args.parquet} — run `python -m pipelines.featurise` first")
        return 1

    payload = read_model_json(args.model)
    frame = pd.read_parquet(args.parquet)
    predictions = predict(payload, feature_matrix(frame, payload))
    truth = [str(value) for value in frame[args.label_column]]

    metrics = evaluate_predictions(
        truth,
        predictions,
        name=args.parquet.stem,
        majority_label=str(payload.get("metadata", {}).get("training_majority_class", "NORMAL")),
    )

    print(f"{metrics.name}: {metrics.n_windows} windows")
    print(
        f"  accuracy         {metrics.accuracy:.3f}   "
        f"(majority baseline {metrics.majority_accuracy:.3f})"
    )
    print(f"  macro-F1         {metrics.macro_f1:.3f}")
    print(f"  balanced acc.    {metrics.balanced_accuracy:.3f}")
    print(f"  HIGH_RISK recall {metrics.high_risk_recall:.3f}")
    for flag in metrics.flags:
        print(f"  flag: {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
