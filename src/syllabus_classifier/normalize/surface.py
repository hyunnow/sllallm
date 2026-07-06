"""Deterministic normalization layer (C11 / master spec v2 §5).

Run BEFORE candidate extraction so the model never has to learn surface variety
it can be handed for free. Every function is pure and preserves the original in
the caller's `raw_text` field. Where a value cannot be normalized confidently,
we return None rather than guess.
"""
from __future__ import annotations

import re
from typing import Optional

# --- weekday ---------------------------------------------------------------

_WEEKDAYS = {
    "Monday": ["월", "월요일", "월욜", "mon", "monday"],
    "Tuesday": ["화", "화요일", "화욜", "tue", "tues", "tuesday"],
    "Wednesday": ["수", "수요일", "수욜", "wed", "weds", "wednesday"],
    "Thursday": ["목", "목요일", "목욜", "thu", "thur", "thurs", "thursday"],
    "Friday": ["금", "금요일", "금욜", "fri", "friday"],
    "Saturday": ["토", "토요일", "토욜", "sat", "saturday"],
    "Sunday": ["일", "일요일", "일욜", "sun", "sunday"],
}
_WEEKDAY_LOOKUP = {alias: canon for canon, aliases in _WEEKDAYS.items() for alias in aliases}


def normalize_weekday(token: str) -> Optional[str]:
    """`월 / 월요일 / 월욜 / Mon / Monday` -> `Monday`. None if unrecognized."""
    if token is None:
        return None
    return _WEEKDAY_LOOKUP.get(token.strip().lower())


# --- time ------------------------------------------------------------------

_TIME_PATTERNS = [
    # 14:00 / 9:5 (already clock-like)
    re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})$"),
    # 2:00 PM / 2:00pm
    re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>am|pm|AM|PM)$"),
    # 오후 2시 30분 / 오전 9시 / 2시
    re.compile(r"^(?:(?P<ampm>오전|오후)\s*)?(?P<h>\d{1,2})\s*시(?:\s*(?P<m>\d{1,2})\s*분)?$"),
    # 2 PM
    re.compile(r"^(?P<h>\d{1,2})\s*(?P<ap>am|pm|AM|PM)$"),
]


def normalize_time(text: str) -> Optional[str]:
    """Normalize a single clock time to 24h `HH:MM`.

    Handles: `14:00`, `2:00 PM`, `오후 2시`, `오후 2시 30분`, `14시`, `2PM`.
    Returns None if it is not a recognizable single time.
    """
    if text is None:
        return None
    t = text.strip()
    for pat in _TIME_PATTERNS:
        m = pat.match(t)
        if not m:
            continue
        g = m.groupdict()
        hour = int(g["h"])
        minute = int(g.get("m") or 0)
        ampm = g.get("ampm")   # 오전/오후
        ap = (g.get("ap") or "").lower()  # am/pm
        if ampm == "오후" and hour < 12:
            hour += 12
        elif ampm == "오전" and hour == 12:
            hour = 0
        elif ap == "pm" and hour < 12:
            hour += 12
        elif ap == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
        return None
    return None


# --- date ------------------------------------------------------------------

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DATE_YMD = re.compile(r"^(?P<y>\d{4})[.\-/]\s*(?P<mo>\d{1,2})[.\-/]\s*(?P<d>\d{1,2})$")
_DATE_KO = re.compile(r"^(?:(?P<y>\d{4})\s*년\s*)?(?P<mo>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일$")
_DATE_EN = re.compile(
    r"^(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+(?P<mon>[A-Za-z]{3,4})\.?\s*(?P<y>\d{4})?$"
)


def normalize_date(text: str) -> Optional[str]:
    """Normalize a single date.

    `2026.10.27` / `2026-10-27` / `10월 27일` / `2026년 10월 27일` / `27th Oct 2026`.
    Returns ISO `YYYY-MM-DD` when a year is present, otherwise `MM-DD`
    (year unknown -> caller decides via academic-calendar KB). None if unparseable.
    """
    if text is None:
        return None
    t = text.strip()
    for pat in (_DATE_YMD, _DATE_KO):
        m = pat.match(t)
        if m:
            g = m.groupdict()
            return _fmt(g.get("y"), g["mo"], g["d"])
    m = _DATE_EN.match(t)
    if m:
        g = m.groupdict()
        mon = _MONTH_NAMES.get(g["mon"].lower())
        if mon is None:
            return None
        return _fmt(g.get("y"), mon, g["d"])
    return None


def _fmt(year, month, day) -> Optional[str]:
    mo, d = int(month), int(day)
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    if year:
        return f"{int(year):04d}-{mo:02d}-{d:02d}"
    return f"{mo:02d}-{d:02d}"


# --- range separators ------------------------------------------------------

_RANGE_SEP = re.compile(r"\s*(?:~|-|–|—|부터|to|까지)\s*")


def normalize_range_separators(text: str) -> str:
    """Collapse `~ / - / – / 부터 / to / 까지` into a single `~` so range parsing
    downstream sees one separator. Non-destructive to the surrounding tokens."""
    if text is None:
        return text
    # "부터 ... 까지" -> keep a single ~ between the two bounds
    t = re.sub(r"\s*부터\s*", "~", text)
    t = re.sub(r"\s*까지\s*", "", t)
    t = _RANGE_SEP.sub("~", t)
    return t
