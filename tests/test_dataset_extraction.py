"""GwaTop 이식 회귀 — 강의계획서_데이터셋(1,059개, 8 레이아웃) 정답 대비 평가로 드러난
추출 실패의 원문 고정. 세션 2026-07-14: no-title 35%→0%, school 35%→96%,
instructor 71%→97%, credit 68%→99%, grading 0%→89%, class_times 48%→70%,
시험/과제 과다추출(중간고사×6·발표×8) 접기.

각 테스트는 실패 레이아웃의 실제 표면형을 doc_from 으로 재현한다.
"""
from syllabus_classifier.extract.normalize_doc import NormalizedDoc, Page, Table
from syllabus_classifier.extract.rule_fields import (
    extract_rule_fields, _extract_grading, _header_instructor, _clean_instructor,
    _heading_title, _inline_label_title, _surface_school,
)
from syllabus_classifier.extract.field_router import _collapse_dateless
from syllabus_classifier.normalize.class_time import to_notation


def doc_from(text="", tables=None, doc_id="t"):
    return NormalizedDoc(doc_id=doc_id, pages=[Page(page_no=1, text=text, tables=tables or [])])


# --- (1) 제목: 라벨 없는 상단 헤딩 (boxed/minimal — no-title 100% 였던 레이아웃) --------
def test_heading_title_boxed():
    d = doc_from("고려대학교 · 과학기술대학\n미분적분학과 벡터해석\n"
                 "여름학기 2026학년도 수학과 문경연 교수\n강좌번호 학점(이론/실습)")
    f = extract_rule_fields(d)
    assert f["course.title_ko"] == "미분적분학과 벡터해석"


def test_heading_title_minimal_ko_before_en():
    d = doc_from("숙명여자대학교 사회과학대학 사회학과\n사회학개론\nIntroduction to Sociology\n"
                 "HUM1593-05 · 3학점 · 교양선택 · 월 12:00~13:15 · 과학관")
    f = extract_rule_fields(d)
    assert f["course.title_ko"] == "사회학개론"


# --- (2) 제목: 콜론 없는 인라인 라벨 '과목/교과목 <값>' (grid/plain/portal/mono) --------
def test_inline_label_title_variants():
    assert _inline_label_title(doc_from("과목 일반물리학 1 교과목번호 BUS1776-06")) == "일반물리학 1"
    assert _inline_label_title(doc_from("교과목 알고리즘 교과목번호 NUR8141-02")) == "알고리즘"
    assert _inline_label_title(doc_from("과목 : 게임 프로그래밍")) == "게임 프로그래밍"
    assert _inline_label_title(doc_from("교과목 생리학 교과목번호 의예2054")) == "생리학"


def test_inline_label_title_not_prerequisite():
    # '선수과목'·'교과목번호'의 '과목'은 줄머리 라벨이 아니므로 제목으로 새면 안 된다
    assert _inline_label_title(doc_from("선수과목 미적분학")) is None
    assert _inline_label_title(doc_from("교과목번호 BUS1776-06")) is None


def test_inline_title_rejects_section_word():
    # '교과목 목표'(course objectives 섹션 헤더)는 제목 아님
    assert _inline_label_title(doc_from("교과목 목표\n1. ...")) is None


def test_portal_scrape_chrome_not_taken_as_title():
    # 실코퍼스 검증: 한양 웹스크랩 포털 export 상단이 UI 툴바·네비 탭 나열 →
    # 헤딩 폴백이 'Korean English Excel Print'/'Lecture' 를 제목으로 confident-wrong
    # 하게 잡던 것. 포털 크롬 감지 시 헤딩 추론 끔(→ 라벨/인라인 실패면 OpenAI 폴백).
    d = doc_from("Korean English Excel Print\nAttach files\n조회된 데이터가 없습니다.\n"
                 "Lecture\nintroduction\nSyllabus\nSchool year 2026 first semester")
    assert _heading_title(d) is None


def test_junk_banner_titles_rejected():
    # 프로그램 배너·문서제목·UI 라벨은 제목 아님 → fail-closed
    for junk in ("2026 YONSEI INTERNATIONAL SUMMER SCHOOL", "STERN SCHOOL OF BUSINESS",
                 "Syllabus (1st Semester, 2026)", "Spring 2026", "Course Information",
                 "4-WEEK PROGRAM", "카테고리"):
        # 배너 + 메타데이터 한 줄뿐(제목 후보 없음) → 헤딩 폴백이 배너를 취하지 않고 None(폴백)
        d = doc_from(f"{junk}\n2026학년도 1학기 · 3학점 · 담당교수 홍길동")
        f = extract_rule_fields(d)
        assert f["course.title_ko"] is None and f["course.title_en"] is None, junk


def test_bilingual_and_numbered_title_prefix_stripped():
    from syllabus_classifier.extract.rule_fields import _clean_title
    assert _clean_title("(국문) 반도체공학 I") == "반도체공학 I"
    assert _clean_title("<국문> 강화학습") == "강화학습"          # 꺾쇠 마커도
    assert _clean_title("1. Introduction to Education") == "Introduction to Education"


