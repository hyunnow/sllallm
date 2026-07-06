"""Post-training threshold analysis (Phase 8).

Reuses a trained checkpoint to sweep the class_schedule confidence threshold —
trading precision for recall — WITHOUT retraining. The product wants the lowest
threshold that still keeps class_schedule precision above target (so recall is
as high as possible while a wrong class is still essentially never added).

torch/transformers imported lazily so the module loads without them.
"""
from __future__ import annotations

from typing import Optional

from ..eval.metrics import evaluate
from .train import ID2LABEL, load_split, predict_with_threshold


def compute_probs(model_dir: str, rows: list[dict], max_length: int = 256, batch_size: int = 64):
    """Softmax probabilities [n, num_labels] for `rows` from a saved checkpoint."""
    import numpy as np
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).eval()

    out = []
    with torch.no_grad():
        for i in range(0, len(rows), batch_size):
            batch = [r["input_text"] for r in rows[i:i + batch_size]]
            enc = tok(batch, truncation=True, max_length=max_length, padding=True, return_tensors="pt").to(device)
            logits = model(**enc).logits
            out.append(torch.softmax(logits, dim=1).cpu().numpy())
    return np.concatenate(out)


def sweep_thresholds(
    model_dir: str,
    test_file: str,
    thresholds=(0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95),
) -> list[dict]:
    """Evaluate the real holdout at each class_schedule threshold."""
    rows = load_split(test_file)
    probs = compute_probs(model_dir, rows)
    y_true = [r["label"] for r in rows]
    results = []
    for t in thresholds:
        y_pred = [ID2LABEL[i] for i in predict_with_threshold(probs, t)]
        m = evaluate(y_true, y_pred)
        results.append({
            "threshold": t,
            "class_precision": m["class_schedule_precision"],
            "class_recall": m["class_schedule_recall"],
            "office_to_class": m["office_hours_to_class_schedule_rate"],
            "macro_f1": m["macro_f1"],
        })
    return results


def recommend_threshold(results: list[dict], min_precision: float = 0.98) -> Optional[dict]:
    """Lowest threshold whose precision still meets target -> maximizes recall
    while keeping the precision guarantee."""
    ok = [r for r in results if r["class_precision"] >= min_precision]
    return min(ok, key=lambda r: r["threshold"]) if ok else None
