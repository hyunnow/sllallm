"""Field router (v4 §5): run each method family over a NormalizedDoc and hand
the per-method outputs to the record builder / method harness.

Methods:
  rule       — rule_fields (structured fields)                      [live]
  subsystem  — the v1 classifier pipeline for time/exam/assignment  [live]
  llm        — section-scoped LLM for free text                     [Phase 3]
  rule_llm   — rule output verified/corrected by LLM                [Phase 3]
"""
from __future__ import annotations

import re
from typing import Optional

from ..model import HeuristicClassifier
from ..validator import validate_candidate
from .candidate_extractor import extract_candidates_from_doc
from .llm_fields import extract_llm_fields
from .rule_fields import extract_rule_fields, labeled_value

_TBA = re.compile(r"\bTBA\b|미정|추후\s*(?:공지|안내)", re.IGNORECASE)
_ASYNC = re.compile(r"사이버\s*강의|온라인\s*강의|비대면|원격\s*수업|동영상\s*강의|e-?learning|OCW|KOCW", re.IGNORECASE)
_EXAM_TYPE = [("midterm", re.compile(r"중간|midterm", re.I)), ("final", re.compile(r"기말|final", re.I)),
              ("quiz", re.compile(r"퀴즈|quiz", re.I))]


def extract_subsystem(doc, classifier=None) -> dict:
    """Time/exam/assignment/office-hours via the existing candidate pipeline."""
    clf = classifier or HeuristicClassifier()
    class_events, office_hours, exams, assignments = [], [], [], []

    for cand in extract_candidates_from_doc(doc):
        cls, _ = validate_candidate(cand, clf.predict(cand))
        label = cls.classified_as
        ctx = cand.context_blob()
        if label == "class_schedule":
            class_events.append({"raw": cand.candidate_text, "date_kind": cand.date_kind, "page": cand.page})
        elif label in ("instructor_office_hours", "ta_office_hours"):
            office_hours.append({"raw": cand.candidate_text, "who": "ta" if label.startswith("ta") else "instructor"})
        elif label == "exam_time":
            etype = next((t for t, pat in _EXAM_TYPE if pat.search(ctx + " " + cand.candidate_text)), None)
            exams.append(_dated_entry(cand, {"type": etype}))
        elif label == "assignment_deadline":
            assignments.append(_dated_entry(cand, {"title": (cand.table_row_label or cand.section_title or None)}))

    raw_time = labeled_value(doc, "class_time", cut=False)
    if raw_time and _TBA.search(raw_time):
        status = "tba"
    elif class_events:
        status = "present"
    elif _ASYNC.search(doc.full_text):
        status = "async"
    else:
        status = "not_specified"

    return {
        "meeting.status": status,
        "meeting.events": class_events if status == "present" else [],
        "instructors.office_hours": office_hours,
        "schedule.exams": exams,
        "schedule.assignments": assignments,
    }


def _dated_entry(cand, extra: dict) -> dict:
    """§3-4/§3-5: a non-absolute reference NEVER gets a resolved date here —
    only the academic-calendar KB may resolve it later."""
    from ..normalize import normalize_date

    resolved = None
    if cand.date_kind == "absolute":
        resolved = normalize_date(cand.candidate_text)
        if resolved and len(resolved) < 10:      # MM-DD without a year is not resolved
            resolved = None
    entry = {
        "date_kind": cand.date_kind,
        "raw_reference": cand.candidate_text,
        "resolved_date": resolved,
        "needs_review": resolved is None,
    }
    entry.update(extra)
    return entry


def route_document(doc, *, llm_enabled: bool = False, classifier=None) -> dict[str, dict]:
    """Run all method families -> {method: {field_path: value}}."""
    return {
        "rule": extract_rule_fields(doc),
        "subsystem": extract_subsystem(doc, classifier=classifier),
        "llm": extract_llm_fields(doc, enabled=llm_enabled),
        # rule_llm lands in Phase 3 (rule output + LLM verification)
    }
