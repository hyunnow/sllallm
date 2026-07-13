"""Phase F/G (v3 §9-§11) — 캘린더 컴파일러와 ICS. §11의 핵심 위험 지표를 그대로
테스트로 고정한다: 근거 없는 확정 이벤트 0, 공휴일 수업 0(EXDATE), 면담 혼입 0."""
from syllabus_classifier.compile import compile_record, write_ics
from syllabus_classifier.kb.resolver import KBResolver
from syllabus_classifier.record.schema import empty_record

TT = {"yonsei_seoul": {"periods": {"2": ["10:30", "11:45"], "3": ["12:00", "13:15"]}}}
CAL = {"yonsei__2026_2": {
    "term_start": "2026-09-01", "term_end": "2026-12-18", "weeks": 16,
    "term_start_confidence": "high",
    "holidays": ["2026-09-24", "2026-09-25", "2026-10-05"],   # 10-05는 월요일
}}


def _kb():
    return KBResolver(timetables=TT, calendars=CAL)


def _record(**meeting):
    r = empty_record()
    r["meta"].update({"school": "연세대학교", "academic_year": 2026, "term": "가을"})
    r["course"]["title_ko"] = "자료구조"
    r["meeting"].update(meeting)
    return r


def test_period_class_with_kb_becomes_confirmed_rrule():
    # §11: "월 2,3교시" + 교시표 KB → 실제 시각으로 confirmed
    r = _record(status="present", raw_time="월 2,3교시")
    out = compile_record(r, kb=_kb())
    evs = [e for e in out["confirmed_events"] if "(수업)" in e["summary"]]
    assert len(evs) == 1
    ev = evs[0]
    assert ev["dtstart"] == "2026-09-07T10:30"          # term_start 9/1(화) 이후 첫 월요일
    assert ev["dtend"].endswith("T13:15")
    assert "FREQ=WEEKLY;BYDAY=MO" in ev["rrule"] and "UNTIL=20261218" in ev["rrule"]
    # §11: 추석 연휴가 아닌, 이 요일에 떨어지는 휴강일만 EXDATE
    assert ev["exdate"] == ["2026-10-05"]
    assert out["weekly_timetable"] and out["weekly_timetable"][0]["day"] == "Mon"


def test_week_exam_without_calendar_stays_needs_review():
    # §11: "중간고사 8주차" + 학사일정 없음 → confirmed 금지
    r = _record(status="present", raw_time="월 2교시")
    r["meta"]["school"] = "미지대학교"                    # calendar_key_for -> None
    r["schedule"]["exams"].append({
        "title": "중간고사", "type": "midterm", "date_kind": "relative",
        "raw_reference": "Week 8", "resolved_date": None, "needs_review": True,
    })
    out = compile_record(r, kb=_kb())
    assert all("중간고사" not in e["summary"] for e in out["confirmed_events"])
    assert any("중간고사" in e["summary"] for e in out["needs_review_events"])


def test_office_hours_never_compile_to_class_events():
    # §11: 면담 월 22:00-23:00 → confirmed 수업 이벤트에 없어야 함
    r = _record(status="present", raw_time="월 2교시")
    r["instructors"].append({"name": "홍길동", "office_hours": [{"raw": "월 22:00-23:00"}]})
    out = compile_record(r, kb=_kb())
    for ev in out["confirmed_events"]:
        assert "면담" not in ev["summary"]
        assert "22:00" not in ev.get("dtstart", "")
    assert all("22:00" not in (s.get("start_time") or "") for s in out["weekly_timetable"])


def test_async_course_has_zero_class_events():
    # §11: 비동기 강의 → 수업 이벤트 0개
    out = compile_record(_record(status="async", raw_time=None), kb=_kb())
    assert out["confirmed_events"] == [] and out["weekly_timetable"] == []


def test_no_calendar_still_yields_safe_timetable():
    # 학사일정 미확보(교시표는 있음): RRULE 확정 금지, weekly_timetable은 유효 (v7 §0)
    r = _record(status="present", raw_time="월 2교시")
    out = compile_record(r, kb=KBResolver(timetables=TT, calendars={}))
    assert out["confirmed_events"] == []
    assert out["weekly_timetable"] and out["weekly_timetable"][0]["start_time"] == "10:30"
    assert any("학사일정" in e["review_reason"] for e in out["needs_review_events"])


def test_resolved_exam_date_becomes_all_day_confirmed():
    r = _record(status="not_specified", raw_time=None)
    r["schedule"]["exams"].append({
        "title": "기말고사", "type": "final", "date_kind": "absolute",
        "raw_reference": "2026-12-15", "resolved_date": "2026-12-15", "needs_review": False,
    })
    out = compile_record(r, kb=_kb())
    ev = next(e for e in out["confirmed_events"] if e["summary"] == "기말고사")
    assert ev["all_day"] and ev["dtstart"] == "2026-12-15"