def test_mangled_table_label_fragments_rejected():
    # 실코퍼스(추가 폴더 동국대): 뭉개진 표에서 라벨/강의실/번호섹션 조각이 제목으로
    # 새던 것 — 전부 fail-closed(None → OpenAI 폴백).
    for junk in ("여부 세부 유형", "Classification)", "(혜화관 207-604 강의실)",
                 "1. 교과목표", "평가내용", "이수 여부",
                 "K309(학술문화관 102-309)", "202(계산관)", "Course Title", "\x01 평가내용"):
        d = doc_from(f"{junk}\n2026학년도 1학기 · 3학점 · 담당교수 김철수")
        f = extract_rule_fields(d)
        assert f["course.title_ko"] is None and f["course.title_en"] is None, junk


def test_heading_title_rejects_doctype_and_school():
    # 문서제목/학교/학과 줄은 제목 후보에서 배제, 진짜 제목만
    d = doc_from("2025학년도 1학기 · 명지대학교\n강의 계획 및 진도표\n"
                 "1. 교수자 인적사항\n대학 사회과학대학 Department 사회학과")
    # 라벨/인라인/헤딩 어디서도 문서제목을 제목으로 뽑지 않는다
    assert _heading_title(d) is None or "강의" not in _heading_title(d)


# --- (3) 학교: 사전 확장 + 미등재 표면형 폴백 ------------------------------------
def test_school_dict_expanded_new_entries():
    for name in ("숙명여자대학교", "조선대학교", "서울과학기술대학교", "포항공과대학교"):
        f = extract_rule_fields(doc_from(f"{name} 공과대학\n일반물리학"))
        assert f["meta.school"] == name, name


def test_surface_school_fallback_uncovered():
    # 사전에 없는 학교라도 'X대학교' 표면형은 학교로 인정(교 접미는 단과대학과 안 겹침)
    assert _surface_school("한국무슨무슨대학교 공과대학 2026학년도") == "한국무슨무슨대학교"
    # 단과대학/학과는 학교 아님 (교 접미 없음)
    assert _surface_school("공과대학 기계공학과 강의계획서") is None


# --- (4) class_time: 혼합(명시+교시) run 에서 명시 슬롯 보존 + 차시 동의어 + '/' 구분 ----
def test_mixed_explicit_and_period_keeps_explicit():
    # to_notation 이 all-or-nothing 이던 버그: 교시(KB 없음) 세그먼트가 명시 시각까지 버림
    assert to_notation("화2교시 / 목 10:30~11:45") == "Thu 10:30-11:45"
    assert to_notation("월 14:00~15:50 / 화2차시") == "Mon 14:00-15:50"


def test_slash_separates_daytime_groups():
    assert to_notation("월 12:00~13:15 / 목 14:00~15:50") == "Mon 12:00-13:15 ; Thu 14:00-15:50"


def test_pure_period_without_kb_still_abstains():
    # 순수 교시/차시(명시 시각 없음)는 KB 없으면 종전대로 abstain (정밀도 보존)
    assert to_notation("화6,7 / 목4,5") is None
    assert to_notation("화6차시") is None


def test_classtime_fallback_labelless():
    # 라벨 없는 헤더의 '요일 시각' 도 raw_time 으로 잡힌다 (minimal ·-라인)
    d = doc_from("숙명여자대학교\n사회학개론\nHUM1593-05 · 3학점 · 월 12:00~13:15 / 화 11:00~12:50 · 과학관")
    f = extract_rule_fields(d)
    assert f["meeting.raw_time"] and "12:00" in f["meeting.raw_time"]


def test_combined_cell_classtime_not_mangled_by_time_colon():
    # boxed 결합 셀 "강의시간\n월 12:00~13:15 / 목 14:00~15:50": 콜론 분리가 시각의
    # ':'(12:00)에서 값을 자르던 버그 → 월(MON) 유실. 개행 분리로 두 요일 다 산다.
    tbl = Table(header=["수강대상\n1학년", "강의시간\n월 12:00~13:15 / 목 14:00~15:50", "Classroom\n교양관 523호"],
                rows=[])
    d = NormalizedDoc(doc_id="t", pages=[Page(page_no=1, text="", tables=[tbl])])
    rt = extract_rule_fields(d)["meeting.raw_time"]
    assert rt and to_notation(rt) == "Mon 12:00-13:15 ; Thu 14:00-15:50"


# --- (5) credit: 라벨 없는 'N학점' 폴백 ------------------------------------------
def test_credit_fallback_labelless():
    d = doc_from("고려대학교\n미분적분학\n여름학기 2026학년도 · 3학점 · 전공기초")
    assert extract_rule_fields(d)["course.credits"] == 3.0


# --- (6) instructor: 헤더형 폴백 + form '직위' 라벨 + 직위 접미 제거 -----------------
def test_header_instructor_name_before_title():
    assert _header_instructor("여름학기 2026학년도 수학과 문경연 교수") == "문경연"
    assert _header_instructor("2022학년도 겨울학기 · 담당 은하호 부교수 · 연구실 501호") == "은하호"


