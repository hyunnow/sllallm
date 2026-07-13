#!/usr/bin/env python3
"""역방향 학습 (①) — 동결된 규칙·cue로 합성 후보를 생성해 TRAIN을 재균형한다.
학습 자체는 Colab(07_train.py)이 하고, 이 스크립트는 합성 데이터셋을 만들고
검증(라벨 신호 무결성·클래스 균형·누출 없음)한다.

규율:
  - train.jsonl에만 합친다. val/test는 손대지 않는다 (§6 누출 금지).
  - 합성 doc_id는 'synthetic__…' 접두 — split 키가 실문서와 절대 안 겹친다.

산출:
  data/splits/train_synth.jsonl        합성만
  data/splits/train_plus_synth.jsonl   실 train + 합성 (Colab 학습 입력)

Usage:
  python scripts/22_synth_dataset.py --n 1200
  python scripts/07_train.py --train-file data/splits/train_plus_synth.jsonl   # Colab
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import resolve_path
from syllabus_classifier.common.schema import ALL_LABELS
from syllabus_classifier.dataset.synth import generate
from syllabus_classifier.model.infer import (
    _ASSIGN_CUES, _EXAM_CUES, _OFFICE_HOURS_CUES, _TA_CUES,
)

# 라벨별 문맥에 반드시 있어야 하는 cue (합성 무결성 검증) — 없으면 모델이 배울 신호 없음
_REQUIRED_CUES = {
    "exam_time": _EXAM_CUES,
    "assignment_deadline": _ASSIGN_CUES,
    "instructor_office_hours": _OFFICE_HOURS_CUES,
    "ta_office_hours": _TA_CUES,
}


def validate_rows(rows: list[dict]) -> list[str]:
    """합성 무결성: (1) 라벨 유효 (2) cue 신호 존재 (3) office→class 오라벨 없음."""
    errs = []
    for r in rows:
        if r["label"] not in ALL_LABELS:
            errs.append(f"bad label {r['label']}")
        cues = _REQUIRED_CUES.get(r["label"])
        if cues:
            blob = r["input_text"].lower()
            if not any(c.lower() in blob for c in cues):
                errs.append(f"{r['label']} 후보에 cue 없음: {r['input_text'][:50]!r}")
        # office-hours 라벨이 class_schedule 플래그를 켜면 안 된다 (flagship 제약)
        if r["label"].endswith("office_hours") and r["include_in_class_schedule"]:
            errs.append(f"office→class 플래그 오염: {r['doc_id']}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rows = generate(args.n, seed=args.seed)
    errs = validate_rows(rows)
    if errs:
        print(f"합성 무결성 실패 {len(errs)}건:")
        for e in errs[:10]:
            print("  ", e)
        return 1

    splits = resolve_path("data/splits")
    (splits / "train_synth.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    real_train = splits / "train.jsonl"
    merged = list(rows)
    real_n = 0
    if real_train.exists():
        real_rows = [json.loads(l) for l in real_train.read_text(encoding="utf-8").splitlines()]
        real_n = len(real_rows)
        # 누출 가드: 실 train doc_id와 합성 doc_id가 겹치지 않음을 확인
        real_ids = {r.get("doc_id") for r in real_rows}
        assert not (real_ids & {r["doc_id"] for r in rows}), "synthetic doc_id collides with real train!"
        merged = real_rows + rows
    (splits / "train_plus_synth.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in merged), encoding="utf-8")

    syn = Counter(r["label"] for r in rows)
    print(f"합성 {len(rows)}건 생성 (무결성 OK) -> train_synth.jsonl")
    print(f"  클래스: {dict(syn)}")
    if real_n:
        before = Counter(json.loads(l)["label"]
                         for l in (splits / "train.jsonl").read_text(encoding="utf-8").splitlines())
        after = before + syn
        print(f"\n재균형 (실 train {real_n} + 합성 {len(rows)} = {real_n + len(rows)}):")
        for lab in ALL_LABELS:
            b = before.get(lab, 0)
            a = after.get(lab, 0)
            print(f"  {lab:26} {b:>5} -> {a:>5}  (+{a-b})")
    print(f"\nColab 학습: python scripts/07_train.py --train-file data/splits/train_plus_synth.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
