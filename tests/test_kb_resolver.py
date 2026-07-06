"""KB resolver tests (v2 §2). Uses explicit in-test KBs — never invents dates."""
from syllabus_classifier.kb.resolver import KBResolver

TIMETABLES = {
    "univ_a__regular": {"periods": {"1": ["09:00", "09:50"], "2": ["10:00", "10:50"]}},
    "univ_a__summer": {"periods": {"1": ["09:00", "10:40"]}},
}
CALENDARS = {
    "univ_a__2026_fall": {
        "term_start": "2026-09-01",   # a Tuesday
        "term_end": "2026-12-18",
        "holidays": ["2026-09-24"],   # Thu of week 4
        "makeup_days": {},
    }
}


def r():
    return KBResolver(timetables=TIMETABLES, calendars=CALENDARS)


def test_period_to_time():
    rt = r().resolve_period("univ_a", "regular", [1, 2])
    assert rt.start_time == "09:00" and rt.end_time == "10:50"
    assert rt.resolved_by == "period_timetable_kb"
    assert not rt.needs_review


def test_seasonal_term_differs():
    assert r().resolve_period("univ_a", "summer", [1]).end_time == "10:40"


def test_missing_timetable_needs_review():
    rt = r().resolve_period("univ_x", "regular", [1])
    assert rt.needs_review and rt.start_time is None


def test_week_to_date():
    # term_start 2026-09-01 (Tue). Week 1 Monday = 2026-08-31. Week 2 Tuesday = 2026-09-08.
    rd = r().resolve_week("univ_a__2026_fall", 2, "Tuesday")
    assert rd.resolved_date == "2026-09-08"
    assert rd.resolved_by == "academic_calendar_kb"


def test_week_on_holiday_flagged():
    # Week 4 Thursday = 2026-09-24, which is a holiday with no makeup.
    rd = r().resolve_week("univ_a__2026_fall", 4, "Thursday")
    assert rd.is_holiday and rd.needs_review


def test_missing_calendar_no_invented_date():
    rd = r().resolve_week("univ_unknown__2027_fall", 3, "Monday")
    assert rd.resolved_date is None and rd.needs_review
