"""Phase F (v3 §9) — 캘린더 컴파일러: 해석된 record를 캘린더 이벤트로 조립한다.
"틀린 일정을 안 넣는" 마지막 관문.

버킷 3개 (v3의 confirmed/needs_review에 weekly_timetable을 추가):
  confirmed_events     날짜·시각 근거가 완결된 것만 — 반복 수업(RRULE/EXDATE/UNTIL),
                       resolved_date 있는 시험/과제(종일 이벤트).
  weekly_timetable     요일+시각 슬롯 (날짜 무관 시간표). 학사일정이 없어도 수업
                       시간표 자체는 유효하므로 항상 안전하게 낸다 (v7 §0 제품 목적).
  needs_review_events  근거가 모자란 전부 — 확정 이벤트로 절대 승격하지 않는다.

컴파일 규칙 (v3 §9):
  - 수업: 학사일정 KB가 usable할 때만 반복 이벤트. UNTIL=term_end,
    공휴일·학교휴강일은 EXDATE. C4 다분반 의심이면 통째로 needs_review.
  - 면담시간: 기본 미컴파일 (compile_office_hours=True로만 별도 카테고리 생성).
  - 시험/과제: resolved_date + needs_review=False만 확정(종일). 주-범위만 있으면
    needs_review. recurring 마감은 아직 확정 금지(needs_review).
  - 무기한과제·기한 없는 항목: 캘린더 비대상 (record JSON에 남는다).
  - 공통: KB·문서 근거 없는 날짜/시각으로 확정 이벤트를 만들지 않는다.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from ..kb.record_resolver import calendar_key_for, resolve_record_dates
from ..kb.resolver import KBResolver, calendar_usable
from ..normalize.class_time import to_notation

_SLOT = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{2}:\d{2})-(\d{2}:\d{2})$")
# 컴파일 최후 가드 (§9): 문서 메타데이터·인용 출처의 날짜는 일정이 아니다 —
# 200-doc 스모크에서 '출력일 2014-09-18'(인쇄일)과 'Web. http://…' 2009(참고문헌
# 인용)가 confirmed로 새는 것을 잡았다. 제목 단서 + 학년도 원거리 연도로 차단.
_NON_EVENT_TITLE = re.compile(
    r"출력일|인쇄일|작성일|발행일|갱신일|조회일|^Web\b|https?://|\bRetrieved\b|\bAccessed\b|"
    r"\bdoi\b|\bpp?\.\s*\d", re.IGNORECASE)
# 라벨·주차 참조·bare 숫자는 이벤트 제목이 아니다 — 과목명 폴백으로 교체 (날짜는
# 유효하므로 이벤트는 유지; 전 코퍼스 스모크의 '8'/'Week 5 (Tuesday'/'제출일')
_LABELISH_TITLE = re.compile(
    r"^\s*(?:\d{1,3}|week\s*\d+.*|제?\s*\d+\s*주차?.*|제출일|출제일|시험일|마감일?|날짜|일시)\s*$",
    re.IGNORECASE)
# 제목이 주차/요일 마커인 이벤트 = 주차 일정 행이 시험/과제로 오추출된 것. 그 행의
# 날짜(주차 topic 날짜)를 시험 날짜로 확정하면 안 된다 (UNIST 2026: "Week 5
# (Tuesday 2026-04-02)"가 시험으로 새어 실제 TBA 시험을 4/2에 가짜 확정). 거부.
_WEEK_MARKER_TITLE = re.compile(
    r"^\s*(?:week\s*\d+|제?\s*\d+\s*주차|\d+\s*(?:st|nd|rd|th)?\s*week)\b", re.IGNORECASE)
_BYDAY = {"Mon": "MO", "Tue": "TU", "Wed": "WE", "Thu": "TH", "Fri": "FR",
          "Sat": "SA", "Sun": "SU"}
_WD_INDEX = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def _parse_slots(notation: str) -> list[tuple[str, str, str]]:
    """'Mon 10:00-10:50 ; Wed 10:00-10:50' -> [(day, start, end), ...].
    한 세그먼트라도 계약 형태가 아니면 [] — 반쯤 파싱한 시간표를 내지 않는다."""
    slots = []
    for seg in (notation or "").split(";"):
        seg = seg.strip()
        if not seg:
            continue
        m = _SLOT.match(seg)
        if not m:
            return []
        slots.append((m.group(1), m.group(2), m.group(3)))
    return slots


def _first_on_or_after(start: date, weekday: str) -> date:
    return start + timedelta(days=(_WD_INDEX[weekday] - start.weekday()) % 7)


def _class_exdates(cal: dict, weekday: str, first: date, until: date) -> list[str]:
    holidays = set(cal.get("holidays", [])) | set(cal.get("school_holidays", []))
    out = []
    cur = first
    while cur <= until:
        iso = cur.isoformat()
        if iso in holidays:
            out.append(iso)
        cur += timedelta(days=7)
    return out


def _review(summary: str, reason: str, *, kind: str = "class", **extra) -> dict:
    # kind (class|exam|assignment|office_hours) lets host apps route events
    # without re-deriving type from the summary. Defaults to class (the 수업 block).
    return {"summary": summary, "kind": kind, "status": "needs_review",
            "review_reason": reason, **extra}


def compile_record(record: dict, kb: Optional[KBResolver] = None,
                   compile_office_hours: bool = False,
                   current_year: Optional[int] = None) -> dict:
    """record (record_builder 산출) -> 3-버킷 캘린더. resolve_record_dates를
    내부에서 호출하므로 미해석 record를 그대로 넣어도 된다.

    current_year (제품 배포 시 오늘 연도 전달): 지정하면 그 연도보다 과거인 확정
    이벤트를 needs_review로 내린다 — v7 §0 제품은 현재·다가올 학기용이지 과거 학기
    아카이브가 아니다. 코퍼스의 kocw 옛 실라버스(2013~2024)가 과거 시험을 확정
    이벤트로 만드는 것을 막는다. 기본 None = 필터 없음(라이브러리 결정론)."""
    kb = kb or KBResolver()
    resolve_record_dates(record, kb=kb)

    meta = record.get("meta", {})
    meeting = record.get("meeting", {})
    course = record.get("course", {})
    title = re.sub(r"\s+", " ", course.get("title_ko") or course.get("title_en") or "수업").strip()

    confirmed: list[dict] = []
    timetable: list[dict] = []
    review: list[dict] = []

    cal_key = calendar_key_for(meta.get("school"), meta.get("academic_year"), meta.get("term"))
    cal = kb._calendars.get(cal_key) if cal_key else None
    cal_ok = calendar_usable(cal)

    # --- 수업 (반복) ------------------------------------------------------
    status = meeting.get("status")
    multi_section = any(
        f.get("field") == "meeting" and "C4" in (f.get("reason") or "")
        for f in record.get("needs_review", []))
    raw_time = meeting.get("raw_time")

    if status == "async":
        pass                                        # 비동기: 수업 이벤트 0개 (v3 §11)
    elif status == "tba":
        review.append(_review(f"{title} (수업)", "수업시간 TBA — 문서가 추후 공지"))
    elif multi_section:
        review.append(_review(f"{title} (수업)", "C4 다분반 혼합 의심 — 분반 확정 필요",
                              raw_time=raw_time))
    elif raw_time:
        from ..kb.resolver import timetable_key_for

        notation = to_notation(raw_time, timetable_key=timetable_key_for(meta.get("school")), kb=kb)
        slots = _parse_slots(notation) if notation else []
        if not slots:
            review.append(_review(f"{title} (수업)",
                                  "수업시간 미해석 (교시표 miss 또는 비정형 표기)",
                                  raw_time=raw_time))
        else:
            for day, start, end in slots:
                timetable.append({"summary": f"{title} (수업)", "kind": "class",
                                  "day": day, "start_time": start, "end_time": end})
            if cal_ok:
                term_start = date.fromisoformat(cal["term_start"])
                term_end = date.fromisoformat(cal["term_end"]) if cal.get("term_end") \
                    else term_start + timedelta(weeks=int(cal.get("weeks", 16)), days=-1)
                for day, start, end in slots:
                    first = _first_on_or_after(term_start, day)
                    confirmed.append({
                        "summary": f"{title} (수업)",
                        "kind": "class",
                        "dtstart": f"{first.isoformat()}T{start}",
                        "dtend": f"{first.isoformat()}T{end}",
                        "rrule": f"FREQ=WEEKLY;BYDAY={_BYDAY[day]};"
                                 f"UNTIL={term_end.strftime('%Y%m%d')}T235959",
                        "exdate": _class_exdates(cal, day, first, term_end),
                        "status": "confirmed",
                        "resolved_by": "period_timetable_kb/in_document + academic_calendar_kb",
                    })
            else:
                review.append(_review(
                    f"{title} (수업)",
                    f"학사일정 미확보({cal_key or '키 없음'}) — 반복 경계(UNTIL)·휴강 확정 불가, "
                    "weekly_timetable 참조", slots=[f"{d} {s}-{e}" for d, s, e in slots]))
    elif status == "not_specified":
        # 근거 없음을 async 로 단정하지 않고 표면화 — "우리가 못 찾았다"를 솔직히 needs_review.
        review.append(_review(f"{title} (수업)", "수업시간 미상 — 문서에서 추출 근거 없음"))

    # --- 면담시간 (기본 미컴파일, v3 §9) -----------------------------------
    if compile_office_hours:
        for inst in record.get("instructors", []):
            for oh in inst.get("office_hours") or []:
                review.append(_review(f"{title} (면담)", "면담시간은 확정 캘린더 비대상 (옵션 카테고리)",
                                      kind="office_hours",
                                      raw=oh.get("raw") if isinstance(oh, dict) else str(oh)))

    # 연도 sanity 기준: 학년도 > 문서 내 지배 연도. 학년도가 없어도(bare 날짜뿐인
    # 문서) 문서가 스스로 쓰는 연도에서 크게 벗어난 확정일은 오타/오파싱이다
    # (회사법1: 주차표 2016×N에 '2076-10-20' 한 건 — 원본 1→7 오타).
    from collections import Counter as _Counter

    _yrs: _Counter = _Counter()
    for _k in ("exams", "assignments"):
        for _e in record.get("schedule", {}).get(_k, []):
            _rd = _e.get("resolved_date")
            if _rd and _e.get("date_kind") == "absolute":
                _yrs[str(_rd)[:4]] += 1
    doc_year = meta.get("academic_year") or (int(_yrs.most_common(1)[0][0]) if _yrs else None)

    # --- 시험 / 과제 (단일) -------------------------------------------------
    for bucket, label in (("exams", "시험"), ("assignments", "과제")):
        ev_kind = "exam" if bucket == "exams" else "assignment"
        for e in record.get("schedule", {}).get(bucket, []):
            orig_title = e.get("title") or ""
            # 주차/요일 마커 제목 = 주차 일정 행 오추출 → 실제 이벤트 아님, 날짜 확정 금지
            if _WEEK_MARKER_TITLE.match(orig_title):
                review.append(_review(f"{title} ({label})",
                                      "주차 일정 행이 시험/과제로 오추출 (실제 이벤트 아님)",
                                      kind=ev_kind, raw_reference=e.get("raw_reference")))
                continue
            summary = orig_title or f"{title} ({label})"
            if _LABELISH_TITLE.match(summary):
                summary = f"{title} ({label})"
            if e.get("date_kind") == "recurring":
                review.append(_review(summary, "반복 마감 — 확정 컴파일 미지원(확인 필요)",
                                      kind=ev_kind, raw_reference=e.get("raw_reference")))
                continue
            rd = e.get("resolved_date")
            if _NON_EVENT_TITLE.search(summary):
                review.append(_review(summary, "문서 메타데이터/인용 날짜 의심 — 일정 아님",
                                      kind=ev_kind, raw_reference=e.get("raw_reference")))
                continue
            if rd and doc_year and abs(int(str(rd)[:4]) - int(doc_year)) > 1:
                ref = "학년도" if meta.get("academic_year") else "문서 지배연도"
                review.append(_review(summary, f"{ref}({doc_year})와 동떨어진 연도({str(rd)[:4]}) — "
                                               "오타/인용/과거 날짜 의심",
                                      kind=ev_kind, raw_reference=e.get("raw_reference")))
                continue
            if rd and current_year and int(str(rd)[:4]) < current_year:
                review.append(_review(summary, f"과거 학기({str(rd)[:4]}) — 현재/다가올 학기 아님",
                                      kind=ev_kind, raw_reference=e.get("raw_reference")))
                continue
            if rd and not e.get("needs_review"):
                confirmed.append({
                    "summary": summary, "kind": ev_kind, "dtstart": rd, "all_day": True,
                    "status": "confirmed", "resolved_by": e.get("resolved_by"),
                })
            elif e.get("resolved_week_start"):
                review.append(_review(
                    summary,
                    f"주-범위만 확정({e['resolved_week_start']}~{e.get('resolved_week_end')}) — "
                    "단일 날짜 근거 없음", kind=ev_kind, raw_reference=e.get("raw_reference")))
            else:
                review.append(_review(
                    summary,
                    e.get("review_reason") or
                    ("휴강일 충돌" if e.get("needs_review") and rd else "날짜 근거 없음(raw 유지)"),
                    kind=ev_kind, raw_reference=e.get("raw_reference"), date_kind=e.get("date_kind")))

    return {
        "course": {"title": title, "school": meta.get("school"),
                   "academic_year": meta.get("academic_year"), "term": meta.get("term"),
                   "calendar_key": cal_key if cal_ok else None},
        "confirmed_events": confirmed,
        "weekly_timetable": timetable,
        "needs_review_events": review,
        "stats": {"confirmed": len(confirmed), "timetable_slots": len(timetable),
                  "needs_review": len(review)},
    }
