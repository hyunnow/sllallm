"""역방향 학습 (①) — 합성 후보 생성기. 트리거 3조건(동결·게이트·승자 안정) 충족
후 재개. 학습은 Colab이지만 합성 데이터의 무결성·재균형·누출 안전은 여기서 고정."""
from collections import Counter

from syllabus_classifier.common.schema import (
    ALL_LABELS, TimeCandidate, include_in_class_schedule,
)
from syllabus_classifier.dataset.synth import generate
from syllabus_classifier.model.infer import (
    HeuristicClassifier, _ASSIGN_CUES, _EXAM_CUES, _OFFICE_HOURS_CUES,
)
from syllabus_classifier.validator import validate_candidate


def test_generate_is_deterministic():
    assert generate(300, seed=7) == generate(300, seed=7)
    assert generate(300, seed=7) != generate(300, seed=8)


def test_every_row_has_valid_label_and_cue_signal():
    rows = generate(800)
    req = {"exam_time": _EXAM_CUES, "assignment_deadline": _ASSIGN_CUES,
           "instructor_office_hours": _OFFICE_HOURS_CUES}
    for r in rows:
        assert r["label"] in ALL_LABELS
        cues = req.get(r["label"])
        if cues:
            blob = r["input_text"].lower()
            assert any(c.lower() in blob for c in cues), f"{r['label']} 신호 없음: {r['input_text']!r}"


def test_rare_classes_are_boosted():
    c = Counter(r["label"] for r in generate(1200))
    # 희소 클래스가 실 train에서보다 훨씬 큰 비중으로 생성된다
    assert c["exam_time"] > c["weekly_plan"]
    assert c["policy_text"] > c["weekly_plan"]
    assert c["instructor_office_hours"] > 50 and c["ta_office_hours"] > 50


def test_synthetic_doc_ids_never_collide_with_real_split_keys():
    # split은 doc_id로 나뉜다 — 합성 doc_id는 'synthetic__' 접두라 실문서와 안 겹침
    for r in generate(400):
        assert r["doc_id"].startswith("synthetic__")


def test_office_hours_flag_and_boundary_never_leak_to_class():
    # flagship 제약: office-hours 합성은 include_in_class_schedule=False 이고,
    # 검증기를 통과시켜도 class_schedule로 새지 않는다
    clf = HeuristicClassifier()
    for r in generate(600):
        if r["label"].endswith("office_hours"):
            assert r["include_in_class_schedule"] is False
            cand = TimeCandidate(
                candidate_text=r["candidate_text"], nearby_text_before=r.get("nearby_text_before", ""),
                nearby_text_after=r.get("nearby_text_after", ""), section_title=r.get("section_title"),
                table_row_label=r.get("table_row_label"), table_col_label=r.get("table_col_label"),
                page=1, doc_id=r["doc_id"], char_start=0, char_end=0,
                normalized_text=r["candidate_text"], date_kind=r.get("date_kind", "uncertain"),
                raw_text=r["candidate_text"])
            cls, _ = validate_candidate(cand, clf.predict(cand))
            assert cls.classified_as != "class_schedule"


def test_include_flag_matches_label():
    for r in generate(300):
        assert r["include_in_class_schedule"] == include_in_class_schedule(r["label"])
