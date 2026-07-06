"""Normalization layer tests (C11 / v2 §5)."""
from syllabus_classifier.normalize import (
    normalize_date,
    normalize_range_separators,
    normalize_time,
    normalize_weekday,
)


def test_weekday_variants():
    for token in ["월", "월요일", "월욜", "Mon", "monday", "MONDAY"]:
        assert normalize_weekday(token) == "Monday"
    assert normalize_weekday("금요일") == "Friday"
    assert normalize_weekday("nope") is None


def test_time_24h():
    assert normalize_time("14:00") == "14:00"
    assert normalize_time("오후 2시") == "14:00"
    assert normalize_time("오후 10시") == "22:00"
    assert normalize_time("2:00 PM") == "14:00"
    assert normalize_time("10:00 PM") == "22:00"
    assert normalize_time("22시") == "22:00"
    assert normalize_time("오전 9시 30분") == "09:30"
    assert normalize_time("2PM") == "14:00"


def test_date_iso():
    assert normalize_date("2026.10.27") == "2026-10-27"
    assert normalize_date("2026-10-27") == "2026-10-27"
    assert normalize_date("2026년 10월 27일") == "2026-10-27"
    assert normalize_date("10월 27일") == "10-27"  # year unknown -> MM-DD
    assert normalize_date("27th Oct 2026") == "2026-10-27"


def test_range_separator():
    assert normalize_range_separators("22:00 - 23:00") == "22:00~23:00"
    assert normalize_range_separators("9시부터 11시까지").replace(" ", "") == "9시~11시"
