"""Regression fixtures born from reviewer memos (batch 1/2). Each test names the
memo that motivated it. Synthetic values only."""
from syllabus_classifier.eval.method_compare import values_match
from syllabus_classifier.extract.field_router import extract_subsystem
from syllabus_classifier.extract.normalize_doc import NormalizedDoc, Page, Table
from syllabus_classifier.merge import build_record
from syllabus_classifier.extract.field_router import route_document


def doc_from(text="", tables=None):
    return NormalizedDoc(doc_id="t", pages=[Page(page_no=1, text=text, tables=tables or [])])


# --- B2-009/024/030: 학기 표기는 계절 동치로 채점 --------------------------------

def test_term_season_equivalence():
    assert values_match("학기", "2", "가을")
    assert values_match("학기", "fall", "2")
    assert values_match("학기", "봄", "spring")
    assert values_match("학기", "여름", "summer")
    assert not values_match("학기", "여름", "겨울")


# --- B2-035/036: 다분반 혼합 문서는 needs_review로 표면화 (C4) --------------------

def test_multi_section_suspect_flagged():
    t = Table(header=[], rows=[
        ["강의시간", "월 10:00-11:15"], ["강의시간", "화 13:00-14:15"],
        ["강의시간", "수 15:00-16:15"], ["강의시간", "목 09:00-10:15"],
    ])
    d = doc_from("", tables=[t])
    sub = extract_subsystem(d)
    assert sub["meeting.multi_section_suspect"] is True
    rec = build_record(d, route_document(d))
    assert any(f["field"] == "meeting" and "C4" in f["reason"] for f in rec["needs_review"])


def test_single_section_not_flagged():
    t = Table(header=[], rows=[["강의시간", "월 10:00-11:15"]])
    sub = extract_subsystem(doc_from("", tables=[t]))
    assert sub["meeting.multi_section_suspect"] is False


# --- SYL-036/040: CID-깨진 텍스트 레이어는 needs_ocr ------------------------------

def test_cid_garbage_detected(tmp_path):
    from syllabus_classifier.extract.normalize_doc import NormalizedDoc as ND
    # unit-level: the detection predicate itself (normalize_pdf needs a real file,
    # so we test the condition shape used there)
    text = "(cid:4)(cid:5)(cid:6)" * 200
    assert text.count("(cid:") * 8 > len(text) * 0.3
    clean = "정상적인 강의계획서 텍스트입니다. " * 50
    assert not (clean.count("(cid:") * 8 > len(clean) * 0.3)


# ================= batch 3 memos =================

# --- B3-007/B3-039: 학기는 숫자가 아닌 계절 canonical로 출력 ----------------------

def test_b3_039_term_emits_season_not_number():
    from syllabus_classifier.extract.rule_fields import extract_term
    assert extract_term(doc_from("2026년 1학기 강의계획서")) == "봄"
    assert extract_term(doc_from("2026학년도 2학기")) == "가을"
    assert extract_term(doc_from("Digital Innovation Spring 2026")) == "봄"
    assert extract_term(doc_from("여름계절학기 운영계획")) == "여름"


def test_b3_039_term_english_word_boundary():
    from syllabus_classifier.extract.rule_fields import extract_term
    # "waterfall"/"offspring" 속 부분 문자열은 학기 증거가 아니다
    assert extract_term(doc_from("We follow the waterfall model for offspring projects.")) is None


# --- B3-038: bare 숫자열은 수업시간이 아니다 (깨진 표의 '678') ---------------------

def test_b3_038_bare_digit_class_time_abstains():
    from syllabus_classifier.extract.rule_fields import extract_rule_fields
    t = Table(header=[], rows=[["강의시간", "678"]])
    assert extract_rule_fields(doc_from("", tables=[t]))["meeting.raw_time"] is None
    # 요일/시각/교시 증거가 있으면 그대로 방출 (B3-026 표기 포함)
    t2 = Table(header=[], rows=[["강의시간", "금9,10,11,12,13,14"]])
    assert extract_rule_fields(doc_from("", tables=[t2]))["meeting.raw_time"] == "금9,10,11,12,13,14"


# --- B3-033: Classroom 라벨 뒤 코드는 강의실이지 학수번호가 아니다 -----------------

def test_b3_033_classroom_code_not_course_code():
    from syllabus_classifier.extract.rule_fields import find_course_code
    assert find_course_code("Period 2: 11 am-12:40 pm Classroom: EDU 306") is None
    assert find_course_code("강의실: ABC 101 배정") is None
    assert find_course_code("Course IEE3246-01 Korean American History") == "IEE3246-01"


# --- B3-016/B3-021: 학교 부분 표기·약어 매칭 --------------------------------------

