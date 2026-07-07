"""Event 4-part contract (제목 | 타입 | 날짜 | 날짜종류) — title extraction,
serialization, and the event-level partial scorer. Synthetic values only."""
from syllabus_classifier.common.schema import TimeCandidate
from syllabus_classifier.eval.excel_harness import ours_for_excel_fields
from syllabus_classifier.eval.method_compare import event_partial_stats, parse_events
from syllabus_classifier.extract.field_router import _event_title, extract_subsystem
from syllabus_classifier.extract.normalize_doc import normalize_text_blob


def cand(**kw):
    base = dict(candidate_text="Week 3")
    base.update(kw)
    return TimeCandidate(**base)


# --- title extraction -----------------------------------------------------

def test_title_from_row_label():
    assert _event_title(cand(table_row_label="Placement Test")) == "Placement Test"


def test_generic_row_label_rejected():
    # "시험" alone is a header, not a title
    assert _event_title(cand(table_row_label="시험")) is None


def test_title_from_preceding_phrase():
    assert _event_title(cand(nearby_text_before="… 성적 안내.\nMidterm Exam:")) == "Midterm Exam"


# --- subsystem emits titled, typed events ----------------------------------

def test_subsystem_event_has_title_and_kind():
    doc = normalize_text_blob("t", "Midterm Exam: Week 3\n과제 제출: Week 5")
    sub = extract_subsystem(doc)
    exams = sub["schedule.exams"]
    assert exams and exams[0]["title"] == "Midterm Exam"
    assert exams[0]["type"] == "midterm"
    assert exams[0]["date_kind"] == "relative"
    assert exams[0]["resolved_date"] is None      # never invent a date


def test_ours_serialization_is_four_part():
    fields = ours_for_excel_fields("Midterm Exam: Week 3", "t")
    ev = fields["이벤트"]
    assert ev is not None
    parts = [p.strip() for p in ev.split(" ; ")[0].split("|")]
    assert len(parts) == 4
    assert parts[0] == "Midterm Exam"
    assert parts[1] == "exam"
    assert parts[3] == "relative"


# --- partial scorer ---------------------------------------------------------

def test_parse_events_pads_and_normalizes():
    evs = parse_events("Midterm Exam | exam | Week 3 | relative ; Final | exam | Week 6")
    assert evs[0] == ("midterm exam", "exam", "week 3", "relative")
    assert evs[1][3] == ""                        # missing 4th part padded


def test_event_partial_counts_part_matches():
    gold_cells = [{"syllabus_id": "S1", "field": "이벤트",
                   "gold": "Midterm Exam | exam | Week 3 | relative"}]
    preds = {
        "old": {("S1", "이벤트"): "Midterm Exam | exam | Week 3 | exam"},   # kind wrong
        "ours": {("S1", "이벤트"): "Midterm Exam | exam | Week 3 | relative"},
    }
    stats = event_partial_stats(gold_cells, preds)
    assert stats["old"]["exact"] == 0
    assert stats["old"]["title"] == 1 and stats["old"]["date"] == 1 and stats["old"]["date_kind"] == 0
    assert stats["ours"]["exact"] == 1 and stats["ours"]["date_kind"] == 1
