#!/usr/bin/env python3
"""End-to-end prediction — a syllabus (or a normalized JSON) -> final JSON.

Runs the full pipeline: normalize -> extract candidates -> classify -> rule
validator -> assemble the per-document output (spec Phase 9 / v2 §6).

  # heuristic baseline (no GPU, runs anywhere):
  python scripts/09_predict.py --file "data/normalized/<doc>.json" --model heuristic

  # trained encoder (needs the checkpoint + torch):
  python scripts/09_predict.py --file syllabus.pdf --model checkpoints/klue/best
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config
from syllabus_classifier.extract.normalize_doc import NormalizedDoc, normalize_file
from syllabus_classifier.pipeline import run_pipeline


def load_doc(path: str) -> NormalizedDoc:
    p = Path(path)
    if p.suffix.lower() == ".json":   # already-normalized doc
        return NormalizedDoc.from_dict(json.loads(p.read_text(encoding="utf-8")))
    return normalize_file(str(p))     # raw syllabus -> normalize now


def build_classifier(model: str, threshold: float):
    if model == "heuristic":
        from syllabus_classifier.model import HeuristicClassifier
        return HeuristicClassifier()
    from syllabus_classifier.model import EncoderClassifier
    return EncoderClassifier(model, threshold=threshold)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="syllabus file or normalized .json")
    ap.add_argument("--model", default="heuristic", help="'heuristic' or a checkpoint dir")
    ap.add_argument("--threshold", type=float, default=None, help="class_schedule confidence (default from train.yaml)")
    args = ap.parse_args()

    threshold = args.threshold
    if threshold is None:
        threshold = load_config("train.yaml")["training"]["class_schedule_confidence_threshold"]

    doc = load_doc(args.file)
    clf = build_classifier(args.model, threshold)
    result = run_pipeline(doc, clf)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
