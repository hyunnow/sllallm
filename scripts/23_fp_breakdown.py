#!/usr/bin/env python3
"""임계값 T(기본 0.5)에서 class_schedule False Positive를 gold 클래스별로 분해한다
(HANDOFF: 임계값 0.5 전환 전 증거). exam/assignment가 수업으로 새는지 눈으로 확인.

두 설정을 나란히:
  (A) 현재 validator          — office만 차단
  (B) + exam/assignment 차단  — validate_candidate(block_events=True)

각 설정에서:
  - class_schedule로 잘못 예측된 것(gold != class_schedule)을 gold 라벨별로 집계
  - (B) 추가: 진짜 수업(gold=class_schedule)을 새 규칙이 잘못 막은 수(=recall 비용)
  - class_schedule precision / recall / office→class

Colab 실행 (학습된 체크포인트 필요):
  python scripts/23_fp_breakdown.py --model checkpoints/encoder/best --threshold 0.5
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import resolve_path
from syllabus_classifier.common.schema import (
    Classification, include_in_class_schedule,
)
from syllabus_classifier.model.evaluate import _row_to_candidate, compute_probs
from syllabus_classifier.model.train import ID2LABEL, load_split, predict_with_threshold
from syllabus_classifier.validator.rules import validate_candidate

CLASS = "class_schedule"


def run(model_dir: str, test_file: str, t: float) -> int:
    rows = load_split(test_file)
    probs = compute_probs(model_dir, rows)
    pred_ids = predict_with_threshold(probs, t)

    def final_label(row, i, block_events):
        label = ID2LABEL[pred_ids[i]]
        cls = Classification(classified_as=label,
                             include_in_class_schedule=include_in_class_schedule(label),
                             confidence=float(probs[i][pred_ids[i]]))
        return validate_candidate(_row_to_candidate(row), cls, block_events=block_events)[0].classified_as

    for block_events in (False, True):
        fp_by_gold = Counter()          # gold != class 인데 class로 예측된 것
        tp = fp = gold_class = blocked_true = 0
        for i, row in enumerate(rows):
            gold = row["label"]
            final = final_label(row, i, block_events)
            if gold == CLASS:
                gold_class += 1
                # recall 비용: 새 규칙 때문에 class에서 빠진 진짜 수업
                if block_events and final != CLASS and final_label(row, i, False) == CLASS:
                    blocked_true += 1
            if final == CLASS:
                if gold == CLASS:
                    tp += 1
                else:
                    fp += 1
                    fp_by_gold[gold] += 1
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / gold_class if gold_class else 0.0
        tag = "B) + exam/assignment 차단" if block_events else "A) 현재 validator (office만)"
        print(f"\n=== {tag}  @ threshold {t} ===")
        print(f"  class_schedule  precision {prec:.3f}  recall {rec:.3f}  (TP {tp} / FP {fp})")
        if block_events:
            print(f"  새 규칙이 막은 진짜 수업(recall 비용): {blocked_true}")
        print(f"  FP를 gold 클래스별로 분해 (수업으로 샌 것):")
        if not fp_by_gold:
            print("    (없음)")
        for gold, n in fp_by_gold.most_common():
            print(f"    {gold:26} {n}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--test", default=None)
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()
    test = args.test or str(resolve_path("data/splits/test.jsonl"))
    return run(args.model, test, args.threshold)


if __name__ == "__main__":
    raise SystemExit(main())
