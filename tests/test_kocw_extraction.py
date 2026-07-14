"""GwaTop 이식 3단계 회귀 — KOCW/포털형 강의계획서 수업시간·status 추출.

실측(2026-07 섀도)에서 KB 커버 학교의 class_times 가 0/12 였던 실패 원문을 고정한다:
연세 bare 교시, 건국 콜론 없는 HHMM, 홍익/동국 'N시' o'clock, 그리고 async 오탐
구조 수정(KOCW=출처는 async 아님, raw_time 있으면 present, 근거 없으면 needs_review).
"""
from syllabus_classifier.compile import compile_record
from syllabus_classifier.extract.field_router import _ASYNC
from syllabus_classifier.kb.resolver import KBResolver
from syllabus_classifier.normalize.class_time import to_notation
from syllabus_classifier.record.schema import empty_record

_KB = KBResolver()


# --- (1) 수업시간 포맷: 실패 원문 → 기대 notation (회귀 고정) --------------------
def test_yonsei_bare_period_lists_resolve():
    # 연세: "수5,6" 처럼 '교시' 접미사 없는 bare 교시 — KB 있을 때만 해석
    assert to_notation("수5,6,목5(목6)", timetable_key="yonsei_seoul", kb=_KB) == \
        "Wed 13:00-14:50 ; Thu 13:00-13:50"
    assert to_notation("화5,6,수7(수8)", timetable_key="yonsei_seoul", kb=_KB) == \
        "Tue 13:00-14:50 ; Wed 15:00-15:50"
    assert to_notation("화6, 목3,4(화5)", timetable_key="yonsei_seoul", kb=_KB) == \
        "Tue 14:00-14:50 ; Thu 11:00-12:50"


def test_konkuk_colonless_hhmm_range():
    # 건국 KOCW: "화1400-1500" (콜론 없는 HHMM)
    assert to_notation("화1400-1500, 목1300-1500", timetable_key="konkuk", kb=_KB) == \
        "Tue 14:00-15:00 ; Thu 13:00-15:00"


def test_oclock_si_formats():
    # 홍익/동국: "15시-18시", "15-16시"(끝에만 시)
    assert to_notation("일 15시-18시", timetable_key="hongik", kb=_KB) == "Sun 15:00-18:00"
    assert to_notation("수15-16시", timetable_key="dongguk", kb=_KB) == "Wed 15:00-16:00"


def test_bare_periods_abstain_without_kb():
    # KB(교시표) 없으면 bare 숫자는 종전대로 abstain — 정밀도 보존
    assert to_notation("수5,6,목5(목6)") is None
    assert to_notation("화6, 목3,4") is None


def test_existing_formats_unregressed():
    assert to_notation("월2,3교시", timetable_key="yonsei_seoul", kb=_KB) == "Mon 10:00-11:50"
    assert to_notation("화 14:00-15:00") == "Tue 14:00-15:00"
    # 방번호(607-208)를 시각으로 오인하지 않는다
    assert to_notation("월 18:00(100) 607-208,수 18:00(100) 607-208") == \
        "Mon 18:00-19:40 ; Wed 18:00-19:40"


# --- (2) async 구조 수정 ------------------------------------------------------
def test_async_pattern_excludes_kocw_source():
    # KOCW/OCW 는 출처일 뿐 배달 방식이 아니다 → async 근거로 쓰지 않는다
    assert _ASYNC.search("본 강의는 KOCW 에 공개됩니다") is None
    assert _ASYNC.search("OCW 자료") is None
    # 배달 방식의 긍정 근거는 여전히 매치
    assert _ASYNC.search("비대면 수업")
    assert _ASYNC.search("온라인 강의로 진행")


def _record(status, raw_time=None):
    r = empty_record()
    r["meta"].update({"school": "연세대학교", "academic_year": 2026, "term": "가을"})
    r["course"]["title_ko"] = "자료구조"
    r["meeting"].update(status=status, raw_time=raw_time)
    return r


def test_not_specified_becomes_needs_review_not_silent():
    # 근거 없음(not_specified) → async 처럼 조용히 0개가 아니라 "수업시간 미상" needs_review
    out = compile_record(_record("not_specified"), kb=_KB)
    assert out["confirmed_events"] == [] and out["weekly_timetable"] == []
    assert any("수업시간 미상" in e["review_reason"] for e in out["needs_review_events"])


def test_async_still_emits_no_class_events():
    # 진짜 async(긍정 근거로 판정된) 는 종전대로 수업 이벤트 0 — needs_review 도 안 만든다
    out = compile_record(_record("async"), kb=_KB)
    assert out["weekly_timetable"] == []
    assert not any("수업" in e.get("review_reason", "") for e in out["needs_review_events"])
