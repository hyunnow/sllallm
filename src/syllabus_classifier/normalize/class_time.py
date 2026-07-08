"""Class-time notation converter: raw 강의시간 strings -> the serialization
contract `Mon 11:00-11:50 ; Wed 11:00-11:50` (days Mon~Sun, 24h, ' ; ' slots).

Observed raw shapes handled:
  "TUE THU 10:30-11:45 (104-E101)"      days share one range; room stripped
  "Mon-Thu 9:00am-10:40am"              day RANGE + am/pm times
  "월/수 11:00-11:50" / "월,수 14:00"     Korean days, shared range
  "월 18:00(100) 607-208, 수 18:00(100)"  start(duration-min) pairs, room tails
  "화 5,6교시" / "월7,8"                   period references -> timetable KB

Deterministic and abstaining: if ANY segment fails to convert confidently the
whole conversion returns None and the caller keeps the raw string — a wrong
converted time must never replace a right raw one.
"""
from __future__ import annotations

import re
from typing import Optional

from .surface import normalize_time

_DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_EN_DAY = {"mon": "Mon", "monday": "Mon", "tue": "Tue", "tues": "Tue", "tuesday": "Tue",
           "wed": "Wed", "weds": "Wed", "wednesday": "Wed", "thu": "Thu", "thur": "Thu",
           "thurs": "Thu", "thursday": "Thu", "fri": "Fri", "friday": "Fri",
           "sat": "Sat", "saturday": "Sat", "sun": "Sun", "sunday": "Sun"}
_KO_DAY = {"월": "Mon", "화": "Tue", "수": "Wed", "목": "Thu", "금": "Fri", "토": "Sat", "일": "Sun"}

_ROOM_PAREN = re.compile(r"\((?=[^)]*[A-Za-z가-힣-])[^)]{2,}\)")   # (104-E101), (강의실) — not (100)
_DURATION = re.compile(r"\(\s*(\d{2,3})\s*\)")                      # (100) minutes
_TIME_RANGE = re.compile(
    r"(?P<a>\d{1,2}:\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm))\s*[-~–—]\s*"
    r"(?P<b>\d{1,2}:\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm))", re.IGNORECASE)
_SINGLE_TIME = re.compile(r"\d{1,2}:\d{2}\s*(?:am|pm)?", re.IGNORECASE)
_EN_DAY_TOKEN = re.compile(r"\b(mon|tues?|tuesday|weds?|wednesday|thur?s?|thursday|fri|friday|"
                           r"sat|saturday|sun|sunday|monday)\b\.?", re.IGNORECASE)
_KO_DAY_TOKEN = re.compile(r"(?<![가-힣])([월화수목금토일])(?:요일)?(?![가-힣])")
_DAY_RANGE = re.compile(r"(?P<x>[A-Za-z]{3,9}|[월화수목금토일])\s*[-~]\s*(?P<y>[A-Za-z]{3,9}|[월화수목금토일])")
_PERIODS = re.compile(r"(\d{1,2}(?:\s*[,·]\s*\d{1,2})*)\s*교시|(?<![\d:])(\d{1,2}(?:\s*,\s*\d{1,2})+)(?![\d:])")

_ROOM_TAIL = re.compile(r"\b\d{2,4}-[A-Za-z]?\d{2,4}\b")            # 607-208, 104-E101


def _day_of(tok: str) -> Optional[str]:
    t = tok.strip(". ").lower()
    return _EN_DAY.get(t) or _KO_DAY.get(tok.strip())


def _to_24h(t: str) -> Optional[str]:
    t = t.strip().lower().replace(" ", "")
    if re.fullmatch(r"\d{1,2}(am|pm)", t):
        t = t[:-2] + ":00" + t[-2:]
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(am|pm)?", t)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), m.group(2), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi}" if 0 <= h <= 23 else None


def _add_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = h * 60 + m + minutes
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


def _expand_day_range(x: str, y: str) -> Optional[list[str]]:
    a, b = _day_of(x), _day_of(y)
    if not a or not b:
        return None
    i, j = _DAY_ORDER.index(a), _DAY_ORDER.index(b)
    return _DAY_ORDER[i:j + 1] if i <= j else None


def _segment_days(seg: str) -> list[str]:
    m = _DAY_RANGE.search(seg)
    if m:
        expanded = _expand_day_range(m.group("x"), m.group("y"))
        if expanded:
            return expanded
    days = []
    for tok in _EN_DAY_TOKEN.findall(seg):
        d = _day_of(tok)
        if d and d not in days:
            days.append(d)
    if not days:
        for tok in _KO_DAY_TOKEN.findall(seg):
            d = _KO_DAY.get(tok)
            if d and d not in days:
                days.append(d)
    return days


def to_notation(raw: str, *, timetable_key: Optional[str] = None, kb=None) -> Optional[str]:
    """Convert a raw class-time string to notation, or None when not confident."""
    if not raw or not raw.strip():
        return None
    text = _ROOM_PAREN.sub(" ", raw)
    # strip room tails BUT protect time ranges (they contain ':', rooms don't)
    text = "\n".join(_ROOM_TAIL.sub(" ", ln) if ":" not in ln else ln for ln in text.splitlines())

    slots: list[tuple[str, str, str]] = []
    pending_days: list[str] = []
    # a comma splits segments ONLY when what follows isn't a digit — "5,6교시"
    # period lists and "10:30,11:45"-style enumerations must stay intact.
    segments = re.split(r"[;\n]|\s및\s|,(?=\s*[^\d\s])", text)

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        days = _segment_days(seg) or pending_days
        if not days:
            return None                                  # a segment we can't place

        rng = _TIME_RANGE.search(seg)
        if rng:
            a, b = _to_24h(rng.group("a")), _to_24h(rng.group("b"))
            if not a or not b:
                return None
            if b <= a:                                    # "9:00-10:40am": end carries meridiem
                b2 = _add_minutes(b, 12 * 60)
                if b2 <= a:
                    return None
                b = b2
            for d in days:
                slots.append((d, a, b))
            pending_days = []
            continue

        dur = _DURATION.search(seg)
        single = _SINGLE_TIME.search(seg)
        if dur and single:
            a = _to_24h(single.group(0))
            if not a:
                return None
            for d in days:
                slots.append((d, a, _add_minutes(a, int(dur.group(1)))))
            pending_days = []
            continue

        pm = _PERIODS.search(seg)
        if pm:
            nums = [int(n) for n in re.findall(r"\d{1,2}", pm.group(1) or pm.group(2))]
            if not nums or not timetable_key:
                return None
            from ..kb.resolver import resolve_period_reference

            r = resolve_period_reference(nums, timetable_key=timetable_key, kb=kb)
            if r.needs_review or not r.start_time:
                return None
            for d in days:
                slots.append((d, r.start_time, r.end_time))
            pending_days = []
            continue

        if _segment_days(seg):
            pending_days = days                           # days-only segment ("월,")
            continue
        return None

    if not slots:
        return None
    slots = sorted(set(slots), key=lambda s: (_DAY_ORDER.index(s[0]), s[1]))
    return " ; ".join(f"{d} {a}-{b}" for d, a, b in slots)
