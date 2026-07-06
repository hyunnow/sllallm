#!/usr/bin/env python3
"""Phase 4 — build the candidate-level training dataset from Phase 2 labels.

Reads data/candidates/label_review.jsonl (LLM draft + any human corrections),
turns each labeled candidate into a training example, and reports the class
distribution so imbalance is visible before training.

Usage:
  python scripts/04_build_dataset.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.dataset.build import build_dataset_from_labels, class_distribution


def main() -> int:
    cfg = load_config("data.yaml")
    cand_dir = resolve_path(cfg["paths"]["candidates_dir"])
    review = cand_dir / "label_review.jsonl"
    if not review.exists():
        print(f"no {review}. Run scripts/02_label.py first.")
        return 1

    rows = [json.loads(l) for l in review.read_text(encoding="utf-8").splitlines() if l.strip()]
    dataset = build_dataset_from_labels(rows)
    dropped = len(rows) - len(dataset)

    out = cand_dir / "dataset.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in dataset), encoding="utf-8")

    dist = class_distribution(dataset)
    n = len(dataset)
    n_docs = len({r["doc_id"] for r in dataset})
    n_human = sum(1 for r in dataset if r["source"] == "human")

    print(f"=== dataset: {n} examples from {n_docs} docs "
          f"({dropped} unlabeled dropped, {n_human} human-corrected) ===\n")
    print("=== class distribution ===")
    for lab, k in Counter(dist).most_common():
        print(f"  {lab:26} {k:5}  ({100*k/max(n,1):.1f}%)")
    n_class = dist.get("class_schedule", 0)
    print(f"\nclass_schedule share: {n_class}/{n} ({100*n_class/max(n,1):.1f}%)")
    if n_class and n_class / n < 0.03:
        print("  NOTE: class_schedule is rare — use class weights / focal loss (train.yaml).")
    print(f"\nwrote -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
