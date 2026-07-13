#!/usr/bin/env python3
"""validator recall 캡 조사 (작업 #20) — 모델 없이 로컬에서.

recall 천장(0.633)은 validator가 진짜 수업(gold=class_schedule)의 일부를 규칙으로
쳐내서 생긴다. 모델이 완벽하다고 가정하고(=gold=class 행마다 model이 class라고
예측했다고 두고) validator를 통과시켜, **어떤 규칙이 진짜 수업을 얼마나 쳐내는지**를
분해한다. 이게 validator가 허용하는 recall 상한 — 모델은 이보다 잘할 수 없다.

Usage:  python scripts/25_validator_recall_probe.py [--split data/splits/test.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import resolve_path
from syllabus_classifier.common.schema import (
    Classification, TimeCandidate, include_in_class_schedule,
)
from syllabus_classifier.validator.rules import validate_candidate


def _cand(r: dict) -> TimeCandidate:
    return TimeCandidate(
        candidate_text=r.get("candidate_text", "") or "",
        section_title=r.get("section_title"), table_row_label=r.get("table_row_label"),
        table_col_label=r.get("table_col_label"),
        nearby_text_before=r.get("nearby_text_before", "") or "",
        nearby_text_after=r.get("nearby_text_after", "") or "",
        date_kind=r.get("date_kind"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default=None)
    args = ap.parse_args()
    split = Path(args.split) if args.split else resolve_path("data/splits/test.jsonl")
    rows = [json.loads(l) for l in split.read_text(encoding="utf-8").splitlines()]
    gold_class = [r for r in rows if r["label"] == "class_schedule"]

    survived = 0
    by_rule = Counter()
    examples: dict[str, list] = {}
    for r in gold_class:
        cls = Classification(classified_as="class_schedule",
                             include_in_class_schedule=True, confidence=1.0)
        out, rej = validate_candidate(_cand(r), cls)      # 모델=완벽 가정
        if out.classified_as == "class_schedule":
            survived += 1
        else:
            reason = (rej or {}).get("reason", out.reason or "?")
            key = reason.split("(")[0].strip()[:40]
            by_rule[key] += 1
            examples.setdefault(key, []).append(
                (r.get("candidate_text", ""), r.get("table_row_label") or r.get("section_title") or ""))

    n = len(gold_class)
    print(f"gold=class_schedule {n}건 | validator 통과 {survived} "
          f"→ validator 허용 recall 상한 {survived/n:.3f}")
    print(f"쳐낸 것 {n - survived}건을 규칙별로:")
    for rule, c in by_rule.most_common():
        print(f"\n  [{c}건] {rule}")
        for txt, ctx in examples[rule][:6]:
            print(f"      cand={txt[:34]!r}  ctx={ctx[:40]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
