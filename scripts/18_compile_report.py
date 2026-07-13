#!/usr/bin/env python3
"""Phase H (v3 §11) — 문서→record→해석→컴파일→ICS 전 구간 리포트.

resolver 정확도(§15류)와 분리해 COMPILER 층의 산출·위험 지표만 잰다:
  - 버킷 분포: confirmed / weekly_timetable / needs_review
  - 위험 지표(전부 0이어야 함):
      · 근거 없는 확정 이벤트 (resolved_by 없는 confirmed)
      · 공휴일에 떨어지는 확정 수업 발생일 (RRULE 전개 후 EXDATE 누락 검출)
      · 면담시간이 수업으로 컴파일
  - --ics N: 앞 N개 문서의 ICS를 data/records/ics/ 에 저장 (눈 검수용, git 제외)

Usage:
  python scripts/18_compile_report.py --sample 40 --ics 5
  python scripts/18_compile_report.py --batch 7 --ics 3     # gold 배치 문서로
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.compile import compile_record, write_ics
from syllabus_classifier.extract.field_router import route_document
from syllabus_classifier.extract.normalize_doc import NormalizedDoc
from syllabus_classifier.kb.resolver import KBResolver
from syllabus_classifier.merge import build_record

_BYDAY_WD = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _class_occurrences(ev: dict) -> list[str]:
    """RRULE WEEKLY 이벤트의 발생일 전개 (검증용) — EXDATE 제외 후 반환."""
    if ev.get("all_day") or not ev.get("rrule"):
        return []
    start = date.fromisoformat(ev["dtstart"][:10])
    until = date.fromisoformat(
        f"{ev['rrule'].split('UNTIL=')[1][:8][:4]}-{ev['rrule'].split('UNTIL=')[1][4:6]}-{ev['rrule'].split('UNTIL=')[1][6:8]}")
    ex = set(ev.get("exdate") or [])
    out, cur = [], start
    while cur <= until:
        iso = cur.isoformat()
        if iso not in ex:
            out.append(iso)
        cur += timedelta(days=7)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--batch", type=int, help="gold 배치 문서 사용 (drafts_batchN 매핑)")
    ap.add_argument("--ics", type=int, default=0, help="앞 N개 문서의 ICS 저장")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--model", default="heuristic",
                    help="'heuristic'(기본) 또는 학습 체크포인트 경로")
    args = ap.parse_args()

    from syllabus_classifier.model import load_classifier
    clf = load_classifier(args.model)

    norm_dir = resolve_path(load_config("data.yaml")["paths"]["normalized_dir"])
    if args.batch:
        files = []
        for line in Path(f"data/gold/drafts_batch{args.batch}.jsonl").read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            fp = norm_dir / f"{d['doc_id']}.json"
            if fp.exists():
                files.append(fp)
    else:
        files = sorted(norm_dir.glob("*.json"))
        rng = random.Random(args.seed)
        if args.sample and args.sample < len(files):
            files = rng.sample(files, args.sample)

    kb = KBResolver()
    ics_dir = resolve_path("data/records/ics")
    stats = Counter()
    risk = Counter()
    review_reasons = Counter()
    written = 0

    for fp in files:
        doc = NormalizedDoc.from_dict(json.loads(fp.read_text(encoding="utf-8")))
        record = build_record(doc, route_document(doc, classifier=clf))
        out = compile_record(record, kb=kb)
        stats["docs"] += 1
        stats["confirmed"] += out["stats"]["confirmed"]
        stats["timetable_slots"] += out["stats"]["timetable_slots"]
        stats["needs_review"] += out["stats"]["needs_review"]
        if out["stats"]["confirmed"]:
            stats["docs_with_confirmed"] += 1
        if out["stats"]["timetable_slots"]:
            stats["docs_with_timetable"] += 1

        cal = kb._calendars.get(out["course"].get("calendar_key") or "") or {}
        holidays = set(cal.get("holidays", [])) | set(cal.get("school_holidays", []))
        for ev in out["confirmed_events"]:
            if not ev.get("resolved_by"):
                risk["unfounded_confirmed"] += 1
            if "면담" in ev.get("summary", ""):
                risk["office_hours_as_class"] += 1
            for occ in _class_occurrences(ev):
                if occ in holidays:
                    risk["class_on_holiday"] += 1
        for ev in out["needs_review_events"]:
            review_reasons[(ev.get("review_reason") or "")[:34]] += 1

        if args.ics and written < args.ics and out["confirmed_events"]:
            ics_dir.mkdir(parents=True, exist_ok=True)
            name = "".join(c if c.isalnum() else "_" for c in doc.doc_id)[:60] + ".ics"
            (ics_dir / name).write_text(write_ics(out), encoding="utf-8")
            written += 1

    print(f"docs {stats['docs']} | confirmed 이벤트 {stats['confirmed']} "
          f"(문서 {stats['docs_with_confirmed']}) | 시간표 슬롯 {stats['timetable_slots']} "
          f"(문서 {stats['docs_with_timetable']}) | needs_review {stats['needs_review']}")
    print(f"위험 지표 (모두 0 목표): 근거없는 확정 {risk['unfounded_confirmed']} / "
          f"공휴일 수업 발생 {risk['class_on_holiday']} / 면담 혼입 {risk['office_hours_as_class']}")
    print("\nneeds_review 사유 상위:")
    for reason, n in review_reasons.most_common(8):
        print(f"  {n:3}  {reason}")
    if written:
        print(f"\nICS {written}건 -> {ics_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