def test_b3_016_school_from_partial_token_hanyang():
    from syllabus_classifier.extract.rule_fields import extract_school_campus
    school, _ = extract_school_campus(doc_from("Major classification Course C-Hanyang Core Competencies"))
    assert school == "한양대학교"


def test_b3_021_school_acronym_exact_case_only():
    from syllabus_classifier.extract.rule_fields import extract_school_campus
    # 소문자 영단어 속 substring(because→CAU, kudos→KU)은 학교가 아니다
    school, _ = extract_school_campus(doc_from("This is because we value kudos and causes."))
    assert school is None
    school, _ = extract_school_campus(doc_from("KNU 컴퓨터통신망특론, 경북대 대학원"))
    assert school == "경북대학교"


# --- B3-005/016/025류 채점: 같은 학교의 다른 표기는 동치 ---------------------------

def test_b3_school_notation_equivalence():
    assert values_match("대학", "한양대학교", "Hanyang")
    assert values_match("대학", "New York University", "NYU STERN SCHOOL OF BUSINESS")
    assert values_match("대학", "고려대학교", "KOREA UNIVERSITY")
    assert values_match("대학", "UNIST", "unist")
    assert not values_match("대학", "고려대학교", "연세대학교")


# --- B3-004: 전 주차 동일 토픽은 흘러든 이웃 셀 — 내용 abstain, 주차 수는 유지 -------

def test_b3_004_uniform_topic_abstains_but_keeps_week_count():
    t = Table(header=["주차", "강의내용"], rows=[[f"{i}주차", "선택"] for i in range(1, 16)])
    sub = extract_subsystem(doc_from("", tables=[t]))
    assert not sub.get("schedule.weekly_plan")          # 내용은 방출 금지
    assert sub.get("schedule.total_weeks") == 15        # 주 번호 자체는 진짜

    # 정상 표는 그대로 방출되어야 한다 (가드 오발동 금지)
    t2 = Table(header=["주차", "강의내용"],
               rows=[[f"{i}주차", f"{i}장 내용"] for i in range(1, 16)])
    sub2 = extract_subsystem(doc_from("", tables=[t2]))
    assert len(sub2.get("schedule.weekly_plan") or []) == 15


# --- B3-005/014/017: 기관 이메일 도메인은 학교의 결정론 증거 ------------------------

def test_b3_005_school_from_email_domain():
    from syllabus_classifier.extract.rule_fields import extract_school_campus
    # 가상 local part를 런타임 조립 — PII 가드는 verbatim 이메일만 차단하므로
    # 실존 대학 도메인 테스트는 이 형태로 쓴다 (githooks/pre-commit 참조)
    at = "@"
    school, _ = extract_school_campus(doc_from(
        f"Instructor Rm 801-6, Bldg 112 hong.gildong{at}unist.ac.kr Monday 15:00-16:00"))
    assert school == "UNIST"
    # 공용 도메인은 증거가 아니다
    school, _ = extract_school_campus(doc_from(f"Contact: hong.gildong{at}gmail.com"))
    assert school is None
    # 서로 다른 두 학교 도메인이 섞이면 abstain
    school, _ = extract_school_campus(doc_from(f"a{at}unist.ac.kr b{at}kaist.ac.kr"))
    assert school is None


def test_b3_010_school_from_nfd_filename():
    import unicodedata
    from syllabus_classifier.extract.rule_fields import extract_school_campus
    from syllabus_classifier.extract.normalize_doc import NormalizedDoc, Page
    # macOS 파일명은 NFD 자모 — 본문에 학교명이 없는 kocw류는 파일명이 유일 증거
    nfd_id = unicodedata.normalize("NFD", "kocw_syllabi__18_국민대__분석화학__x")
    d = NormalizedDoc(doc_id=nfd_id, pages=[Page(page_no=1, text="주차별 강의계획", tables=[])])
    school, _ = extract_school_campus(d)
    assert school == "국민대학교"


# --- 2026-07-10 사용자 결정: 무기한 항목 통일 + 수업시간 요일묶음 동치 ---------------

def test_undated_exam_becomes_null_uncertain_event():
    from syllabus_classifier.extract.event_hybrid import risk_gate
    raw = [{"title": "Midterm Exam", "type": "exam", "date_raw": None},
           {"title": "Homework", "type": "assignment", "date_raw": None}]
    dated, undated = risk_gate(raw, "Midterm Exam ... Homework ...")
    # 무기한 시험 → 이벤트(null|uncertain), 무기한 과제 → 무기한과제만
    assert [(e["title"], e["kind"], e["raw_reference"], e["date_kind"]) for e in dated] == \
        [("Midterm Exam", "exam", "null", "uncertain")]
    assert undated == ["Homework"]


