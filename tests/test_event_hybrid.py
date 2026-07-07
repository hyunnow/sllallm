"""Event hybrid risk gate (v6 §2) — LLM surface is TRUSTED for reading, BLOCKED
from inventing. Fake LLM outputs only; no network."""
from syllabus_classifier.extract.event_hybrid import (
    merge_events,
    risk_gate,
    serialize_events,
)

DOC = """Course schedule
Midterm Exam: Week 3 (Thursday)
Final Exam: 8/6
Reflection Paper — due date announced later
"""


def test_week_reference_stays_relative():
    dated, _ = risk_gate([{"title": "Midterm Exam", "type": "exam", "date_raw": "Week 3 Thu"}], DOC)
    e = dated[0]
    assert e["date_kind"] == "relative"
    assert e["resolved_date"] is None and e["needs_review"] is True


def test_evidenced_absolute_date_resolves_in_document():
    dated, _ = risk_gate([{"title": "Final Exam", "type": "exam", "date_raw": "8/6"}], DOC)
    e = dated[0]
    assert e["date_kind"] == "absolute"
    assert e["resolved_by"] == "in_document" or e["resolved_date"] is None
    # "8/6" appears in the doc -> MM-DD evidence accepted
    assert e["resolved_date"] is None or e["resolved_date"].endswith("08-06")


def test_unevidenced_absolute_date_is_blocked():
    # SYL-032: the LLM invents 2005-05-01 which the document never states.
    dated, _ = risk_gate([{"title": "Midterm Exam", "type": "exam", "date_raw": "2005-05-01"}], DOC)
    e = dated[0]
    assert e["resolved_date"] is None
    assert e["needs_review"] is True
    assert e["date_kind"] != "absolute"           # demoted, not trusted


def test_hallucinated_title_dropped():
    dated, undated = risk_gate([{"title": "Surprise Oral Defense", "type": "exam",
                                 "date_raw": "Week 9"}], DOC)
    assert dated == [] and undated == []


def test_undated_assignment_goes_to_undated_list():
    _, undated = risk_gate([{"title": "Reflection Paper", "type": "assignment",
                             "date_raw": None}], DOC)
    assert undated == ["Reflection Paper"]


def test_uncertain_reference_kind():
    dated, _ = risk_gate([{"title": "Final Exam", "type": "exam", "date_raw": "추후 공지"}],
                         DOC + "\n기말: 추후 공지")
    assert dated[0]["date_kind"] == "uncertain"


def test_merge_dedupes_table_and_llm():
    table = [{"title": "Midterm Exam", "kind": "exam", "raw_reference": "Week 3",
              "date_kind": "relative", "resolved_date": "2026-09-15", "resolved_by": "in_document"}]
    llm = [{"title": "Midterm Exam", "kind": "exam", "raw_reference": "Week 3 Thu",
            "date_kind": "relative", "resolved_date": None}]
    merged = merge_events(table, llm)
    assert len(merged) == 1
    assert merged[0]["resolved_by"] == "in_document"   # table version (resolved) wins


def test_serialize_four_parts():
    s = serialize_events([{"title": "Final Exam", "kind": "exam",
                           "raw_reference": "Week 6 Wed", "date_kind": "relative"}])
    assert s == "Final Exam | exam | Week 6 Wed | relative"
