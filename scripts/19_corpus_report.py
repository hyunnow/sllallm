#!/usr/bin/env python3
"""전 코퍼스 레코드 리포트 (HANDOFF §2) — 1,026건 전량을 record로 만들고
필드 채움률 + 상대참조 해석률을 분리해서 잰다. resolver 층(주차→날짜)과 추출
층(값을 냈는가)을 섞지 않는다.

산출:
  - 정규화 품질 분포 (ok/low/needs_ocr/failed) + OCR 백로그 명단
  - 필드별 채움률 (record 단위, 값이 non-null인 문서 비율)
  - 해석률: 상대참조(week N 등) 이벤트 중 KB/문서로 날짜·주범위가 붙은 비율
  - 산출 JSON: data/records/corpus_report.json

Usage:  python scripts/19_corpus_report.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.extract.field_router import route_document
from syllabus_classifier.extract.normalize_doc import NormalizedDoc
from syllabus_classifier.kb.record_resolver import resolve_record_dates
from syllabus_classifier.kb.resolver import KBResolver
from syllabus_classifier.merge import build_record

# (라벨, record 경로 접근자) — record 단위 채움 여부
SCALAR_FIELDS = [
    ("과목명", lambda r: r["course"]["title_ko"] or r["course"]["title_en"]),
    ("학수번호", lambda r: r["meta"]["course_code"]),
    ("대학", lambda r: r["meta"]["school"]),
    ("학과", lambda r: r["meta"]["department"]),
    ("학년도", lambda r: r["meta"]["academic_year"]),
    ("학기", lambda r: r["meta"]["term"]),
    ("학점", lambda r: r["course"]["credits"]),
    ("강의실", lambda r: r["meeting"]["location"]),
    ("수업시간(raw)", lambda r: r["meeting"]["raw_time"]),
    ("교수", lambda r: (r["instructors"] or [{}])[0].get("name_ko")
        or (r["instructors"] or [{}])[0].get("name_en") if r["instructors"] else None),
    ("이메일", lambda r: (r["instructors"] or [{}])[0].get("email") if r["instructors"] else None),
]
LIST_FIELDS = [
    ("총주차", lambda r: r["schedule"].get("total_weeks")),
    ("주차별내용", lambda r: r["schedule"]["weekly_plan"]),
    ("시험", lambda r: r["schedule"]["exams"]),
    ("과제", lambda r: r["schedule"]["assignments"]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    norm_dir = resolve_path(load_config("data.yaml")["paths"]["normalized_dir"])
    files = sorted(norm_dir.glob("*.json"))
    if args.limit:
        files = files[: args.limit]
    kb = KBResolver()

    quality = Counter()
    ocr_backlog: list[str] = []
    fill = Counter()
    n = 0
    # 해석률 카운터
    rel_refs = 0            # date_kind == relative 인 시험/과제 참조 총수
    rel_dated = 0          # 그중 단일 날짜로 해석된 것
    rel_ranged = 0         # 주-범위로 해석된 것 (in_document/KB)
    abs_refs = 0           # 절대 날짜 참조
    docs_with_confirmable = 0

    for fp in files:
        doc = NormalizedDoc.from_dict(json.loads(fp.read_text(encoding="utf-8")))
        quality[doc.extraction_quality] += 1
        text_len = len(doc.full_text.strip())
        # B6-001형: 품질 ok인데 텍스트가 거의 없는 문서 = 실질 스캔본 (미탐지 OCR)
        if doc.extraction_quality in ("needs_ocr", "failed") or text_len < 120:
            ocr_backlog.append(f"{doc.doc_id}  [{doc.extraction_quality}, {text_len}자]")
            continue
        n += 1
        record = build_record(doc, route_document(doc))
        resolve_record_dates(record, kb=kb)
        for label, getter in SCALAR_FIELDS:
            if getter(record) not in (None, ""):
                fill[label] += 1
        for label, getter in LIST_FIELDS:
            v = getter(record)
            if v:
                fill[label] += 1
        doc_has = False
        for kind in ("exams", "assignments"):
            for e in record["schedule"][kind]:
                dk = e.get("date_kind")
                if dk == "absolute":
                    abs_refs += 1
                    doc_has = doc_has or bool(e.get("resolved_date"))
                elif dk == "relative":
                    rel_refs += 1
                    if e.get("resolved_date"):
                        rel_dated += 1
                        doc_has = True
                    elif e.get("resolved_week_start"):
                        rel_ranged += 1
        if doc_has:
            docs_with_confirmable += 1

    print(f"=== 정규화 품질 (전체 {len(files)}건) ===")
    for q, k in quality.most_common():
        print(f"  {q:10} {k:>5}")
    print(f"\nOCR 백로그(스캔·저텍스트·실패): {len(ocr_backlog)}건")
    for line in ocr_backlog[:12]:
        print(f"  - {line[:90]}")
    if len(ocr_backlog) > 12:
        print(f"  ... 외 {len(ocr_backlog) - 12}건")

    print(f"\n=== 필드 채움률 (텍스트 유효 {n}건 기준) ===")
    for label, _ in SCALAR_FIELDS + LIST_FIELDS:
        k = fill[label]
        bar = "█" * int(round(20 * k / max(n, 1)))
        print(f"  {label:14} {k:>5}/{n} ({k/max(n,1):5.0%}) {bar}")

    print(f"\n=== 해석률 (상대참조→날짜, resolver 층) ===")
    print(f"  절대 날짜 참조: {abs_refs}")
    print(f"  상대 참조(week N 등): {rel_refs}  → 단일날짜 {rel_dated} / 주범위 {rel_ranged} / "
          f"미해석 {rel_refs - rel_dated - rel_ranged}")
    if rel_refs:
        print(f"  상대참조 해석 성공률(날짜+범위): {(rel_dated + rel_ranged)/rel_refs:.0%}")
    print(f"  최소 1개 이상 확정가능 일정 보유 문서: {docs_with_confirmable}/{n}")

    report = {
        "total_files": len(files), "text_valid": n,
        "quality": dict(quality), "ocr_backlog": ocr_backlog,
        "fill_rate": {label: fill[label] for label, _ in SCALAR_FIELDS + LIST_FIELDS},
        "resolution": {"absolute": abs_refs, "relative": rel_refs,
                       "relative_dated": rel_dated, "relative_ranged": rel_ranged,
                       "docs_with_confirmable": docs_with_confirmable},
    }
    out = resolve_path("data/records/corpus_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