def test_ics_output_shape_and_until_utc():
    r = _record(status="present", raw_time="월 2,3교시")
    out = compile_record(r, kb=_kb())
    ics = write_ics(out)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "BEGIN:VTIMEZONE" in ics and "TZID:Asia/Seoul" in ics
    assert "DTSTART;TZID=Asia/Seoul:20260907T103000" in ics
    # RFC 5545: TZID DTSTART + UNTIL은 UTC (KST 23:59:59 → 14:59:59Z)
    assert "UNTIL=20261218T145959Z" in ics
    assert "EXDATE;TZID=Asia/Seoul:20261005T103000" in ics
    # needs_review는 ICS에 없다
    assert "확인" not in ics


def test_ics_never_contains_unconfirmed_events():
    r = _record(status="present", raw_time="월 9교시")      # KB에 없는 교시 → 미해석
    r["schedule"]["exams"].append({
        "title": "중간고사", "date_kind": "relative", "raw_reference": "Week 8",
        "resolved_date": None, "needs_review": True,
    })
    out = compile_record(r, kb=_kb())
    assert out["confirmed_events"] == []
    assert "VEVENT" not in write_ics(out)


def test_metadata_and_citation_dates_never_confirm():
    # 200-doc 스모크 실측 유출 2건을 가드로 고정: 출력일·참고문헌 인용 날짜
    r = _record(status="not_specified", raw_time=None)
    r["schedule"]["exams"].append({
        "title": "출력일", "date_kind": "absolute", "raw_reference": "2014-09-18",
        "resolved_date": "2014-09-18", "needs_review": False,
    })
    r["schedule"]["assignments"].append({
        "title": "Web. http://www.newyorker.com/magazine/", "date_kind": "absolute",
        "raw_reference": "2009/06/01", "resolved_date": "2009-06-01", "needs_review": False,
    })
    r["schedule"]["assignments"].append({          # 학년도-원거리 연도 (제목은 정상)
        "title": "Report", "date_kind": "absolute", "raw_reference": "2019-10-01",
        "resolved_date": "2019-10-01", "needs_review": False,
    })
    out = compile_record(r, kb=_kb())
    assert out["confirmed_events"] == []
    reasons = " / ".join(e["review_reason"] for e in out["needs_review_events"])
    assert "메타데이터" in reasons and "동떨어진 연도" in reasons


# --- e2e 눈검수(v3 §11)에서 잡은 실버그 3종 회귀 고정 (2026-07-13) ------------------

def test_absurd_year_blocked_by_document_dominant_year():
    # 회사법1: 주차표 2016×N 사이에 오타 '2076-10-20' 한 건 → 문서 지배연도(2016)
    # 기준으로 확정 차단 (academic_year 없어도)
    r = _record(status="not_specified", raw_time=None)
    r["meta"]["academic_year"] = None                # 학년도 없음 → 문서 지배연도 가드 검증
    for d in ("2016-10-13", "2016-12-16", "2076-10-20"):
        r["schedule"]["exams"].append({
            "title": "중간고사", "date_kind": "absolute", "raw_reference": d,
            "resolved_date": d, "needs_review": False})
    out = compile_record(r, kb=_kb())
    dates = {e["dtstart"] for e in out["confirmed_events"]}
    assert "2076-10-20" not in dates and "2016-10-13" in dates
    assert any("2076" in e["review_reason"] for e in out["needs_review_events"])


def test_week_marker_titled_event_is_rejected_not_confirmed():
    # UNIST 2026: "Week 5 (Tuesday 2026-04-02)" 주차행이 시험으로 오추출 →
    # 그 주차 날짜를 시험으로 확정하면 안 된다 (실제 시험은 Week 8 TBA)
    r = _record(status="present", raw_time="월 2교시")
    r["schedule"]["exams"].append({
        "title": "Week 5 (Tuesday", "date_kind": "absolute",
        "raw_reference": "2026-04-02", "resolved_date": "2026-04-02", "needs_review": False})
    out = compile_record(r, kb=_kb(), current_year=2026)
    assert all("2026-04-02" != e.get("dtstart") for e in out["confirmed_events"])
    assert any("오추출" in e["review_reason"] for e in out["needs_review_events"])


def test_current_year_filter_drops_past_term_events():
    # v7 §0: 과거 학기 실라버스(2019)의 시험은 확정 캘린더 대상 아님
    r = _record(status="not_specified", raw_time=None)
    r["meta"]["academic_year"] = None                # 학년도 가드와 독립적으로 현재연도 필터만 검증
    r["schedule"]["exams"].append({
        "title": "기말고사", "date_kind": "absolute", "raw_reference": "2019-12-17",
        "resolved_date": "2019-12-17", "needs_review": False})
    # current_year 미지정: 필터 없음(라이브러리 결정론)
    assert compile_record(r, kb=_kb())["confirmed_events"]
    # current_year=2026: 과거 이벤트 → needs_review
    out = compile_record(r, kb=_kb(), current_year=2026)
    assert out["confirmed_events"] == []
    assert any("과거 학기" in e["review_reason"] for e in out["needs_review_events"])
