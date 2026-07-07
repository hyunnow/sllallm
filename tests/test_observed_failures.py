"""Regression tests for the failures actually observed in the user's comparison
Excel (v4 §3). Each test nails one failure class so a change that reintroduces
it fails loudly. Failure IDs (3-1 …) reference the v4 spec.
"""
import pytest

from syllabus_classifier.extract.field_router import extract_subsystem, route_document
from syllabus_classifier.extract.normalize_doc import NormalizedDoc, Page, Table
from syllabus_classifier.extract.rule_fields import (
    cut_at_next_label,
    extract_academic_year,
    extract_rule_fields,
    extract_school_campus,
)
from syllabus_classifier.merge import build_record


def doc_from(text="", tables=None, doc_id="t"):
    return NormalizedDoc(doc_id=doc_id, pages=[Page(page_no=1, text=text, tables=tables or [])])


# --- 3-1: academic year must never come from the print/export date -------------

def test_3_1_haknyeondo_beats_print_date():
    d = doc_from("2015학년도 1학기 교과목계획표\n...\n2016.10.6. 학사관리시스템 출력")
    assert extract_academic_year(d) == 2015


def test_3_1_print_date_alone_is_not_a_year():
    d = doc_from("실라버스\n출력일: 2016.10.6. 학사관리\nhttp://sugang.univ.ac.kr")
    assert extract_academic_year(d) is None


def test_3_1_english_term_adjacent_year_counts():
    # evidence-based English shapes — the year sits next to a term word
    assert extract_academic_year(doc_from("2026 YONSEI INTERNATIONAL SUMMER SCHOOL")) == 2026
    assert extract_academic_year(doc_from("Course Syllabus — Spring 2025, Section 01")) == 2025
    # a bare year with no term word nearby is still NOT evidence
    assert extract_academic_year(doc_from("Copyright 2024 University Press. All rights reserved.")) is None


# --- 3-2: school vs department -------------------------------------------------

def test_3_2_department_never_becomes_school():
    t = Table(header=["개설학과", "National Statistics"], rows=[])
    d = doc_from("고려대학교 2015학년도 2학기", tables=[t])
    school, _ = extract_school_campus(d)
    assert school == "고려대학교"
    rec = build_record(d, route_document(d))
    assert rec["meta"]["school"] == "고려대학교"
    assert rec["meta"]["department"] != "고려대학교"


def test_3_2_department_only_doc_leaves_school_null():
    t = Table(header=[], rows=[["개설학과", "통계학과"]])
    d = doc_from("교과목 계획표", tables=[t])
    school, _ = extract_school_campus(d)
    assert school is None
    rec = build_record(d, route_document(d))
    assert rec["meta"]["school"] is None
    assert rec["meta"]["department"] == "통계학과"


# --- 3-4 / 3-5: exam dates are never hallucinated -------------------------------

def test_3_4_week_only_exam_gets_no_date():
    t = Table(header=[], rows=[["중간고사", "Week 8"], ["기말고사", "Week 16"]])
    d = doc_from("Exams: Midterm Week 8, Final Week 16", tables=[t])
    sub = extract_subsystem(d)
    exams = sub["schedule.exams"]
    assert exams, "week-only exam references must still be captured"
    for e in exams:
        assert e["resolved_date"] is None
        assert e["date_kind"] in ("relative", "uncertain", "recurring")
        assert e["needs_review"] is True


def test_3_4_record_builder_strips_unsupported_dates():
    d = doc_from("dummy")
    outputs = {
        "rule": {},
        "subsystem": {
            "meeting.status": "not_specified", "meeting.events": [],
            "instructors.office_hours": [],
            "schedule.exams": [{"type": "midterm", "date_kind": "relative",
                                "raw_reference": "Week 8",
                                "resolved_date": "2005-05-01",  # hallucinated
                                "needs_review": False}],
            "schedule.assignments": [],
        },
        "llm": {},
    }
    rec = build_record(d, outputs)
    assert rec["schedule"]["exams"][0]["resolved_date"] is None
    assert rec["schedule"]["exams"][0]["needs_review"] is True
    assert any(f["field"] == "schedule.exams" for f in rec["needs_review"])