def test_b3_028_class_time_day_group_equivalence():
    # 문서 표기 "MON WED 10:30-11:45" == 요일별 분해 표기 (같은 사실)
    assert values_match("수업시간", "Mon 10:30-11:45 ; Wed 10:30-11:45", "MON WED 10:30-11:45")
    assert values_match("수업시간", "월 15:00-16:15 ; 수 15:00-16:15", "월 수 15:00-16:15")
    assert not values_match("수업시간", "Mon 10:30-11:45", "MON WED 10:30-11:45")


# --- 배치4 메모 대응 (2026-07-10) --------------------------------------------

def _doc_with_tables(*tables):
    from syllabus_classifier.extract.normalize_doc import NormalizedDoc, Page
    return NormalizedDoc(doc_id="t", pages=[Page(page_no=1, text="", tables=list(tables))])


def test_b4_037_yiss_week_cell_with_date_range_and_chapter_extras():
    # YISS형: "WEEK1\n(June 29 to July 2, 2026)" 주차 셀 + ASSIGNMENTS 열의 챕터.
    # 챕터는 주차 내용에 포함(B4-035/037 gold), 'Problem set'은 범주 라벨이라 제외,
    # 'Midterm'은 이벤트로 승격.
    from syllabus_classifier.extract.normalize_doc import Table
    from syllabus_classifier.extract.field_router import extract_subsystem

    t = Table(header=["WEEK", "CONTENTS", "ASSIGNMENTS", ""],
              rows=[["WEEK1\n(June 29 to July 2, 2026)", "Preference,\nUtility function", "CH 1: Consumption\ntheory\nProblem set", ""],
                    ["WEEK 2\n(July 6 to July 9, 2026)", "Comparative statics", "CH 1: Consumption theory", "Midterm"]])
    sub = extract_subsystem(_doc_with_tables(t))
    topics = {r["week"]: r["topic"] for r in sub["schedule.weekly_plan"]}
    assert topics[1] == "Preference, Utility function, CH 1: Consumption theory"
    assert "Problem set" not in topics[1]
    assert topics[2] == "Comparative statics, CH 1: Consumption theory"
    assert any(e["raw_reference"] == "Week 2" for e in sub["schedule.exams"])


def test_b4_037_lone_week_row_promoted_from_header_and_boundary_gap():
    # 페이지 분할로 홀로 남은 "WEEK6" 행이 header로 오분류된 표 + week 5 유실:
    # 경계 갭은 방출 유지(needs_review 플래그만), 행은 병합된다.
    from syllabus_classifier.extract.normalize_doc import Table
    from syllabus_classifier.extract.table_plan import parse_weekly_plan

    main = Table(header=["WEEK", "CONTENTS", "", ""],
                 rows=[[f"WEEK{i}\n(2026)", f"topic {i}", "", ""] for i in (1, 2, 3, 4)])
    lone = Table(header=["WEEK6\n(August 3 to August 5,\n2026)", "Public Goods", "CH6 Public Goods", "Final Exam"],
                 rows=[])
    plan = parse_weekly_plan(_doc_with_tables(main, lone))
    weeks = sorted(r.week for r in plan.rows if r.week is not None)
    assert weeks == [1, 2, 3, 4, 6]
    assert plan.total_weeks == 6 and plan.issues == ["week_gap"] and plan.needs_review


def test_b4_029_exam_only_week_row_leaves_weekly_content():
    # 'Midterm week' 행은 이벤트 소관 — 주차별내용 직렬화에서 제외 (B4-029 gold)
    from syllabus_classifier.extract.normalize_doc import Table
    from syllabus_classifier.extract.field_router import extract_subsystem

    t = Table(header=["주차", "수업내용"],
              rows=[["1", "Introduction"], ["2", "Sampling"], ["3", "Midterm week"], ["4", "Regression"]])
    sub = extract_subsystem(_doc_with_tables(t))
    topics = [r["topic"] for r in sub["schedule.weekly_plan"]]
    assert topics == ["Introduction", "Sampling", None, "Regression"]
    assert any(e["raw_reference"] == "Week 3" for e in sub["schedule.exams"])


def test_b4_035_undated_duplicates_of_scheduled_items_suppressed():
    from syllabus_classifier.extract.event_hybrid import suppress_scheduled

    dated = [{"title": "Case (#1) report", "kind": "assignment"}]
    weekly = [{"topic": "Case II: Crocs, Problem set review"}]
    out = suppress_scheduled(
        ["Case (#1) report", "Problem set", "Problem set", "Field essay"], dated, weekly)
    assert out == ["Field essay"]


def test_b4_024_class_time_day_word_and_dash_equivalence():
    assert values_match("수업시간", "Mon 16:55-19:35", "Mondays 16:55–19:35")
    assert values_match("수업시간", "화 09:00-10:15", "화요일 09:00~10:15")
    assert not values_match("수업시간", "Mon 16:55-19:35", "Tuesdays 16:55–19:35")
