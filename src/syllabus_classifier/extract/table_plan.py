"""Phase 4 — weekly-plan table extractor (v6 §1).

Structure is RULE-driven: header keywords fix the column map; a numeric first
column is the fallback. The LLM is never asked to infer table structure.

The risk rule is abstain-on-uncertain (v6 §1-2): tables corrupt silently — one
shifted column misaligns every row — so on shift/discontinuity we mark
needs_review and do NOT emit weekly rows or promote events from that table.

In-table events (v6 §1-3): a row whose topic mentions exam/assignment cues is
promoted to an event with date_kind=relative (Week N). If the row carries an
explicit date (기간 column), that date resolves it as in_document (v7 §2
priority 1) — no calendar KB needed. Never a fabricated date.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..normalize import normalize_date

_WEEK_H = re.compile(r"^\s*(?:주\s*차?|week|wk|제?\s*\d*\s*주)\s*$", re.I)
_DATE_H = re.compile(r"기간|날짜|일자|date|일정", re.I)
# topic column selection is TIERED (batch-2 gold evidence: reviewers take the
# short 주제/제목 column, not the long 학습목표/상세내용 one — B2-001/010/013):
#   tier 1: explicit topic headers   tier 2: content-ish fallback
# and some headers are NEVER the topic (핵심어 B2-003, 학습목표, 방법, 추가설명).
_TOPIC_H1 = re.compile(r"주제|제목|단원|강의\s*주제|topic|subject|title", re.I)
_TOPIC_H2 = re.compile(r"수업\s*내용|강의\s*내용|학습\s*내용|내용|content", re.I)
_TOPIC_EXCLUDE = re.compile(r"핵심어|키워드|keyword|목표|objective|방법|method|평가|과제|추가\s*설명|비고", re.I)
_BOOK_H = re.compile(r"교재|범위|reading|chapter|자료", re.I)
_REMARK_H = re.compile(r"비고|remark|note|기타", re.I)

_WEEK_CELL = re.compile(r"^\s*(?:제)?\s*(\d{1,2})\s*(?:주차?|週)?\s*$|^\s*week\s*(\d{1,2})\s*$", re.I)
_DATE_LIKE = re.compile(r"\d{1,4}\s*[./\-]\s*\d{1,2}(\s*[./\-]\s*\d{1,2})?|(\d{1,2}\s*월\s*\d{1,2}\s*일)")
_FILENAMEY = re.compile(r"\.(pdf|pptx?|hwp|docx?|zip)\b|week\s*\d+\s*$", re.I)

_EXAM_CUE = re.compile(r"중간\s*고사|기말\s*고사|중간\s*시험|기말\s*시험|midterm|final\s*exam|\bexam\b|퀴즈|quiz|시험", re.I)
_ASSIGN_CUE = re.compile(r"과제|assignment|homework|레포트|리포트|report\s*due|제출|presentation|발표", re.I)


@dataclass
class PlanRow:
    week: Optional[int]
    date_range: Optional[str] = None
    topic: Optional[str] = None
    textbook_range: Optional[str] = None
    remarks: Optional[str] = None


@dataclass
class WeeklyPlan:
    rows: list[PlanRow] = field(default_factory=list)
    total_weeks: Optional[int] = None
    events: list[dict] = field(default_factory=list)
    needs_review: bool = False
    issues: list[str] = field(default_factory=list)


def _colmap_from_header(header: list[str]) -> Optional[dict]:
    cmap: dict = {}
    topic_tier = 99
    for i, cell in enumerate(header or []):
        c = (cell or "").strip()
        if not c:
            continue
        if "week" not in cmap and _WEEK_H.match(c):
            cmap["week"] = i
        elif "date" not in cmap and _DATE_H.search(c):
            cmap["date"] = i
        elif not _TOPIC_EXCLUDE.search(c) and _TOPIC_H1.search(c) and topic_tier > 1:
            cmap["topic"], topic_tier = i, 1
        elif not _TOPIC_EXCLUDE.search(c) and _TOPIC_H2.search(c) and topic_tier > 2:
            cmap["topic"], topic_tier = i, 2
        elif "book" not in cmap and _BOOK_H.search(c):
            cmap["book"] = i
        elif "remark" not in cmap and _REMARK_H.search(c):
            cmap["remark"] = i
    return cmap if "week" in cmap and "topic" in cmap else None


def _parse_week(cell: str) -> Optional[int]:
    m = _WEEK_CELL.match(cell or "")
    if not m:
        return None
    n = int(m.group(1) or m.group(2))
    return n if 1 <= n <= 30 else None


def _numeric_first_col(table) -> Optional[dict]:
    """Headerless fallback: first column mostly week numbers -> week col 0,
    topic = the column with the most text."""
    rows = table.rows or []
    if len(rows) < 3:
        return None
    hits = sum(1 for r in rows if r and _parse_week(r[0] or "") is not None)
    if hits < max(3, int(0.6 * len(rows))):
        return None
    width = max(len(r) for r in rows)
    if width < 2:
        return None
    text_len = [0] * width
    for r in rows:
        for i in range(1, min(width, len(r))):
            cell = r[i] or ""
            if not _parse_week(cell):
                text_len[i] += len(cell)
    topic = max(range(1, width), key=lambda i: text_len[i])
    cmap = {"week": 0, "topic": topic}
    for i in range(1, width):
        if i != topic and any(_DATE_LIKE.search(r[i] or "") for r in rows if i < len(r)):
            cmap["date"] = i
            break
    return cmap


def _check_alignment(rows: list[PlanRow]) -> list[str]:
    issues = []
    weeks = [r.week for r in rows if r.week is not None]
    if not weeks:
        return ["no_week_numbers"]
    if len(set(weeks)) != len(weeks):
        issues.append("duplicate_weeks")
    if weeks != sorted(weeks):
        issues.append("weeks_not_monotonic")
    expected = list(range(min(weeks), min(weeks) + len(weeks)))
    if sorted(set(weeks)) != expected:
        issues.append("week_gap")
    # shift: topic cells that are dates/filenames in 2+ rows (SYL-031)
    shifty = sum(1 for r in rows if r.topic and (_DATE_LIKE.fullmatch(r.topic.strip())
                                                 or _FILENAMEY.search(r.topic)))
    if shifty >= 2:
        issues.append("column_shift")
    return issues


def _row_date(date_cell: Optional[str]) -> Optional[str]:
    """Normalize a plan-row date (start of range) to ISO if a full date exists."""
    if not date_cell:
        return None
    first = re.split(r"[~〜–—]|부터", date_cell)[0].strip()
    return normalize_date(first)


def _events_from_rows(rows: list[PlanRow]) -> list[dict]:
    events = []
    for r in rows:
        if r.week is None or not r.topic:
            continue
        blob = f"{r.topic} {r.remarks or ''}"
        is_exam = _EXAM_CUE.search(blob)
        is_assign = _ASSIGN_CUE.search(blob)
        if not (is_exam or is_assign):
            continue
        resolved = _row_date(r.date_range)
        full = resolved is not None and len(resolved) == 10
        events.append({
            "title": r.topic.strip()[:80],
            "type": "midterm" if re.search(r"중간|midterm", blob, re.I)
                    else "final" if re.search(r"기말|final", blob, re.I)
                    else ("quiz" if re.search(r"퀴즈|quiz", blob, re.I) else None),
            "kind": "exam" if is_exam else "assignment",
            "raw_reference": f"Week {r.week}",
            "date_kind": "relative",
            "resolved_date": resolved if full else None,
            "resolved_by": "in_document" if full else None,   # v7 §2 priority 1
            "needs_review": not full,
        })
    return events


def _rows_from_table(table) -> list[PlanRow]:
    cmap = _colmap_from_header(table.header) or _numeric_first_col(table)
    if not cmap:
        return []
    rows = []
    for raw in table.rows:
        def cell(key):
            i = cmap.get(key)
            if i is None or i >= len(raw):
                return None
            # PDF cells wrap mid-word — collapse internal whitespace
            return re.sub(r"\s+", " ", raw[i] or "").strip() or None
        week = _parse_week(cell("week") or "")
        if week is None and not (cell("topic") or "").strip():
            continue
        rows.append(PlanRow(week=week, date_range=cell("date"), topic=cell("topic"),
                            textbook_range=cell("book"), remarks=cell("remark")))
    rows = [r for r in rows if r.week is not None or r.topic]
    return rows if len([r for r in rows if r.week is not None]) >= 2 else []


def _plan_from_rows(rows: list[PlanRow]) -> WeeklyPlan:
    issues = _check_alignment(rows)
    plan = WeeklyPlan(rows=rows, issues=issues)
    if issues:
        # abstain-on-uncertain: corrupted alignment must not emit values
        plan.needs_review = True
        plan.rows = []
        plan.total_weeks = None
    else:
        weeks = [r.week for r in rows if r.week is not None]
        plan.total_weeks = max(weeks)
        plan.events = _events_from_rows(rows)
    return plan


def parse_weekly_plan(doc) -> WeeklyPlan:
    """Find and parse the weekly-plan table(s) of a NormalizedDoc.

    A plan often SPANS PAGES as several tables (weeks 1-13 + 14-16). Fragments
    with disjoint week sets are merged before the alignment checks — taking only
    the biggest fragment silently drops the final weeks (the SYL-022 15-vs-16
    failure, reproduced on B2-002)."""
    fragments: list[list[PlanRow]] = []
    for page in doc.pages:
        for table in page.tables:
            rows = _rows_from_table(table)
            if rows:
                fragments.append(rows)
    if not fragments:
        return WeeklyPlan()

    # merge fragments whose week sets don't overlap (page-split plans)
    fragments.sort(key=lambda rs: min((r.week for r in rs if r.week is not None), default=99))
    merged: list[PlanRow] = []
    seen_weeks: set[int] = set()
    for rs in fragments:
        weeks = {r.week for r in rs if r.week is not None}
        if weeks and not (weeks & seen_weeks):
            merged.extend(rs)
            seen_weeks |= weeks
    candidates = [merged] + sorted(fragments, key=len, reverse=True)

    first: Optional[WeeklyPlan] = None
    for rows in candidates:
        plan = _plan_from_rows(rows)
        first = first or plan
        if not plan.needs_review and plan.rows:
            return plan                      # first clean candidate wins (merged preferred)
    return first or WeeklyPlan()