# --- 3-6: TBA class time ---------------------------------------------------------

def test_3_6_tba_class_time():
    t = Table(header=[], rows=[["Class Time", "TBA"]])
    d = doc_from("Class Time: TBA", tables=[t])
    sub = extract_subsystem(d)
    assert sub["meeting.status"] == "tba"
    assert sub["meeting.events"] == []


# --- 3-8: adjacent-cell bleed is cut at the next label ---------------------------

def test_3_8_title_stops_before_next_label():
    assert cut_at_next_label("미분적분학과벡터해석(1) 학점 3") == "미분적분학과벡터해석(1)"


def test_3_8_instructor_stops_before_affiliation_label():
    assert cut_at_next_label("안상욱 담당교수소속 과학기술대학 수학") == "안상욱"


def test_3_8_rule_fields_apply_cutting():
    t = Table(header=[], rows=[["교과목명", "미분적분학과벡터해석(1) 학점 3"],
                               ["담당교수", "안상욱 담당교수소속 과학기술대학 수학"]])
    d = doc_from("", tables=[t])
    fields = extract_rule_fields(d)
    assert fields["course.title_ko"] == "미분적분학과벡터해석(1)"
    assert fields["instructors.name"] == "안상욱"


# --- 3-9: homework/quiz rows classify deterministically --------------------------

def test_3_9_homework_week_is_assignment_not_exam():
    t = Table(header=[], rows=[["Homework & Quiz", "Week 1"]])
    d = doc_from("", tables=[t])
    sub = extract_subsystem(d)
    assert sub["schedule.assignments"], "homework row must land in assignments"
    assert not sub["schedule.exams"], "homework row must not also become an exam"


# --- 3-10: async/OCW courses have no meeting events (and that is not an error) ---

def test_3_10_async_course():
    d = doc_from("본 강좌는 KOCW 온라인 강의로 운영됩니다. 주별 학습내용은 아래와 같습니다.")
    sub = extract_subsystem(d)
    assert sub["meeting.status"] == "async"
    assert sub["meeting.events"] == []
    rec = build_record(d, route_document(d))
    assert rec["meeting"]["status"] == "async"
    assert rec["meeting"]["events"] == []


# --- 3-3: 교시 -> 시각 is KB-only; out-of-KB never yields an invented time ---------

def test_3_3_period_resolution_is_kb_only():
    from syllabus_classifier.kb.resolver import KBResolver, resolve_period_reference

    kb = KBResolver(timetables={"yonsei_wonju": {"periods": {"5": ["13:00", "13:50"],
                                                             "6": ["14:00", "14:50"]}}},
                    calendars={})
    # in-KB campus resolves deterministically (no per-method divergence possible)
    ok = resolve_period_reference([5, 6], timetable_key="yonsei_wonju", kb=kb)
    assert (ok.start_time, ok.end_time) == ("13:00", "14:50")
    # out-of-KB school: no time is invented — needs_review instead (SYL-022/024/028)
    miss = resolve_period_reference([5, 6], timetable_key="unknown_univ", kb=kb)
    assert miss.start_time is None and miss.needs_review


# --- 3-7: column shift / week continuity -> abstain, never emit shifted rows -----

def test_3_7_column_shift_and_week_continuity():
    from syllabus_classifier.extract.normalize_doc import Table
    from syllabus_classifier.extract.table_plan import parse_weekly_plan

    shifted = Table(header=["주차", "수업내용"],
                    rows=[["1", "Week 2"], ["2", "3/4-3/8"], ["3", "file3.pdf"], ["4", "ok"]])
    plan = parse_weekly_plan(doc_from("", tables=[shifted]))
    assert plan.needs_review and "column_shift" in plan.issues and plan.rows == []

    gapped = Table(header=["주차", "수업내용"],
                   rows=[["1", "a"], ["2", "b"], ["5", "c"], ["6", "d"]])
    plan2 = parse_weekly_plan(doc_from("", tables=[gapped]))
    assert plan2.needs_review and "week_gap" in plan2.issues and plan2.total_weeks is None
