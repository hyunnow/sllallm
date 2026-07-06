#!/usr/bin/env python3
"""v5 §3-1 — COVERAGE-ONLY comparison: our extractor vs the Excel's three
stored methods (룰/LLM/하이브리드) on the same 37 syllabi, using the Excel's own
원문텍스트 column as input (the same ML input their methods used).

Coverage = "did the method output anything for this field". It needs no gold and
is unbiased. It says NOTHING about correctness — accuracy claims wait for
trusted gold (v5 §1). This script prints that caveat with the table.

Usage:  python scripts/11_coverage_compare.py [--xlsx ParserTest.xlsx]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.eval.excel_harness import FIELDS, load_rows
from syllabus_classifier.extract.field_router import route_document
from syllabus_classifier.extract.normalize_doc import normalize_text_blob


def ours_for_excel_fields(source_text: str, doc_id: str) -> dict[str, object]:
    """Run our rule+subsystem on the raw text and map to the 13 Excel fields."""
    doc = normalize_text_blob(doc_id, source_text)
    out = route_document(doc)
    rule, sub = out.get("rule", {}), out.get("subsystem", {})

    def events_serialized():
        evs = (sub.get("schedule.exams") or []) + (sub.get("schedule.assignments") or [])
        return " ; ".join(
            f"{e.get('type') or e.get('title') or '?'} | {e['raw_reference']} | {e['date_kind']}"
            for e in evs
        ) or None

    def class_time():
        if rule.get("meeting.raw_time"):
            return rule["meeting.raw_time"]
        evs = sub.get("meeting.events") or []
        return " ; ".join(e["raw"] for e in evs) or None

    contact = " ; ".join(v for v in (rule.get("instructors.email"), rule.get("instructors.phone")) if v) or None
    return {
        "과목명": rule.get("course.title_ko") or rule.get("course.title_en"),
        "교수": rule.get("instructors.name"),
        "연락처": contact,
        "학점": rule.get("course.credits"),
        "강의실": rule.get("meeting.location"),
        "총주차": None,                    # not implemented yet (Phase 4 table work)
        "수업시간": class_time(),
        "이벤트": events_serialized(),
        "무기한과제": None,                 # undated assignments not captured yet
        "주차별내용": None,                 # Phase 4 weekly-plan table
        "대학": rule.get("meta.school"),
        "학년도": rule.get("meta.academic_year"),
        "학기": rule.get("meta.term"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default="ParserTest.xlsx")
    args = ap.parse_args()

    all_rows = load_rows(args.xlsx)
    # keep the same-input claim true by construction: compare ONLY on rows that
    # have 원문텍스트 (ours runs on it), and report anything excluded.
    rows = [r for r in all_rows if r["source_text"]]
    skipped = len(all_rows) - len(rows)
    n = len(rows)
    ours_cov = {f: 0 for f in FIELDS}
    for r in rows:
        ours = ours_for_excel_fields(r["source_text"], r["syllabus_id"])
        for f in FIELDS:
            if ours.get(f) not in (None, ""):
                ours_cov[f] += 1

    print(f"=== COVERAGE ONLY — {n} docs, same 원문텍스트 input"
          + (f" ({skipped} rows without 원문텍스트 excluded from BOTH sides)" if skipped else "") + " ===")
    print("(값을 냈는가일 뿐, 맞았는가가 아님 — 정확도는 신뢰 gold 이후에만. v5 §3-1)\n")
    print(f"{'field':10} {'기존룰':>6} {'기존LLM':>7} {'기존하이브리드':>9} {'우리(rule+sub)':>13}")
    for f in FIELDS:
        old = {m: sum(1 for r in rows if r["fields"][f][m]) for m in ("rule", "llm", "hybrid")}
        print(f"{f:10} {old['rule']:>6} {old['llm']:>8} {old['hybrid']:>12} {ours_cov[f]:>13}")
    print("\n미구현 필드(총주차/무기한과제/주차별내용)는 정직하게 0으로 보고.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
