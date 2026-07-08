"""Bridge to the user's original comparison Excel (ParserTest.xlsx, v4 §4).

The Excel IS the method harness: 1 syllabus = 1 row; 13 fields × 4 versions
(정답 gold / 룰 rule / LLM llm / 하이브리드 hybrid) + auto OK flags + 오류유형 +
원문텍스트(ML input). This module loads it, RE-SCORES independently (exact
match per the 읽어보기 rules: blank gold or blank prediction is excluded), and
reports per-field win rates.

CAVEAT that must never be forgotten when reading these numbers: gold was
PRE-FILLED with the hybrid outputs (readme: "정답(하이브리드 값 프리필)") and every
row is still 상태=라벨대기 — until a human reviews, accuracy vs gold is biased
toward hybrid. Coverage (how often a method outputs anything) is unbiased.

The Excel stays git-ignored (local only).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Optional

# NOTE: 학수번호 added 2026-07 (user request) — absent from ParserTest.xlsx and
# the batch-2 workbook (both predate it); loaders return None there, scoring
# skips it until gold exists. Future review builds include it automatically.
FIELDS = ["과목명", "학수번호", "교수", "연락처", "학점", "강의실", "총주차", "수업시간",
          "이벤트", "무기한과제", "주차별내용", "대학", "학년도", "학기"]
METHODS = {"rule": "룰", "llm": "LLM", "hybrid": "하이브리드"}
GOLD_PENDING_STATUS = "파싱완료(라벨대기)"


def load_rows(path: "str | Path" = "ParserTest.xlsx") -> list[dict]:
    """One dict per filled syllabus row: meta + per-field {gold,rule,llm,hybrid}."""
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb["데이터셋"]
    raw = list(ws.iter_rows(values_only=True))
    header = raw[0]
    idx = {h: i for i, h in enumerate(header)}
    id_col = idx.get("syllabus_id", 0)   # header-keyed, not positional
    body = [r for r in raw[1:] if r and r[id_col]]

    def cell(row, col) -> Optional[str]:
        i = idx.get(col)
        if i is None:
            return None
        v = row[i]
        s = str(v).strip() if v is not None else ""
        return s or None

    out = []
    for r in body:
        rec = {
            "syllabus_id": cell(r, "syllabus_id"),
            "source_file": cell(r, "파일명"),
            "school": cell(r, "대학"),
            "status": cell(r, "상태"),
            "error_type": cell(r, "오류유형"),
            "source_text": cell(r, "원문텍스트(ML입력)"),
            "fields": {},
        }
        for f in FIELDS:
            rec["fields"][f] = {
                "gold": cell(r, f"정답_{f}"),
                "rule": cell(r, f"룰_{f}"),
                "llm": cell(r, f"LLM_{f}"),
                "hybrid": cell(r, f"하이브리드_{f}"),
            }
        out.append(rec)
    return out


def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip().lower()
    s = re.sub(r"[–—]", "-", s)                  # en/em dashes == hyphen
    s = re.sub(r"\s*([;|~:])\s*", r"\1", s)      # spacing around separators is not a difference
    # numeric surface: "3.0" == "3" (credits/weeks written either way)
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s


def exact_ok(pred: Optional[str], gold: Optional[str]) -> Optional[bool]:
    """Readme rule: blank gold OR blank prediction -> excluded (None)."""
    if not gold or not pred:
        return None
    return _norm(pred) == _norm(gold)


def ours_for_excel_fields(source_text: str, doc_id: str) -> dict[str, object]:
    """Run OUR extractor on FLAT TEXT (pseudo-tables) and map to Excel fields."""
    from ..extract.normalize_doc import normalize_text_blob

    return ours_fields_from_doc(normalize_text_blob(doc_id, source_text))


def ours_fields_from_doc(doc) -> dict[str, object]:
    """Run OUR rule+subsystem extractor on a NormalizedDoc (real tables when the
    doc came from the corpus) and map to the Excel field names."""
    from ..extract.field_router import route_document

    out = route_document(doc)
    rule, sub = out.get("rule", {}), out.get("subsystem", {})

    def events_serialized():
        # 4-part contract per the 읽어보기 notation:
        #   제목 | 타입(exam/assignment/other) | 날짜(raw) | 날짜종류
        parts = []
        for kind, key in (("exam", "schedule.exams"), ("assignment", "schedule.assignments")):
            for e in sub.get(key) or []:
                title = e.get("title") or "?"
                parts.append(f"{title} | {kind} | {e['raw_reference']} | {e['date_kind']}")
        return " ; ".join(parts) or None

    def class_time():
        if rule.get("meeting.raw_time"):
            return rule["meeting.raw_time"]
        evs = sub.get("meeting.events") or []
        return " ; ".join(e["raw"] for e in evs) or None

    def weekly_plan_serialized():
        rows = sub.get("schedule.weekly_plan") or []
        parts = [f"Week {r['week']}: {r['topic']}" for r in rows
                 if r.get("week") is not None and (r.get("topic") or "").strip()]
        return " ; ".join(parts) or None

    contact = " ; ".join(v for v in (rule.get("instructors.email"), rule.get("instructors.phone")) if v) or None
    # our internal term values -> the Excel notation {1, 2, 여름, 겨울}
    term = {"summer": "여름", "winter": "겨울"}.get(rule.get("meta.term"), rule.get("meta.term"))
    return {
        "과목명": rule.get("course.title_ko") or rule.get("course.title_en"),
        "학수번호": rule.get("meta.course_code"),
        "교수": rule.get("instructors.name"),
        "연락처": contact,
        "학점": rule.get("course.credits"),
        "강의실": rule.get("meeting.location"),
        "총주차": sub.get("schedule.total_weeks"),
        "수업시간": class_time(),
        "이벤트": events_serialized(),
        "무기한과제": None,                 # undated assignments not captured yet
        "주차별내용": weekly_plan_serialized(),
        "대학": rule.get("meta.school"),
        "학년도": rule.get("meta.academic_year"),
        "학기": term,
    }


def score_rows(rows: list[dict]) -> dict:
    """Per-field: coverage per method + accuracy-vs-gold (with the prefill caveat)."""
    n = len(rows)
    table = {}
    for f in FIELDS:
        stats = {}
        for m in METHODS:
            preds = [r["fields"][f][m] for r in rows]
            golds = [r["fields"][f]["gold"] for r in rows]
            cov = sum(1 for p in preds if p)
            verdicts = [exact_ok(p, g) for p, g in zip(preds, golds)]
            scored = [v for v in verdicts if v is not None]
            stats[m] = {
                "coverage": cov,
                "n_scored": len(scored),
                "acc": (sum(scored) / len(scored)) if scored else None,
            }
        gold_cov = sum(1 for r in rows if r["fields"][f]["gold"])
        # how often gold literally equals hybrid — the prefill-bias indicator
        same = [exact_ok(r["fields"][f]["hybrid"], r["fields"][f]["gold"]) for r in rows]
        same = [v for v in same if v is not None]
        table[f] = {
            "n_docs": n,
            "gold_filled": gold_cov,
            "gold_equals_hybrid_rate": (sum(same) / len(same)) if same else None,
            "methods": stats,
        }
    return table


def print_summary(table: dict) -> None:
    print(f"{'field':10} {'gold':>4} | {'rule cov/acc':>14} | {'llm cov/acc':>14} | {'hybrid cov/acc':>15} | g==hyb")
    for f, t in table.items():
        def fmt(m):
            s = t["methods"][m]
            acc = f"{s['acc']:.2f}" if s["acc"] is not None else "  - "
            return f"{s['coverage']:>4}/{acc}"
        geq = t["gold_equals_hybrid_rate"]
        geq_s = f"{geq:.2f}" if geq is not None else "-"
        print(f"{f:10} {t['gold_filled']:>4} | {fmt('rule'):>14} | {fmt('llm'):>14} | {fmt('hybrid'):>15} | {geq_s}")
