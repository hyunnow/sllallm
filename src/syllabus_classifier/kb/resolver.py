"""Knowledge-base resolvers (mechanism KB, master spec v2 §2).

These turn external-knowledge references into concrete values:
  - period number -> clock time      (period_timetables.yaml)
  - week N / N일차 / N월 -> real date  (academic_calendars.yaml)

ABSOLUTE RULE (v2 §2-2, §7): if the KB lacks the needed entry, we return
needs_review=True and resolved_* = None. We never invent a time or date.

The model is never trained to do these conversions — that is the whole point of
having KBs. Model performance and resolver performance are measured separately
(v2 §8).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from ..common.config import load_config

_WEEKDAY_INDEX = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}


@dataclass
class ResolvedTime:
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    resolved_by: Optional[str] = None       # period_timetable_kb | None
    needs_review: bool = False
    review_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "resolved_by": self.resolved_by,
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
        }


@dataclass
class ResolvedDate:
    resolved_date: Optional[str] = None      # ISO YYYY-MM-DD
    resolved_by: Optional[str] = None        # academic_calendar_kb | None
    is_holiday: bool = False
    makeup_date: Optional[str] = None
    needs_review: bool = False
    review_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "resolved_date": self.resolved_date,
            "resolved_by": self.resolved_by,
            "is_holiday": self.is_holiday,
            "makeup_date": self.makeup_date,
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
        }


class KBResolver:
    """Loads both KBs once and exposes the resolvers. Pass explicit dicts in
    tests to avoid touching config files."""

    def __init__(self, timetables: Optional[dict] = None, calendars: Optional[dict] = None):
        self._timetables = timetables if timetables is not None else load_config(
            "period_timetables.yaml"
        ).get("timetables", {})
        self._calendars = calendars if calendars is not None else load_config(
            "academic_calendars.yaml"
        ).get("calendars", {})

    # --- period -> clock time ---------------------------------------------
    def resolve_period(self, school: str, term_type: str, period_numbers: list[int]) -> ResolvedTime:
        key = f"{school}__{term_type}"
        table = self._timetables.get(key)
        if not table:
            return ResolvedTime(
                needs_review=True,
                review_reason=f"period timetable not found for '{key}'",
            )
        periods = table.get("periods", {})
        starts, ends = [], []
        for n in period_numbers:
            slot = periods.get(str(n))
            if not slot:
                return ResolvedTime(
                    needs_review=True,
                    review_reason=f"period {n} not in timetable '{key}'",
                )
            starts.append(slot[0])
            ends.append(slot[1])
        return ResolvedTime(
            start_time=min(starts),
            end_time=max(ends),
            resolved_by="period_timetable_kb",
        )

    # --- week N (+weekday) -> date ----------------------------------------
    def resolve_week(self, calendar_key: str, week: int, weekday: str) -> ResolvedDate:
        cal = self._calendars.get(calendar_key)
        if not cal or not cal.get("term_start"):
            return ResolvedDate(
                needs_review=True,
                review_reason=f"academic calendar / term_start missing for '{calendar_key}'",
            )
        wd = _WEEKDAY_INDEX.get(weekday)
        if wd is None:
            return ResolvedDate(needs_review=True, review_reason=f"unknown weekday '{weekday}'")

        term_start = date.fromisoformat(cal["term_start"])
        week1_monday = term_start - timedelta(days=term_start.weekday())
        target = week1_monday + timedelta(weeks=week - 1, days=wd)

        holidays = set(cal.get("holidays", []))
        iso = target.isoformat()
        if iso in holidays:
            makeup = (cal.get("makeup_days") or {}).get(iso)
            return ResolvedDate(
                resolved_date=iso,
                resolved_by="academic_calendar_kb",
                is_holiday=True,
                makeup_date=makeup,
                needs_review=makeup is None,
                review_reason=None if makeup else "class date falls on a holiday with no makeup day",
            )
        return ResolvedDate(resolved_date=iso, resolved_by="academic_calendar_kb")

    # --- N-th class day -> date -------------------------------------------
    def resolve_nth_class_day(self, calendar_key: str, n: int, class_weekdays: list[str]) -> ResolvedDate:
        """N번째 실제 수업일. class_weekdays = the course's meeting weekdays."""
        cal = self._calendars.get(calendar_key)
        if not cal or not cal.get("term_start"):
            return ResolvedDate(
                needs_review=True,
                review_reason=f"academic calendar / term_start missing for '{calendar_key}'",
            )
        wds = sorted({_WEEKDAY_INDEX[w] for w in class_weekdays if w in _WEEKDAY_INDEX})
        if not wds:
            return ResolvedDate(needs_review=True, review_reason="no valid class weekdays given")
        term_start = date.fromisoformat(cal["term_start"])
        term_end = date.fromisoformat(cal["term_end"]) if cal.get("term_end") else term_start + timedelta(weeks=20)
        holidays = set(cal.get("holidays", []))
        count = 0
        cur = term_start
        while cur <= term_end:
            if cur.weekday() in wds and cur.isoformat() not in holidays:
                count += 1
                if count == n:
                    return ResolvedDate(resolved_date=cur.isoformat(), resolved_by="academic_calendar_kb")
            cur += timedelta(days=1)
        return ResolvedDate(needs_review=True, review_reason=f"class day #{n} is beyond term end")


def resolve_month(month: int, year: Optional[int] = None) -> dict:
    """`3월 / 4월` -> a tentative month range. Never a single fixed date (v2 §2-2)."""
    return {
        "date_kind": "relative",
        "raw_reference": {"type": "month", "value": month},
        "resolved_date": None,
        "resolved_by": None,
        "tentative_range": {"year": year, "month": month},
        "needs_review": True,
        "review_reason": "month-only reference; resolve to a specific date requires more context",
    }


# module-level convenience wrappers (use the seed configs)
def resolve_period(school: str, term_type: str, period_numbers: list[int]) -> ResolvedTime:
    return KBResolver().resolve_period(school, term_type, period_numbers)


def resolve_week(calendar_key: str, week: int, weekday: str) -> ResolvedDate:
    return KBResolver().resolve_week(calendar_key, week, weekday)
