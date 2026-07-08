"""Record-level date resolution (v7 §2, final wiring): take a built syllabus
record and resolve its relative schedule references through the calendar KB.

Rules enforced here:
  - only HIGH-confidence calendars produce dates (calendar_usable);
  - "Week N Thu" -> a concrete date; holiday collisions keep needs_review;
  - "Week N" without a weekday NEVER becomes a single invented date — it gets
    the week's [monday..sunday] RANGE and stays tentative (v2 §4: week-only
    references are not fixed dates);
  - anything in_document-resolved earlier is left untouched (priority 1).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from .resolver import (
    CALENDAR_KEY_BY_SCHOOL_2026_FALL,
    KBResolver,
    calendar_usable,
    resolve_week_reference,
)

_SUMMER_KEYS = {
    "연세대학교": "yonsei__2026_summer",
    "이화여자대학교": "ewha__2026_summer",
}

_WD_EN = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday",
          "fri": "Friday", "sat": "Saturday", "sun": "Sunday"}
_WD_KO = {"월": "Monday", "화": "Tuesday", "수": "Wednesday", "목": "Thursday",
          "금": "Friday", "토": "Saturday", "일": "Sunday"}

_WEEK_REF = re.compile(r"week\s*(\d{1,2})|(\d{1,2})\s*주차", re.IGNORECASE)
_WD_REF = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b|(?<![가-힣])([월화수목금토일])(?:요일)?(?![가-힣])",
                     re.IGNORECASE)


def calendar_key_for(school: Optional[str], year, term) -> Optional[str]:
    """Current/upcoming 2026 terms only (v7 policy)."""
    if not school or year != 2026:
        return None
    t = str(term or "").lower()
    if t in ("2", "fall", "가을"):
        return CALENDAR_KEY_BY_SCHOOL_2026_FALL.get(school)
    if t in ("summer", "여름"):
        return _SUMMER_KEYS.get(school)
    return None


def _parse_week_ref(raw: str) -> tuple[Optional[int], Optional[str]]:
    m = _WEEK_REF.search(raw or "")
    if not m:
        return None, None
    week = int(m.group(1) or m.group(2))
    wd = _WD_REF.search(raw)
    weekday = None
    if wd:
        weekday = _WD_EN.get((wd.group(1) or "").lower()[:3]) or _WD_KO.get(wd.group(2) or "")
    return week, weekday


def _week_range(term_start_iso: str, week: int) -> tuple[str, str]:
    start = date.fromisoformat(term_start_iso)
    monday = start - timedelta(days=start.weekday()) + timedelta(weeks=week - 1)
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


def resolve_record_dates(record: dict, kb: Optional[KBResolver] = None) -> dict:
    """Resolve relative exam/assignment references in-place. Returns counters."""
    kb = kb or KBResolver()
    meta = record.get("meta", {})
    key = calendar_key_for(meta.get("school"), meta.get("academic_year"), meta.get("term"))
    cal = kb._calendars.get(key) if key else None
    stats = {"resolved_date": 0, "resolved_range": 0, "skipped": 0}
    if not calendar_usable(cal):
        return stats

    for kind in ("exams", "assignments"):
        for entry in record.get("schedule", {}).get(kind, []):
            if entry.get("resolved_date") or entry.get("date_kind") != "relative":
                stats["skipped"] += 1
                continue
            week, weekday = _parse_week_ref(entry.get("raw_reference") or "")
            if week is None:
                stats["skipped"] += 1
                continue
            if weekday:
                r = resolve_week_reference(week, weekday, calendar_key=key, kb=kb)
                if r.resolved_date:
                    entry["resolved_date"] = r.resolved_date
                    entry["resolved_by"] = r.resolved_by
                    entry["needs_review"] = r.needs_review     # holiday collision stays flagged
                    stats["resolved_date"] += 1
                    continue
            # week only: a RANGE, never an invented single date — stays tentative
            ws, we = _week_range(cal["term_start"], week)
            entry["resolved_week_start"], entry["resolved_week_end"] = ws, we
            entry["resolved_by"] = "academic_calendar_kb"
            stats["resolved_range"] += 1
    return stats
