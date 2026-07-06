#!/usr/bin/env python3
"""Phase 0 smoke test — prove the pipeline runs end-to-end on tiny synthetic data
BEFORE any real data or trained model exists (spec principle: get 10 samples
flowing through the whole pipeline first).

Flow per document:
  normalize text -> extract candidates (rules) -> classify (heuristic baseline)
  -> validate (safety-net rules) -> assemble final JSON

The flagship case ("연구실 및 면담시간: 월요일 22:00~23:00") MUST NOT land in
class_schedule. This script asserts that and prints the final output.

Run:  python scripts/00_smoke_test.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common import set_seed
from syllabus_classifier.extract import extract_candidates
from syllabus_classifier.model import HeuristicClassifier
from syllabus_classifier.validator import assemble_document_output, validate_candidate

# A few synthetic syllabus snippets covering key edge cases.
SAMPLES = [
    {
        "doc_id": "syn-001",
        "section_title": "연구실 및 면담시간 / Office Location&Hours",
        "table_row_label": "연구실 및 면담시간",
        "text": "연구실 및 면담시간 Office Location&Hours: 월요일 22:00~23:00 WebEx를 이용해 비대면으로 시행",
    },
    {
        "doc_id": "syn-002",
        "section_title": "강의시간",
        "table_row_label": "수업시간",
        "text": "정규 수업시간: 화요일 10:00~11:50 강의실 U502",
    },
    {
        "doc_id": "syn-003",
        "section_title": "평가",
        "table_row_label": "중간고사",
        "text": "중간고사는 8주차에 시행합니다. 기말고사 추후 공지.",
    },
    {
        "doc_id": "syn-004",
        "section_title": "과제",
        "table_row_label": None,
        "text": "매주 금요일 23:59까지 과제를 제출하세요.",
    },
    {
        "doc_id": "syn-005",
        "section_title": "T/A Office Hours",
        "table_row_label": "조교 면담",
        "text": "T/A Office Hours: 수요일 15:00~16:00",
    },
]


def run() -> list[dict]:
    set_seed(42)
    clf = HeuristicClassifier()
    outputs = []
    for s in SAMPLES:
        cands = extract_candidates(
            s["text"],
            section_title=s["section_title"],
            table_row_label=s["table_row_label"],
            doc_id=s["doc_id"],
        )
        validated = []
        for c in cands:
            cls = clf.predict(c)
            cls, rej = validate_candidate(c, cls)
            validated.append((c, cls, rej))
        outputs.append(assemble_document_output(s["doc_id"], validated))
    return outputs


def _demo_safety_net() -> dict:
    """Prove the validator catches a *model error*: feed an office-hours candidate
    with a deliberately-WRONG class_schedule label and show it gets overridden
    and logged in rejected_time_candidates (spec Phase 9)."""
    from syllabus_classifier.common.schema import Classification, TimeCandidate

    cand = TimeCandidate(
        candidate_text="월요일 22:00~23:00",
        section_title="연구실 및 면담시간 / Office Location&Hours",
        table_row_label="연구실 및 면담시간",
        doc_id="demo-err",
    )
    wrong = Classification(classified_as="class_schedule", include_in_class_schedule=True, confidence=0.99)
    fixed, rejection = validate_candidate(cand, wrong)
    return {"fixed": fixed.classified_as, "included": fixed.include_in_class_schedule, "rejection": rejection}


def main() -> int:
    outputs = run()
    print(json.dumps(outputs, ensure_ascii=False, indent=2))

    # Guardrail assertions (the whole point of the product).
    by_id = {o["doc_id"]: o for o in outputs}

    office = by_id["syn-001"]
    assert office["class_schedule"]["status"] == "not_specified", "office hours leaked into class_schedule!"
    assert all(
        tc["classified_as"] != "class_schedule" for tc in office["time_candidates"]
    ), "an office-hours candidate was labeled class_schedule!"

    ta = by_id["syn-005"]
    assert ta["class_schedule"]["status"] == "not_specified", "TA office hours leaked into class_schedule!"

    clazz = by_id["syn-002"]
    assert clazz["class_schedule"]["status"] == "present", "real class time was not detected"

    # Safety net: even a wrong model prediction is caught and logged.
    demo = _demo_safety_net()
    assert demo["included"] is False, "validator failed to reject a wrong class_schedule prediction"
    assert demo["rejection"] and demo["rejection"]["reason"], "rejection was not recorded"
    print("\n[safety-net demo]", json.dumps(demo, ensure_ascii=False))

    print("\n[OK] smoke test passed: office/TA hours filtered, real class time kept, "
          "and the validator overrides a wrong class_schedule prediction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
