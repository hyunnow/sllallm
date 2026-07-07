"""Phase 4 weekly-plan table extractor (v6 §1) — structure, abstain-on-uncertain,
in-table events with in-document date priority. Synthetic tables only."""
from syllabus_classifier.extract.normalize_doc import NormalizedDoc, Page, Table
from syllabus_classifier.extract.table_plan import parse_weekly_plan


def doc_with(table: Table) -> NormalizedDoc:
    return NormalizedDoc(doc_id="t", pages=[Page(page_no=1, text="", tables=[table])])


def clean_table():
    return Table(
        header=["주차", "기간", "수업내용", "비고"],
        rows=[
            ["1", "2026-09-01~09-05", "오리엔테이션", ""],
            ["2", "2026-09-08~09-12", "자료구조 개요", ""],
            ["3", "2026-09-15~09-19", "중간고사", "지참물 안내"],
            ["4", "2026-09-22~09-26", "트리와 그래프", "과제 1 제출"],
        ],
    )


def test_clean_plan_rows_and_total_weeks():
    plan = parse_weekly_plan(doc_with(clean_table()))
    assert not plan.needs_review and plan.issues == []
    assert plan.total_weeks == 4
    assert [r.week for r in plan.rows] == [1, 2, 3, 4]
    assert plan.rows[1].topic == "자료구조 개요"


def test_in_table_exam_event_resolves_in_document():
    plan = parse_weekly_plan(doc_with(clean_table()))
    exams = [e for e in plan.events if e["kind"] == "exam"]
    assert exams and exams[0]["raw_reference"] == "Week 3"
    assert exams[0]["date_kind"] == "relative"
    assert exams[0]["resolved_date"] == "2026-09-15"       # from the 기간 column
    assert exams[0]["resolved_by"] == "in_document"        # v7 §2 priority 1
    assigns = [e for e in plan.events if e["kind"] == "assignment"]
    assert assigns and assigns[0]["raw_reference"] == "Week 4"


def test_week_only_event_stays_unresolved():
    t = Table(header=["Week", "Topic"], rows=[["1", "Intro"], ["2", "Methods"], ["3", "Midterm Exam"]])
    plan = parse_weekly_plan(doc_with(t))
    exams = [e for e in plan.events if e["kind"] == "exam"]
    assert exams[0]["resolved_date"] is None               # no invented date (SYL-032)
    assert exams[0]["needs_review"] is True


def test_week_gap_abstains():
    t = Table(header=["주차", "수업내용"], rows=[["1", "a"], ["2", "b"], ["5", "c"], ["6", "d"]])
    plan = parse_weekly_plan(doc_with(t))
    assert plan.needs_review and "week_gap" in plan.issues
    assert plan.rows == [] and plan.total_weeks is None and plan.events == []


def test_column_shift_abstains():
    # topics are filenames/dates -> SYL-031-style shift; must NOT emit
    t = Table(header=["주차", "수업내용"],
              rows=[["1", "Week 2"], ["2", "3/4-3/8"], ["3", "lecture3.pdf"], ["4", "ok"]])
    plan = parse_weekly_plan(doc_with(t))
    assert plan.needs_review and "column_shift" in plan.issues
    assert plan.rows == [] and plan.events == []


def test_headerless_numeric_first_column_fallback():
    t = Table(header=[], rows=[["1", "Introduction to ML"], ["2", "Linear models"],
                               ["3", "Trees"], ["4", "Final Exam"]])
    plan = parse_weekly_plan(doc_with(t))
    assert plan.total_weeks == 4
    assert any(e["kind"] == "exam" and e["raw_reference"] == "Week 4" for e in plan.events)