def test_header_instructor_form_jikwi():
    # form: '교강사 <이름> 직위 <직함>' — '직위'(라벨)를 이름으로 오인하지 않고 실이름
    assert _header_instructor("교강사 용재철 직위 조교수") == "용재철"
    assert _header_instructor("교수 함유 직위 초빙교수") == "함유"


def test_clean_instructor_strips_titles():
    assert _clean_instructor("석미태 산학협력중점") == "석미태"
    assert _clean_instructor("황규 (초빙교수)") == "황규"
    assert _clean_instructor("위연나 (") == "위연나"
    assert _clean_instructor("임혜욱 겸임") == "임혜욱"


# --- (7) grading: 성적평가 비율 규칙 추출 (규칙 경로 grading 0% 였음) ----------------
def test_grading_extraction_inline():
    text = ("평가 및 성적: 프로젝트 40% · 출석 10% · 과제 20% · 발표 20% · 중간고사 10%\n교재")
    g = _extract_grading(text)
    assert g is not None
    comp = {c["name"]: c["weight"] for c in g["components"]}
    assert comp == {"프로젝트": 40, "출석": 10, "과제": 20, "발표": 20, "중간고사": 10}


def test_grading_picks_grading_not_method_run():
    # 수업방법 비율 run(강의/실습/토의)과 평가 비율 run 이 둘 다 합100 — 채점 run 만 채택
    text = ("강좌운영방식: 강의 5% · 실습 10% · 발표 25% · 토의/토론 60%\n"
            "평가 및 성적: 프로젝트 10%, 중간고사 10%, 출석 35%, 발표 5%, 기말고사 40%")
    g = _extract_grading(text)
    assert g is not None
    comp = {c["name"]: c["weight"] for c in g["components"]}
    assert comp.get("중간고사") == 10 and comp.get("기말고사") == 40 and "강의" not in comp


def test_grading_none_when_no_percentages():
    assert _extract_grading("평가는 상대평가로 진행한다.") is None


# --- (8) 이벤트: 날짜 없는 동일 제목 접기 + 주차표 조각 드롭 (blocker ①) ---------------
def test_exam_title_rejects_week_markers():
    # 실사용 버그(연세/UNIST 스페인어): 주차표 행 '4주 ※기말고사_2025.07.20' 에서 행 라벨
    # '4주'/'2주' 가 시험 제목이 되던 것 → 주차/차시/강 마커는 제목 후보에서 거부.
    from syllabus_classifier.extract.field_router import _GENERIC_EVENT_LABEL
    for wk in ("4주", "2주", "Week 4", "week4", "4강", "3차시", "주차", "week"):
        assert _GENERIC_EVENT_LABEL.match(wk), wk
    for real in ("기말고사", "중간고사", "미분적분학", "Final Exam"):
        assert not _GENERIC_EVENT_LABEL.match(real), real


def test_drop_dateless_exam_when_dated_exists():
    # 날짜 확정된 중간/기말이 있으면 같은 type 의 dateless 조각(주차토픽·수업시간 오분류)은
    # 유령 이벤트가 되므로 드롭 — 캘린더에 가짜 시험/오추정일 안 생기게.
    from syllabus_classifier.extract.field_router import _drop_dateless_when_dated
    exams = [
        {"type": "final", "title": "기말고사", "resolved_date": "2025-07-20"},
        {"type": "final", "title": "○주제…", "resolved_date": None},          # drop
        {"type": "midterm", "title": "중간고사", "resolved_date": "2025-07-08"},
        {"type": "midterm", "title": "수업시간 월2,3", "resolved_date": None},   # drop
    ]
    out = _drop_dateless_when_dated(exams)
    assert len(out) == 2 and all(e["resolved_date"] for e in out)
    # dated 가 없으면(주차만) 그대로 — abstain 유지
    only_dateless = [{"type": "final", "title": "기말고사", "resolved_date": None}]
    assert _drop_dateless_when_dated(only_dateless) == only_dateless


def test_collapse_dateless_same_title_exams():
    ev = [{"type": "midterm", "title": "중간고사", "resolved_date": None} for _ in range(6)]
    ev += [{"type": "final", "title": "기말고사", "resolved_date": None} for _ in range(3)]
    out = _collapse_dateless(ev)
    assert len(out) == 2
    assert {e["title"] for e in out} == {"중간고사", "기말고사"}


def test_collapse_keeps_dated_distinct_events():
    # 날짜가 확정된 서로 다른 실이벤트는 유지 (같은 제목이어도)
    ev = [{"type": "exam", "title": "시험", "resolved_date": "2026-04-22"},
          {"type": "exam", "title": "시험", "resolved_date": "2026-06-10"}]
    assert len(_collapse_dateless(ev)) == 2


def test_collapse_drops_weekly_table_fragments():
    ev = [{"type": None, "title": "주차(Week)", "resolved_date": None},
          {"type": None, "title": "11", "resolved_date": None},
          {"type": None, "title": "Week 월/", "resolved_date": None},
          {"type": None, "title": "발표", "resolved_date": None}]
    out = _collapse_dateless(ev)
    assert [e["title"] for e in out] == ["발표"]
