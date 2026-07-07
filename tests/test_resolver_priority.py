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
