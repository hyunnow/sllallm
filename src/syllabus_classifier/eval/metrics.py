"""Risk-aware evaluation (Phase 8). General accuracy is explicitly not enough.

The metrics that matter for this product's risk profile:
  - class_schedule PRECISION (target 0.98~0.99+)
  - office_hours -> class_schedule misclassification rate (target ~0)
  - class_schedule false-positive rate (as low as possible)
  - per-class F1 + full confusion matrix

Pure-python (no sklearn dependency) so it runs anywhere, including bare Colab.
Report against the REAL holdout and, separately, the synthetic stress test, so
"synthetic mirage" performance is visible (spec Phase 8 / §7).
"""
from __future__ import annotations

from collections import defaultdict

from ..common.schema import ALL_LABELS, Label

CLASS = Label.CLASS_SCHEDULE.value
OFFICE = {Label.INSTRUCTOR_OFFICE_HOURS.value, Label.TA_OFFICE_HOURS.value}


def confusion_matrix(y_true: list[str], y_pred: list[str], labels: list[str] | None = None) -> dict:
    """Return a nested dict cm[true][pred] = count."""
    labels = labels or ALL_LABELS
    cm = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        if t in cm and p in cm[t]:
            cm[t][p] += 1
    return cm


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def evaluate(y_true: list[str], y_pred: list[str]) -> dict:
    """Compute the full risk-aware metric bundle."""
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred length mismatch")
    n = len(y_true)

    per_class = {}
    for label in ALL_LABELS:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        precision, recall, f1 = _prf(tp, fp, fn)
        per_class[label] = {
            "precision": precision, "recall": recall, "f1": f1,
            "support": sum(1 for t in y_true if t == label),
        }

    # office_hours mislabeled as class_schedule — the flagship risk
    office_total = sum(1 for t in y_true if t in OFFICE)
    office_as_class = sum(1 for t, p in zip(y_true, y_pred) if t in OFFICE and p == CLASS)

    # class_schedule false positives (predicted class, truly something else)
    class_fp = sum(1 for t, p in zip(y_true, y_pred) if p == CLASS and t != CLASS)
    class_pred_total = sum(1 for p in y_pred if p == CLASS)

    accuracy = sum(1 for t, p in zip(y_true, y_pred) if t == p) / n if n else 0.0

    return {
        "n": n,
        "accuracy": accuracy,
        "class_schedule_precision": per_class[CLASS]["precision"],
        "class_schedule_recall": per_class[CLASS]["recall"],
        "class_schedule_false_positive_rate": (class_fp / class_pred_total) if class_pred_total else 0.0,
        "office_hours_to_class_schedule_rate": (office_as_class / office_total) if office_total else 0.0,
        "macro_f1": sum(v["f1"] for v in per_class.values()) / len(per_class),
        "per_class": per_class,
        "confusion_matrix": confusion_matrix(y_true, y_pred),
    }
