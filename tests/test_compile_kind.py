"""Compiler stamps a `kind` (class|exam|assignment|office_hours) on every
confirmed / weekly_timetable / needs_review event, so host apps route events
without re-deriving type from the summary (GwaTop port §1 adapter needs this)."""
from syllabus_classifier.compile import compile_record
from syllabus_classifier.kb.resolver import KBResolver
from syllabus_classifier.record.schema import empty_record

TT = {"yonsei_seoul": {"periods": {"2": ["10:30", "11:45"], "3": ["12:00", "13:15"]}}}
CAL = {"yonsei__2026_2": {
    "term_start": "2026-09-01", "term_end": "2026-12-18", "weeks": 16,
    "term_start_confidence": "high", "holidays": ["2026-10-05"],
}}

_VALID_KINDS = {"class", "exam", "assignment", "office_hours"}


def _kb():
    return KBResolver(timetables=TT, calendars=CAL)


def _record():
    r = empty_record()
    r["meta"].update({"school": "연세대학교", "academic_year": 2026, "term": "가을"})
    r["course"]["title_ko"] = "자료구조"
    r["meeting"].update(status="present", raw_time="월 2,3교시")
    r["schedule"]["exams"].append(
        {"title": "중간고사", "date_kind": "absolute", "resolved_date": "2026-10-20",
         "resolved_by": "in_document", "raw_reference": "중간고사 10/20"})
    r["schedule"]["assignments"].append(
        {"title": "과제1", "date_kind": "absolute", "resolved_date": "2026-11-03",
         "resolved_by": "in_document", "raw_reference": "과제1 11/3"})
    return r


def test_every_event_carries_a_valid_kind():
    out = compile_record(_record(), kb=_kb())
    all_events = (out["confirmed_events"] + out["weekly_timetable"]
                  + out["needs_review_events"])
    assert all_events, "fixture should produce at least one event"
    for ev in all_events:
        assert ev.get("kind") in _VALID_KINDS, ev


def test_class_exam_assignment_kinds_are_distinct():
    out = compile_record(_record(), kb=_kb())
    assert all(s["kind"] == "class" for s in out["weekly_timetable"])
    kinds = {e["kind"] for e in out["confirmed_events"]}
    assert "class" in kinds and "exam" in kinds and "assignment" in kinds


def test_kind_survives_needs_review_demotion():
    # exam with no date evidence → needs_review, but still tagged "exam"
    r = _record()
    r["schedule"]["exams"] = [{"title": "기말고사", "date_kind": "absolute",
                               "raw_reference": "기말 TBA"}]
    out = compile_record(r, kb=_kb())
    exam_reviews = [e for e in out["needs_review_events"] if e["kind"] == "exam"]
    assert exam_reviews
