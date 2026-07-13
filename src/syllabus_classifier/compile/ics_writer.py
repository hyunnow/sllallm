"""Phase G (v3 §10) — 표준 ICS 출력. 외부 의존성 없이 RFC 5545를 직접 쓴다.

원칙:
  - confirmed_events만 VEVENT로. needs_review는 ICS에 넣지 않는다 (Phase 0 답 —
    확인 안 된 일정이 캘린더에 꽂히는 것 자체가 사고다). 구조화 JSON은 항상 병행.
  - 시각 이벤트는 TZID=Asia/Seoul (DST 없음 — 정적 VTIMEZONE 한 블록).
  - RFC 5545: DTSTART가 TZID 로컬이면 RRULE의 UNTIL은 UTC — KST 23:59:59를
    UTC 14:59:59Z로 변환해 쓴다.
  - 종일 이벤트(시험/과제 resolved_date)는 VALUE=DATE, DTEND는 다음 날 (RFC 관행).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

_VTIMEZONE = (
    "BEGIN:VTIMEZONE\r\n"
    "TZID:Asia/Seoul\r\n"
    "BEGIN:STANDARD\r\n"
    "DTSTART:19700101T000000\r\n"
    "TZOFFSETFROM:+0900\r\n"
    "TZOFFSETTO:+0900\r\n"
    "TZNAME:KST\r\n"
    "END:STANDARD\r\n"
    "END:VTIMEZONE\r\n"
)


def _escape(s: str) -> str:
    return (str(s).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """RFC 5545 75-octet line folding (continuation lines start with a space)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts = []
    cur = b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b
        else:
            cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def _until_utc(until_local: str) -> str:
    """'YYYYMMDDT235959' (KST) -> 'YYYYMMDDTHHMMSSZ' (UTC)."""
    dt = datetime.strptime(until_local, "%Y%m%dT%H%M%S") - timedelta(hours=9)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def write_ics(compiled: dict, *, dtstamp: str = "20260101T000000Z",
              uid_domain: str = "sllallm") -> str:
    """compile_record 산출 -> ICS 텍스트. 결정론(주어진 dtstamp 고정)이라
    회귀 테스트로 바이트 비교가 가능하다."""
    course = compiled.get("course", {})
    slug = "".join(c if c.isalnum() else "-" for c in str(course.get("title") or "course"))[:40]
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//sllallm//syllabus-calendar//KO",
        "CALSCALE:GREGORIAN",
    ]
    lines.append(_VTIMEZONE.rstrip("\r\n"))

    for i, ev in enumerate(compiled.get("confirmed_events", []), start=1):
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{slug}-{i}@{uid_domain}")
        lines.append(f"DTSTAMP:{dtstamp}")
        lines.append(f"SUMMARY:{_escape(ev.get('summary') or '')}")
        if ev.get("all_day"):
            d = date.fromisoformat(ev["dtstart"])
            lines.append(f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}")
        else:
            st = ev["dtstart"].replace("-", "").replace(":", "") + "00"
            en = ev["dtend"].replace("-", "").replace(":", "") + "00"
            lines.append(f"DTSTART;TZID=Asia/Seoul:{st}")
            lines.append(f"DTEND;TZID=Asia/Seoul:{en}")
            rr = ev.get("rrule")
            if rr:
                if "UNTIL=" in rr:                      # UNTIL은 UTC로 (RFC 5545)
                    head, _, until = rr.partition("UNTIL=")
                    rr = head + "UNTIL=" + _until_utc(until)
                lines.append(f"RRULE:{rr}")
            start_hms = st[9:]
            for x in ev.get("exdate") or []:
                lines.append(f"EXDATE;TZID=Asia/Seoul:{x.replace('-', '')}T{start_hms}")
        if ev.get("resolved_by"):
            lines.append(f"X-RESOLVED-BY:{_escape(ev['resolved_by'])}")
        lines.append("STATUS:CONFIRMED")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in "\r\n".join(lines).split("\r\n")) + "\r\n"
