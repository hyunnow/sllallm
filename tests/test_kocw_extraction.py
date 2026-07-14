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


def test_comma_days_share_trailing_time():
    # "수, 금 15:00~16:15" 는 수·금 둘 다 그 시각 (한쪽만 나오던 버그)
    assert to_notation("수, 금 15:00~16:15") == "Wed 15:00-16:15 ; Fri 15:00-16:15"
    assert to_notation("월, 수 10:30-11:45") == "Mon 10:30-11:45 ; Wed 10:30-11:45"


def test_ai_syllabus_labels_present():
    # 생성 코퍼스/실제 강의계획서에서 흔한 라벨 어휘 커버 (교과명·강좌명·요일 및 시간·시간표)
    from syllabus_classifier.common.config import load_config
    labels = load_config("label_dictionary.yaml")["labels"]
    assert "교과명" in labels["title"] and "강좌명" in labels["title"]
    assert "요일 및 시간" in labels["class_time"] and "시간표" in labels["class_time"]
    assert "강좌번호" in labels["course_code"]


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


# --- 시험 조각 접기 (한 시험 문장이 날짜/요일/시각 토큰마다 다중 항목이 되던 것) ---
def test_exam_fragments_collapse():
    from syllabus_classifier.extract.field_router import _dedup_events
    frags = [
        {"type": "final", "title": "기말고사", "raw_reference": "12월14일",
         "resolved_date": None, "needs_review": True, "_char_start": 6, "_page": 4},
        {"type": "final", "title": "기말고사: 12월14일", "raw_reference": "화",
         "resolved_date": None, "needs_review": True, "_char_start": 14, "_page": 4},
        {"type": "final", "title": "기말고사: 12월14일 (화)", "raw_reference": "2:00-3:00",
         "resolved_date": None, "needs_review": True, "_char_start": 17, "_page": 4},
        # 주차표 유래 같은 시험 (위치 없음, 날짜서명 동일) — 교차-출처 병합 대상
        {"type": "final", "title": "기말고사 실시 12월14일 (화)", "raw_reference": "Week 16",
         "resolved_date": None, "needs_review": True},
        # 다른 시험 (중간, 다른 주차) — 유지
        {"type": "midterm", "title": "중간고사", "raw_reference": "Week 8",
         "resolved_date": None, "needs_review": True},
    ]
    out = _dedup_events(frags, by_date_sig=True)
    finals = [e for e in out if e["type"] == "final"]
    assert len(finals) == 1 and finals[0]["title"] == "기말고사"   # 조각+교차출처 → 1, 깨끗한 base 제목
    assert any(e["type"] == "midterm" for e in out)               # 다른 시험은 유지
    assert all("_char_start" not in e for e in out)               # 임시 위치 필드 제거


def test_distinct_exams_not_merged():
    from syllabus_classifier.extract.field_router import _dedup_events
    # 다른 주차의 두 퀴즈(인접하지만 날짜서명 다름)는 병합 안 됨 — 오병합 방지
    out = _dedup_events([
        {"type": "quiz", "title": "퀴즈", "raw_reference": "3주차",
         "resolved_date": None, "needs_review": True, "_char_start": 0, "_page": 1},
        {"type": "quiz", "title": "퀴즈", "raw_reference": "6주차",
         "resolved_date": None, "needs_review": True, "_char_start": 10, "_page": 1},
    ], by_date_sig=True)
    assert len(out) == 2


# --- 과목명 개행/마커 정규화 + 한/영 분리 (섀도 실측: 표 wrap 된 제목) ---
def test_title_collapses_newlines_and_markers():
    from syllabus_classifier.extract.rule_fields import _derive_titles
    # 영문 제목이 셀에서 여러 줄로 wrap + 선두 '*' 마커
    assert _derive_titles("*BUSINESS\nMANAGEMENT AND\nREAL WORLD\nPRACTICE") == \
        (None, "BUSINESS MANAGEMENT AND REAL WORLD PRACTICE")
    assert _derive_titles("INTRO TO ENTREPRENEURSHIP &\nVENTURE CAPITAL") == \
        (None, "INTRO TO ENTREPRENEURSHIP & VENTURE CAPITAL")


def test_title_splits_korean_and_english():
    from syllabus_classifier.extract.rule_fields import _derive_titles
    # 한국어 제목 + 영문 제목이 한 값에 개행으로 섞임 → 분리
    assert _derive_titles("컴퓨터활용기초\nCOMPUTER APPLICATION BASICS") == \
        ("컴퓨터활용기초", "COMPUTER APPLICATION BASICS")


def test_title_korean_only_unchanged():
    from syllabus_classifier.extract.rule_fields import _derive_titles
    # 한국어 단독 제목은 그대로 (회귀 방지)
    assert _derive_titles("미분적분학과벡터해석(1)") == ("미분적분학과벡터해석(1)", None)
    assert _derive_titles("미적분학") == ("미적분학", None)


def test_title_rejects_timestamp_metadata():
    from syllabus_classifier.extract.rule_fields import _looks_like_title
    # 연세 포털: '최종수정일 2014-…' 타임스탬프가 제목으로 새던 것 차단
    assert not _looks_like_title("00:14 최종수정일 2014-12-27 09:01:23")
    assert not _looks_like_title("최초등록일 2015-07-01 15:21:52")
    assert not _looks_like_title("2014-12-27")
    # 진짜 제목은 통과
    assert _looks_like_title("미분적분학과벡터해석(1)")
    assert _looks_like_title("식품분석및실험")


# --- 포털 URL 도메인으로 학교 감지 (깨진 export 에서 학교명이 소실돼도 URL 은 남을 때) ---
def test_school_from_portal_url_domain():
    from syllabus_classifier.common.config import load_config
    from syllabus_classifier.extract.rule_fields import _school_from_url_domain

    cfg = load_config("school_dictionary.yaml")
    e = _school_from_url_domain("조회 http://ysweb.yonsei.ac.kr:8888/curri120601 찾기", cfg)
    assert e and e["canonical"] == "연세대학교"
    # 도메인 신호가 없으면 None (오탐 없음)
    assert _school_from_url_domain("학교명도 URL 도 없는 본문", cfg) is None
