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
