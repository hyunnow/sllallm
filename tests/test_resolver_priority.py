"""v7 §2/§6 — resolver priority: in_document > KB > needs_review, never invent."""
from syllabus_classifier.kb.resolver import (
    KBResolver,
    resolve_period_reference,
    resolve_week_reference,
)

CAL = {"yonsei__2026_2": {"term_start": "2026-09-01", "term_end": "2026-12-18",
                          "holidays": [], "makeup_days": {}}}
TT = {"yonsei_seoul": {"periods": {"2": ["10:00", "10:50"], "3": ["11:00", "11:50"]}}}


def kb():
    return KBResolver(timetables=TT, calendars=CAL)


def test_in_document_date_beats_calendar():
    r = resolve_week_reference(3, "Monday", in_document_date="2015-03-16",
                               calendar_key="yonsei__2026_2", kb=kb())
    assert r.resolved_date == "2015-03-16"
    assert r.resolved_by == "in_document"
    assert not r.needs_review


def test_week_without_any_source_stays_raw():
    r = resolve_week_reference(8, "Thursday", kb=kb())
    assert r.resolved_date is None and r.needs_review   # SYL-032: never invent


def test_week_with_current_term_calendar_resolves():
    r = resolve_week_reference(2, "Tuesday", calendar_key="yonsei__2026_2", kb=kb())
    assert r.resolved_by == "academic_calendar_kb"
    assert r.resolved_date == "2026-09-08"


def test_past_term_missing_from_calendar_is_needs_review():
    r = resolve_week_reference(2, "Tuesday", calendar_key="yonsei__2015_1", kb=kb())
    assert r.resolved_date is None and r.needs_review


def test_period_in_document_time_first():
    r = resolve_period_reference([2], in_document_time=("10:00", "10:50"),
                                 timetable_key="yonsei_seoul", kb=kb())
    assert r.resolved_by == "in_document" and r.start_time == "10:00"


def test_period_kb_then_needs_review():
    ok = resolve_period_reference([2, 3], timetable_key="yonsei_seoul", kb=kb())
    assert ok.resolved_by == "period_timetable_kb" and ok.end_time == "11:50"
    miss = resolve_period_reference([2], timetable_key="unknown_school", kb=kb())
    assert miss.start_time is None and miss.needs_review


def test_medium_confidence_term_start_is_not_used():
    # user rule (2026-07): only HIGH-confidence term_start may produce dates.
    cal = {"y__2026_2": {"term_start": "2026-09-01", "term_start_confidence": "medium",
                         "holidays": []}}
    r = KBResolver(timetables={}, calendars=cal).resolve_week("y__2026_2", 2, "Tuesday")
    assert r.resolved_date is None and r.needs_review
    assert "medium" in (r.review_reason or "")


def test_fractional_half_periods_and_unpadded_times():
    # 동국대: fractional period keys ("5.0") + single-digit hours ("9:00")
    tt = {"dongguk": {"periods": {"1.0": ["9:00", "9:30"], "1.5": ["9:30", "10:00"],
                                  "5.0": ["13:00", "13:30"]}}}
    r = resolve_period_reference([1], timetable_key="dongguk", kb=KBResolver(timetables=tt, calendars={}))
    assert (r.start_time, r.end_time) == ("09:00", "09:30")   # zero-padded
    r5 = resolve_period_reference([5], timetable_key="dongguk", kb=KBResolver(timetables=tt, calendars={}))
    assert r5.start_time == "13:00"


def test_school_holidays_count_as_exclusions():
    cal = {"s__2026_2": {"term_start": "2026-09-01", "holidays": [],
                         "school_holidays": ["2026-09-08"]}}
    r = KBResolver(timetables={}, calendars=cal).resolve_week("s__2026_2", 2, "Tuesday")
    assert r.is_holiday and r.needs_review        # 학교 휴강일도 제외 대상
