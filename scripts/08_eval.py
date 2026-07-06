#!/usr/bin/env python3
"""Phase 8 — sweep the class_schedule confidence threshold on the real holdout,
reusing a trained checkpoint (no retraining).

Usage (on Colab, after training):
  python scripts/08_eval.py --model checkpoints/klue/best

Prints precision/recall/office->class at each threshold and recommends the
lowest threshold that keeps precision >= --min-precision (max recall under the
precision guarantee). Put that value in config/train.yaml.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.model.evaluate import recommend_threshold, sweep_thresholds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="trained checkpoint dir (e.g. checkpoints/klue/best)")
    ap.add_argument("--test", default=None, help="test split (default: data/splits/test.jsonl)")
    ap.add_argument("--min-precision", type=float, default=0.98)
    args = ap.parse_args()

    test = args.test or str(resolve_path(load_config("data.yaml")["paths"]["splits_dir"]) / "test.jsonl")
    results = sweep_thresholds(args.model, test)

    print(f"{'thresh':>7} {'precision':>10} {'recall':>8} {'office→class':>13} {'macroF1':>8}")
    for r in results:
        print(f"{r['threshold']:>7.2f} {r['class_precision']:>10.3f} {r['class_recall']:>8.3f} "
              f"{r['office_to_class']:>13.3f} {r['macro_f1']:>8.3f}")

    rec = recommend_threshold(results, args.min_precision)
    if rec:
        print(f"\nRecommended: threshold={rec['threshold']:.2f} -> "
              f"precision {rec['class_precision']:.3f}, recall {rec['class_recall']:.3f}, "
              f"office→class {rec['office_to_class']:.3f}")
        print(f"Set  class_schedule_confidence_threshold: {rec['threshold']}  in config/train.yaml")
    else:
        print(f"\nNo threshold reaches precision >= {args.min_precision}; lower --min-precision or improve labels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
