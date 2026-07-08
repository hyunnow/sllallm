"""Record-level date resolution (v7 §2 wiring). Injected KBs only."""
from syllabus_classifier.kb.record_resolver import calendar_key_for, resolve_record_dates
from syllabus_classifier.kb.resolver import KBResolver

CAL = {"korea__2026_2": {"term_start": "2026-09-01", "term_end": "2026-12-18",
                         "holidays": ["2026-09-24"], "makeup_days": {}}}


def rec(**meta):
    base = {"meta": {"school": "고려대학교", "academic_year": 2026, "term": "2", **meta},
            "schedule": {"exams": [], "assignments": []}, "needs_review": []}
    return base


def kb():
    return KBResolver(timetables={}, calendars=CAL)


def test_week_with_weekday_resolves_to_date():
    r = rec()
    r["schedule"]["exams"].append({"type": "midterm", "raw_reference": "Week 3 Thu",
                                   "date_kind": "relative", "resolved_date": None, "needs_review": True})
    stats = resolve_record_dates(r, kb=kb())
    e = r["schedule"]["exams"][0]
    # term_start 9/1(Tue) -> week1 Mon 8/31 -> week3 Thu = 9/17
    assert e["resolved_date"] == "2026-09-17"
    assert e["resolved_by"] == "academic_calendar_kb"
    assert stats["resolved_date"] == 1


def test_week_only_gets_range_not_a_date():
    r = rec()
    r["schedule"]["assignments"].append({"title": "보고서", "raw_reference": "8주차",
                                         "date_kind": "relative", "resolved_date": None,
                                         "needs_review": True})
    resolve_record_dates(r, kb=kb())
    a = r["schedule"]["assignments"][0]
    assert a["resolved_date"] is None                    # never invent a single date
    assert a["resolved_week_start"] == "2026-10-19"      # week 8 Monday
    assert a["resolved_week_end"] == "2026-10-25"
    assert a["needs_review"] is True                     # week-only stays tentative


def test_holiday_collision_stays_flagged():
    r = rec()
    r["schedule"]["exams"].append({"type": None, "raw_reference": "Week 4 목",
                                   "date_kind": "relative", "resolved_date": None, "needs_review": True})
    resolve_record_dates(r, kb=kb())
    e = r["schedule"]["exams"][0]
    assert e["resolved_date"] == "2026-09-24"            # resolved, but...
    assert e["needs_review"] is True                     # ...it's a holiday, keep flagged


def test_unknown_school_or_past_year_untouched():
    r = rec(school="미지대학교")
    r["schedule"]["exams"].append({"raw_reference": "Week 3 Thu", "date_kind": "relative",
                                   "resolved_date": None, "needs_review": True})
    stats = resolve_record_dates(r, kb=kb())
    assert r["schedule"]["exams"][0]["resolved_date"] is None
    assert stats["resolved_date"] == 0
    assert calendar_key_for("고려대학교", 2015, "2") is None   # past terms: by design