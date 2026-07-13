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


def _validate_timetables(tt: dict) -> None:
    """v3 §5-3 로드 시 스키마 검증: 교시 슬롯은 [start,end] 2-튜플이고 start<end."""
    for key, table in (tt or {}).items():
        for p, slot in ((table or {}).get("periods") or {}).items():
            if not (isinstance(slot, (list, tuple)) and len(slot) == 2):
                raise ValueError(f"period_timetables '{key}' 교시 {p}: [시작,끝] 형식이 아님: {slot!r}")
            s, e = _norm_hhmm(slot[0]), _norm_hhmm(slot[1])
            if s >= e:
                raise ValueError(f"period_timetables '{key}' 교시 {p}: 시작({s}) >= 끝({e})")


def _validate_calendars(cals: dict) -> None:
    """v3 §5-3: 날짜 필드는 ISO여야 한다 (문자열/date 객체 모두 str() 후 검사)."""
    from datetime import date as _d

    for key, cal in (cals or {}).items():
        for f in ("term_start", "term_end"):
            v = (cal or {}).get(f)
            if v:
                try:
                    _d.fromisoformat(str(v))
                except ValueError as exc:
                    raise ValueError(f"academic_calendars '{key}' {f}={v!r}: ISO 날짜 아님") from exc
        for group in ("holidays", "school_holidays"):
            for h in (cal or {}).get(group) or []:
                try:
                    _d.fromisoformat(str(h))
                except ValueError as exc:
                    raise ValueError(f"academic_calendars '{key}' {group} {h!r}: ISO 날짜 아님") from exc


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
        # v3 §5-3: 잘못된 KB는 조용히 오답을 만들지 말고 로드에서 크게 실패한다
        _validate_timetables(self._timetables)
        _validate_calendars(self._calendars)

    # --- period -> clock time ---------------------------------------------
    def resolve_period(self, school: str, term_type: str, period_numbers: list[int]) -> ResolvedTime:
        key = f"{school}__{term_type}"
        table = self._timetables.get(key)
        if not table:
            return ResolvedTime(
                needs_review=True,
                review_reason=f"period timetable not found for '{key}'",
            )
        return _resolve_periods_from_table(table, period_numbers, key)

    # --- week N (+weekday) -> date ----------------------------------------
    def resolve_week(self, calendar_key: str, week: int, weekday: str) -> ResolvedDate:
        cal = self._calendars.get(calendar_key)
        if not cal or not cal.get("term_start"):
            return ResolvedDate(
                needs_review=True,
                review_reason=f"academic calendar / term_start missing for '{calendar_key}'",
            )
        # user safety rule (2026-07): only a HIGH-confidence term_start may
        # produce definitive dates. Entries marked medium/low flow to
        # needs_review even though they carry a value.
        conf = str(cal.get("term_start_confidence", "high")).lower()
        if conf not in ("high", "높음"):
            return ResolvedDate(
                needs_review=True,
                review_reason=f"term_start for '{calendar_key}' is {conf}-confidence; "
                              "definitive conversion requires high",
            )
        wd = _WEEKDAY_INDEX.get(weekday)
        if wd is None:
            return ResolvedDate(needs_review=True, review_reason=f"unknown weekday '{weekday}'")

        term_start = date.fromisoformat(cal["term_start"])
        week1_monday = term_start - timedelta(days=term_start.weekday())
        target = week1_monday + timedelta(weeks=week - 1, days=wd)

        # 휴강일은 국가공휴일(holidays)과 학교휴강일(school_holidays)의 합집합
        holidays = set(cal.get("holidays", [])) | set(cal.get("school_holidays", []))
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


# --- v7 §2 priority resolvers: in_document > KB > needs_review ---------------


def resolve_week_reference(
    week: int,
    weekday: Optional[str] = None,
    *,
    in_document_date: Optional[str] = None,
    calendar_key: Optional[str] = None,
    kb: Optional["KBResolver"] = None,
) -> ResolvedDate:
    """Resolve 'Week N' with the v7 §2 priority order.

    1. a date the DOCUMENT itself provides (weekly-plan date column) wins —
       past documents resolve for free, no calendar needed;
    2. else the academic-calendar KB (current/upcoming terms only, by policy);
    3. else stay raw: resolved_date=null + needs_review. Never invent a date.
    """
    if in_document_date:
        return ResolvedDate(resolved_date=in_document_date, resolved_by="in_document")
    if calendar_key:
        kb = kb or KBResolver()
        if calendar_key in kb._calendars and weekday:
            return kb.resolve_week(calendar_key, week, weekday)
    return ResolvedDate(
        needs_review=True,
        review_reason=f"week {week}: no in-document date and no calendar entry"
                      + (f" for '{calendar_key}'" if calendar_key else ""),
    )


