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
# ONLY explicit 교시-suffixed lists are periods. Bare digit lists ("금 1,2,3",
# "화 19,20,21") are ambiguous — even the human reviewer couldn't tell periods
# from o'clock hours (B2-020/022 memos) — so we abstain on them.
_PERIODS = re.compile(r"(\d{1,2}(?:\s*[,·]\s*\d{1,2})*)\s*교시")

_ROOM_TAIL = re.compile(r"\b\d{2,4}-[A-Za-z]?\d{2,4}\b")            # 607-208, 104-E101
# 콜론 없는 HHMM 범위: "1400-1500" -> 14:00-15:00 (KOCW 건국 등). 2자리는 교시라 제외.
_HHMM = re.compile(r"(?<![\d:])(\d{3,4})\s*[-~–—]\s*(\d{3,4})(?![\d:])")
# 'N시'/'N시 M분' o'clock 표기 ("15시-18시", "15시30분"). '교시'의 시는 (?<!교)로 제외.
_SIHOUR = re.compile(r"(?<!교)(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?")


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


def _hhmm_to_24h(s: str) -> Optional[str]:
    """'1400'->'14:00', '900'->'09:00'. 유효 시각 아니면 None (abstain)."""
    h, mi = int(s[:-2]), int(s[-2:])
    return f"{h:02d}:{mi:02d}" if 0 <= h <= 23 and 0 <= mi <= 59 else None


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
    # "15-16시"처럼 끝에만 시가 붙는 범위 → "15시-16시" (양쪽에 시 부여) 후 정규화
    text = re.sub(r"(?<!교)(\d{1,2})\s*[-~]\s*(\d{1,2})\s*시", r"\1시-\2시", text)
    # "15시-18시" / "15시30분" → "15:00" / "15:30" 로 정규화 ('교시'는 (?<!교)로 보호)
    text = _SIHOUR.sub(lambda m: f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}", text)
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

        # 콜론 없는 HHMM 범위: "화1400-1500" -> 14:00-15:00 (3~4자리라 교시 2자리와 구분).
        # 콜론이 있으면 HH:MM 계열(_TIME_RANGE/_DURATION)이 처리하므로 건너뛴다 — 방번호
        # "607-208" 같은 걸 시각으로 오인하지 않게. 유효한 오름차순 범위일 때만 소비.
        hh = _HHMM.search(seg) if ":" not in seg else None
        if hh:
            a, b = _hhmm_to_24h(hh.group(1)), _hhmm_to_24h(hh.group(2))
            if a and b and a < b:
                for d in days:
                    slots.append((d, a, b))
                pending_days = []
                continue
            # 유효 시각이 아니면(방번호 등) HHMM 로 소비하지 않고 다른 브랜치에 맡긴다

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
            nums = [int(n) for n in re.findall(r"\d{1,2}", pm.group(1))]
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

        # bare 교시 리스트 (교시 접미사 없음) — 학교 교시표 KB 가 있을 때만 신뢰한다.
        # KB 커버 학교에선 "요일+작은정수 리스트"가 그 학교의 교시 관행이다 (연세 "수5,6").
        # KB 없으면 종전대로 abstain(아래 return None). KB 가 있어도 범위 밖이면 abstain.
        if timetable_key:
            nums = [int(n) for n in re.findall(r"(?<!\d)\d{1,2}(?!\d)", seg)]
            nums = [n for n in nums if 1 <= n <= 15]
            if nums:
                from ..kb.resolver import resolve_period_reference

                r = resolve_period_reference(nums, timetable_key=timetable_key, kb=kb)
                if not r.needs_review and r.start_time:
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
