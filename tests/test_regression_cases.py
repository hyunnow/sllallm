"""Regression tests (spec Phase 8). These are the assertions that tell us whether
a prompt/model change made things better or worse. They run against the current
pipeline (heuristic baseline + rules); when the encoder lands, the same
assertions must still hold.
"""
from syllabus_classifier.extract import extract_candidates
from syllabus_classifier.model import HeuristicClassifier
from syllabus_classifier.validator import assemble_document_output, validate_candidate

CLF = HeuristicClassifier()


def _run(text, section_title=None, table_row_label=None, doc_id="t"):
    cands = extract_candidates(
        text, section_title=section_title, table_row_label=table_row_label, doc_id=doc_id
    )
    validated = []
    for c in cands:
        cls, rej = validate_candidate(c, CLF.predict(c))
        validated.append((c, cls, rej))
    return assemble_document_output(doc_id, validated), validated


def _labels(validated):
    return {cls.classified_as for _, cls, _ in validated}


def test_office_hours_not_class_schedule():
    out, validated = _run(
        "연구실 및 면담시간 Office Location&Hours: 월요일 22:00~23:00",
        section_title="연구실 및 면담시간 / Office Location&Hours",
        table_row_label="연구실 및 면담시간",
    )
    assert out["class_schedule"]["status"] == "not_specified"
    assert "class_schedule" not in _labels(validated)


def test_ta_office_hours_not_class_schedule():
    out, validated = _run(
        "T/A Office Hours: 수요일 15:00~16:00",
        section_title="T/A Office Hours",
        table_row_label="조교 면담",
    )
    assert out["class_schedule"]["status"] == "not_specified"
    assert "class_schedule" not in _labels(validated)


def test_real_class_time_is_kept():
    out, _ = _run(
        "정규 수업시간: 화요일 10:00~11:50",
        section_title="강의시간",
        table_row_label="수업시간",
    )
    assert out["class_schedule"]["status"] == "present"


def test_duration_not_start_end_time():
    # "50분간 진행" must not become a class time
    _, validated = _run("수업은 50분간 진행", section_title="강의시간", table_row_label="수업시간")
    assert "class_schedule" not in _labels(validated)


def test_week_only_exam_is_tentative():
    # "중간고사 8주차" — week only, no concrete class time -> not class_schedule
    out, validated = _run("중간고사는 8주차에 시행", section_title="평가", table_row_label="중간고사")
    assert out["class_schedule"]["status"] == "not_specified"
    assert "class_schedule" not in _labels(validated)


def test_empty_class_time_not_filled_from_office_hours():
    # class-time row empty; only office hours present -> class_schedule stays empty
    out, _ = _run(
        "강의시간: (미기재)  면담시간: 월요일 22:00~23:00",
        section_title="강의 개요",
        table_row_label="면담시간",
    )
    assert out["class_schedule"]["status"] == "not_specified"