def resolve_period_reference(
    period_numbers: list[int],
    *,
    in_document_time: Optional[tuple[str, str]] = None,
    timetable_key: Optional[str] = None,
    kb: Optional["KBResolver"] = None,
) -> ResolvedTime:
    """Resolve '(N)교시' with the v7 §2 priority order (in-document time first,
    e.g. "2교시(10:00-10:50)"); timetable_key is the (school,campus) KB key."""
    if in_document_time:
        return ResolvedTime(start_time=in_document_time[0], end_time=in_document_time[1],
                            resolved_by="in_document")
    if timetable_key:
        kb = kb or KBResolver()
        table = kb._timetables.get(timetable_key)
        if table:
            school, _, term = timetable_key.partition("__")
            return kb.resolve_period(school, term or "regular", period_numbers) \
                if term else _resolve_periods_from_table(table, period_numbers, timetable_key)
    return ResolvedTime(
        needs_review=True,
        review_reason=f"periods {period_numbers}: no in-document time and no timetable entry"
                      + (f" for '{timetable_key}'" if timetable_key else ""),
    )


def _norm_hhmm(t: str) -> str:
    """'9:00' -> '09:00' — zero-pad so string min/max compares correctly."""
    h, _, m = str(t).partition(":")
    return f"{int(h):02d}:{int(m or 0):02d}"


def _resolve_periods_from_table(table: dict, period_numbers: list[int], key: str) -> ResolvedTime:
    periods = table.get("periods", {})
    starts, ends = [], []
    for n in period_numbers:
        # some schools use fractional half-periods ("1.0"/"1.5", 동국대);
        # an integer reference "1교시" must match the "1.0" key there.
        slot = periods.get(str(n)) or periods.get(f"{float(n):.1f}")
        if not slot:
            return ResolvedTime(needs_review=True, review_reason=f"period {n} not in timetable '{key}'")
        starts.append(_norm_hhmm(slot[0]))
        ends.append(_norm_hhmm(slot[1]))
    return ResolvedTime(start_time=min(starts), end_time=max(ends), resolved_by="period_timetable_kb")


# canonical school name -> academic-calendar key for the CURRENT/UPCOMING term
# (keys follow whatever the humans used in academic_calendars.yaml)
CALENDAR_KEY_BY_SCHOOL_2026_FALL = {
    "한양대학교": "hanyang__2026_2",
    "숭실대학교": "Soon__2026_fall",
    "New York University": "NYU__2026_fall",
    "연세대학교": "yonsei__2026_2",
    "고려대학교": "korea__2026_2",
    "서울대학교": "snu__2026_2",
    "성균관대학교": "skku__2026_2",
    "서강대학교": "sogang__2026_2",
    "이화여자대학교": "ewha__2026_2",
    "KAIST": "kaist__2026_fall",
    "홍익대학교": "hongik__2026_2",
    "건국대학교": "konkuk__2026_2",
    "동국대학교": "dongguk__2026_2",
    "UNIST": "unist__2026_fall",
    "중앙대학교": "cau__2026_2",
    "경희대학교": "khu__2026_2",
    "한국외국어대학교": "hufs__2026_2",
    "서울시립대학교": "uos__2026_2",
    "포항공과대학교": "postech__2026_2",
    "GIST": "gist__2026_fall",
    "DGIST": "dgist__2026_fall",
}


def calendar_usable(cal: "dict | None") -> bool:
    """A calendar entry may produce definitive dates only with a HIGH-confidence
    term_start (user safety rule)."""
    if not cal or not cal.get("term_start"):
        return False
    return str(cal.get("term_start_confidence", "high")).lower() in ("high", "높음")


# canonical school name (school_dictionary) -> period-timetable key
TIMETABLE_KEY_BY_SCHOOL = {
    "연세대학교": "yonsei_seoul",
    "건국대학교": "konkuk",
    "이화여자대학교": "ewha",
    "홍익대학교": "hongik",
    "동국대학교": "dongguk",
}


def timetable_key_for(school: "str | None") -> Optional[str]:
    return TIMETABLE_KEY_BY_SCHOOL.get(school or "")


# module-level convenience wrappers (use the seed configs)
def resolve_period(school: str, term_type: str, period_numbers: list[int]) -> ResolvedTime:
    return KBResolver().resolve_period(school, term_type, period_numbers)


def resolve_week(calendar_key: str, week: int, weekday: str) -> ResolvedDate:
    return KBResolver().resolve_week(calendar_key, week, weekday)
