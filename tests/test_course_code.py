"""Course-code parsing (user request 2026-07): labeled AND unlabeled shapes."""
from syllabus_classifier.extract.normalize_doc import NormalizedDoc, Page, Table
from syllabus_classifier.extract.rule_fields import (
    extract_course_code,
    extract_rule_fields,
    find_course_code,
    split_code_from_title,
)


def doc_from(text="", tables=None):
    return NormalizedDoc(doc_id="t", pages=[Page(page_no=1, text=text, tables=tables or [])])


def test_title_colon_code_style():
    # the user's example: 미적분학: MTH101001
    title, code = split_code_from_title("미적분학: MTH101001")
    assert title == "미적분학" and code == "MTH101001"


def test_rule_fields_split_title_and_code():
    t = Table(header=[], rows=[["교과목명", "미적분학: MTH101001"]])
    f = extract_rule_fields(doc_from("", tables=[t]))
    assert f["course.title_ko"] == "미적분학"
    assert f["meta.course_code"] == "MTH101001"


def test_shapes_kaist_yiss_nyu():
    assert find_course_code("PH301 Quantum Mechanics I") == "PH301"
    assert find_course_code("2026 YISS 6W ISM4508-11 CHINESE FOREIGN POLICY") == "ISM4508-11"
    assert find_course_code("TECH-UB.25.001 Introduction to Programming") == "TECH-UB.25.001"


def test_header_region_fallback():
    d = doc_from("MSE35401 Introduction to Semiconductors\nInstructor: ...")
    assert extract_course_code(d) == "MSE35401"


def test_labeled_numeric_code_still_wins():
    t = Table(header=[], rows=[["학수번호", "21031104"]])
    d = NormalizedDoc(doc_id="t", pages=[Page(page_no=1, text="PH301 mention later", tables=[t])])
    assert extract_course_code(d) == "21031104"


def test_blocklist_and_non_codes():
    assert find_course_code("COVID19 대응 수업 운영 안내") is None
    assert find_course_code("강의실 308-211, 연구실 U502") is None
    title, code = split_code_from_title("일반물리학 및 실험")
    assert code is None and title == "일반물리학 및 실험"
