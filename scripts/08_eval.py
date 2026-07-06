#!/usr/bin/env python3
"""Phase 8 — sweep the class_schedule confidence threshold on the real holdout,
reusing a trained checkpoint (no retraining). Compares the MODEL ALONE against
the FULL PIPELINE (model -> rule validator), which is what actually ships.

Usage (on Colab, after training):
  python scripts/08_eval.py --model checkpoints/klue/best --test data/splits/val.jsonl
  python scripts/08_eval.py --model checkpoints/klue/best --test data/splits/test.jsonl

The validator blocks office-hours context from becoming class_schedule, so it
usually lets a LOWER threshold (more recall) keep office->class near zero.
Pick the threshold on VAL, then read that row on TEST for the honest number.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.model.evaluate import (
    recommend_threshold,
    sweep_thresholds,
    sweep_thresholds_with_validator,
)


def _table(title: str, results: list[dict]) -> None:
    print(f"\n=== {title} ===")
    print(f"{'thresh':>7} {'precision':>10} {'recall':>8} {'office→class':>13} {'macroF1':>8}")
    for r in results:
        print(f"{r['threshold']:>7.2f} {r['class_precision']:>10.3f} {r['class_recall']:>8.3f} "
              f"{r['office_to_class']:>13.3f} {r['macro_f1']:>8.3f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="trained checkpoint dir (e.g. checkpoints/klue/best)")
    ap.add_argument("--test", default=None, help="split to evaluate (default: data/splits/test.jsonl)")
    ap.add_argument("--min-precision", type=float, default=0.98)
    ap.add_argument("--max-office", type=float, default=0.0, help="max tolerated office->class rate")
    args = ap.parse_args()

    test = args.test or str(resolve_path(load_config("data.yaml")["paths"]["splits_dir"]) / "test.jsonl")

    model_only = sweep_thresholds(args.model, test)
    with_val = sweep_thresholds_with_validator(args.model, test)
    _table(f"MODEL ONLY  ({Path(test).name})", model_only)
    _table(f"MODEL + RULE VALIDATOR  ({Path(test).name})", with_val)

    rec = recommend_threshold(with_val, args.min_precision, args.max_office)
    print("\n--- recommendation (full pipeline: model + validator) ---")
    if rec:
        print(f"threshold={rec['threshold']:.2f} -> precision {rec['class_precision']:.3f}, "
              f"recall {rec['class_recall']:.3f}, office→class {rec['office_to_class']:.3f}")
        print(f"Set  class_schedule_confidence_threshold: {rec['threshold']}  in config/train.yaml")
    else:
        print(f"No threshold keeps precision>={args.min_precision} and office→class<={args.max_office}.")
        print("Either relax the guards, improve labels, or try a stronger encoder (xlm-roberta).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
