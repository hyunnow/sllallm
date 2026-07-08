#!/usr/bin/env python3
"""v7 §5 — KB coverage metrics: how date/time references actually resolve.

Reports, over the normalized corpus:
  A. dated events (exams/assignments): share resolved by in-document dates vs
     needing the academic-calendar KB, split CURRENT/UPCOMING (>=2026) vs PAST
     — past needs_review is NORMAL (product targets current terms only).
  B. 교시 usage: docs using period notation vs timetable-KB coverage.

Usage:  python scripts/15_kb_coverage.py [--sample N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.extract.field_router import extract_subsystem
from syllabus_classifier.extract.normalize_doc import NormalizedDoc
from syllabus_classifier.extract.rule_fields import extract_academic_year

CURRENT_YEAR = 2026     # product goal: current + upcoming terms (v7 §0)
PERIOD = re.compile(r"\d\s*교시")

# corpus school -> timetable KB key
TIMETABLE_KEY = {"연세대": "yonsei_seoul", "건국대": "konkuk", "이화여대": "ewha",
                 "홍익대": "hongik", "동국대": "dongguk"}


def school_of(doc_id: str) -> str:
    doc_id = unicodedata.normalize("NFC", doc_id)
    seg = doc_id.split("__")
    top = seg[0]
    if top == "kocw_syllabi" and len(seg) > 1:
        s = re.sub(r"^\d+_", "", seg[1])
    elif top == "7_6" and len(seg) > 1:
        s = seg[1]
    else:
        s = {"Kaist": "KAIST", "Unist": "UNIST", "hanyang_syllabi_302": "한양대학교",
             "YISSSyllabus": "연세대학교", "NYU_Stern_Syllabus": "NYU",
             "가천대": "가천대학교"}.get(top, top)
    return s.replace("학교", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    args = ap.parse_args()

    norm_dir = resolve_path(load_config("data.yaml")["paths"]["normalized_dir"])
    timetables = load_config("period_timetables.yaml").get("timetables", {})
    files = sorted(norm_dir.glob("*.json"))
    if args.sample:
        files = files[:args.sample]

    ev = Counter()          # event resolution paths
    period_docs = []        # (school, covered?)
    docs_current = docs_past = docs_unknown = 0

    for fp in files:
        doc = NormalizedDoc.from_dict(json.loads(fp.read_text(encoding="utf-8")))
        year = extract_academic_year(doc)
        era = "current" if (year and year >= CURRENT_YEAR) else ("past" if year else "unknown")
        docs_current += era == "current"
        docs_past += era == "past"
        docs_unknown += era == "unknown"

        sub = extract_subsystem(doc)
        from syllabus_classifier.kb.resolver import (
            CALENDAR_KEY_BY_SCHOOL_2026_FALL, calendar_usable,
        )
        calendars = load_config("academic_calendars.yaml").get("calendars", {})
        # school_of returns short names; the calendar map is keyed on canonical —
        # match by prefix (연세대 -> 연세대학교)
        s_short = school_of(doc.doc_id)
        cal_key = next((v for k, v in CALENDAR_KEY_BY_SCHOOL_2026_FALL.items()
                        if k.startswith(s_short) or s_short in ("NYU",) and "NYU" in v), None)
        cal_ok = calendar_usable(calendars.get(cal_key)) if cal_key else False
        for e in sub.get("schedule.exams", []) + sub.get("schedule.assignments", []):
            if e.get("resolved_by") == "in_document":
                ev["in_document"] += 1
            elif e.get("date_kind") == "absolute" and e.get("resolved_date"):
                ev["in_document"] += 1
            elif e.get("date_kind") in ("relative", "uncertain", "recurring"):
                if era == "current" and cal_ok:
                    ev["calendar_kb_resolvable"] += 1
                else:
                    ev[f"unresolved_{era}"] += 1

        if PERIOD.search(doc.full_text):
            key = TIMETABLE_KEY.get(school_of(doc.doc_id))
            covered = bool(key and timetables.get(key, {}).get("periods"))
            period_docs.append((school_of(doc.doc_id), covered))

    n_ev = sum(ev.values())
    print(f"=== A. dated-event resolution paths ({len(files)} docs, {n_ev} dated events) ===")
    print(f"  in_document (문서 내 날짜로 해결)      : {ev['in_document']:5}  ({ev['in_document']/max(n_ev,1):.0%})")
    print(f"  calendar KB로 해결 가능 (high-conf 기입됨): {ev['calendar_kb_resolvable']:5}")
    print(f"  needs calendar KB — 미기입/저신뢰      : {ev['unresolved_current']:5}  <- 남은 actionable")
    print(f"  needs_review — PAST terms (정상)      : {ev['unresolved_past']:5}  <- 제품 목표 밖, 실패 아님 (v7 §5)")
    print(f"  needs_review — year unknown          : {ev['unresolved_unknown']:5}")
    print(f"  (doc era: current {docs_current} / past {docs_past} / unknown {docs_unknown})")

    print(f"\n=== B. 교시 -> timetable KB coverage ===")
    n_p = len(period_docs)
    cov = sum(1 for _, c in period_docs if c)
    print(f"  docs using 교시: {n_p}  | timetable-covered: {cov}  | needs_review: {n_p-cov}")
    for s, c in sorted(period_docs):
        print(f"    {s:8} {'OK (KB)' if c else 'needs_review (KB 미기입)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
