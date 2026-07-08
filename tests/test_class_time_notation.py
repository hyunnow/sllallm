"""Class-time notation converter — observed raw shapes -> the ` ; ` contract.
Abstains (None) whenever a segment can't be converted confidently."""
from syllabus_classifier.kb.resolver import KBResolver
from syllabus_classifier.normalize.class_time import to_notation

TT = {"yonsei_seoul": {"periods": {"5": ["13:00", "13:50"], "6": ["14:00", "14:50"],
                                   "7": ["15:00", "15:50"], "8": ["16:00", "16:50"]}}}


def kb():
    return KBResolver(timetables=TT, calendars={})


def test_days_share_one_range_room_stripped():
    assert to_notation("TUE THU 10:30-11:45 (104-E101)") == "Tue 10:30-11:45 ; Thu 10:30-11:45"


def test_day_range_with_ampm():
    assert to_notation("Mon-Thu 9:00am-10:40am") == \
        "Mon 09:00-10:40 ; Tue 09:00-10:40 ; Wed 09:00-10:40 ; Thu 09:00-10:40"


def test_korean_days_slash():
    assert to_notation("월/수 11:00-11:50") == "Mon 11:00-11:50 ; Wed 11:00-11:50"


def test_start_plus_duration_pairs_with_room_tails():
    raw = "월 18:00(100) 607-208,수 18:00(100) 607-208"
    assert to_notation(raw) == "Mon 18:00-19:40 ; Wed 18:00-19:40"


def test_periods_via_timetable_kb():
    assert to_notation("화 5,6교시", timetable_key="yonsei_seoul", kb=kb()) == "Tue 13:00-14:50"


def test_bare_digit_lists_abstain():
    # B2-020/022 memos: "금 1,2,3,4,5,6" / "화 19,20,21" — periods or o'clock?
    # even the reviewer couldn't tell -> we must NOT guess, even with a KB.
    assert to_notation("화 19,20,21", timetable_key="yonsei_seoul", kb=kb()) is None
    assert to_notation("금 1,2,3,4,5,6", timetable_key="yonsei_seoul", kb=kb()) is None


def test_periods_without_kb_abstain():
    assert to_notation("화 5,6교시") is None            # no timetable -> keep raw upstream


def test_unconvertible_abstains():
    assert to_notation("TBA") is None
    assert to_notation("상세 시간은 추후 공지") is None
    assert to_notation("") is None


def test_end_before_start_meridiem_recovery():
    # "9:00-1:40pm": end parses as 13:40 via pm; start stays 09:00
    assert to_notation("Mon 9:00am-1:40pm") == "Mon 09:00-13:40"
