"""Rule validator — the safety net behind the model (Phase 9 / v2 §7).

Even if the model errs, these deterministic rules must stop a wrong time from
reaching class_schedule. The guiding asymmetry: failing to fill a value is
recoverable; filling it wrongly destroys trust. So when in doubt we reject from
class_schedule and record why in `rejected_time_candidates`.
"""
from __future__ import annotations

import re
from typing import Optional

from ..common.schema import (
    Classification,
    DateKind,
    Label,
    ScheduleStatus,
    TimeCandidate,
    include_in_class_schedule,
)

_OFFICE_CUES = [
    "면담", "상담", "office hour", "office hours", "office location", "오피스아워",
    "appointment", "webex", "연구실 및 면담", "consultation",
]
_DURATION_RE = re.compile(r"^\s*\d+\s*분(?:간)?\s*$")
_WEEK_ONLY_RE = re.compile(r"\d+\s*주차|week\s*\d+", re.IGNORECASE)
_HAS_CLOCK_RE = re.compile(r"\d{1,2}:\d{2}|\d{1,2}\s*시|교시")
# A real class time is a range or a 교시. A lone point time (export timestamp,
# deadline instant) must never survive as class_schedule.
_CLASS_SHAPE_RE = re.compile(r"(?:\d{1,2}:\d{2}|\d{1,2}\s*시)\s*[~\-–—]\s*(?:\d{1,2}:\d{2}|\d{1,2}\s*시)|\d*\s*교시")


def has_office_hours_context(candidate: TimeCandidate) -> bool:
    """True if office-hours cues appear anywhere in the candidate's context."""
    blob = (candidate.context_blob() + " " + (candidate.candidate_text or "")).lower()
    return any(cue.lower() in blob for cue in _OFFICE_CUES)


def is_duration(text: str) -> bool:
    """`50분간` / `90분` — a length, never a start/end time (spec Phase 9)."""
    return bool(_DURATION_RE.match(text or ""))


def validate_candidate(
    candidate: TimeCandidate, classification: Classification
) -> tuple[Classification, Optional[dict]]:
    """Apply the safety-net rules to one (candidate, classification) pair.

    Returns the possibly-corrected classification and, if the candidate was
    rejected from class_schedule, a rejection record for audit.
    """
    rejection: Optional[dict] = None

    def reject(reason: str, new_label: Label) -> Classification:
        nonlocal rejection
        rejection = {
            "text": candidate.candidate_text,
            "rejected_from": "class_schedule",
            "reason": reason,
        }
        return Classification(
            classified_as=new_label.value,
            include_in_class_schedule=False,
            confidence=classification.confidence,
            evidence_label=classification.evidence_label,
            reason=reason,
        )

    # Rule 1: office-hours context can NEVER be class_schedule.
    if has_office_hours_context(candidate):
        if classification.classified_as == Label.CLASS_SCHEDULE.value:
            new = Label.TA_OFFICE_HOURS if _is_ta(candidate) else Label.INSTRUCTOR_OFFICE_HOURS
            return reject("Office-hours context near candidate.", new), rejection
        # already non-class; leave as-is
        return classification, None

    # Rule 2: a duration is not a time-of-day event.
    if is_duration(candidate.candidate_text):
        if classification.classified_as == Label.CLASS_SCHEDULE.value:
            return reject("Duration expression, not a start/end time.", Label.POLICY_TEXT), rejection
        return classification, None

    # Rule 3: exam given only as "N주차" must stay tentative, not a fixed class time.
    if (
        classification.classified_as == Label.CLASS_SCHEDULE.value
        and _WEEK_ONLY_RE.search(candidate.candidate_text or "")
        and not _HAS_CLOCK_RE.search(candidate.candidate_text or "")
    ):
        return reject("Week-only reference has no concrete class time.", Label.WEEKLY_PLAN), rejection

    # Rule 4: class_schedule must have a class-time shape (range/period). A lone
    # point time (export timestamp, deadline instant) is not a class time. This
    # also guards the future trained model, not just the heuristic baseline.
    if (
        classification.classified_as == Label.CLASS_SCHEDULE.value
        and not _CLASS_SHAPE_RE.search(candidate.candidate_text or "")
    ):
        return reject("Single point time, not a class-time shape (range/period expected).", Label.UNKNOWN), rejection

    return classification, None


def _is_ta(candidate: TimeCandidate) -> bool:
    blob = (candidate.context_blob() + " " + (candidate.candidate_text or "")).lower()
    return any(k in blob for k in ["조교", "t/a", "t.a", "teaching assistant", " ta "])


def assemble_document_output(
    doc_id: Optional[str],
    validated: list[tuple[TimeCandidate, Classification, Optional[dict]]],
) -> dict:
    """Build the final per-document output (spec Phase 9 / v2 §6 shape).

    class_schedule.status is `present` only if at least one candidate survived as
    class_schedule; otherwise `not_specified` — we never fill it from other
    sections' times.
    """
    time_candidates = []
    rejected = []
    class_events = []

    for cand, cls, rej in validated:
        time_candidates.append(
            {
                "text": cand.candidate_text,
                "classified_as": cls.classified_as,
                "include_in_class_schedule": cls.include_in_class_schedule,
                "evidence_label": cls.evidence_label,
                "date_kind": cand.date_kind,
                "confidence": cls.confidence,
            }
        )
        if rej:
            rejected.append(rej)
        if cls.include_in_class_schedule:
            class_events.append(
                {"text": cand.candidate_text, "date_kind": cand.date_kind, "page": cand.page}
            )

    if class_events:
        class_schedule = {"status": ScheduleStatus.PRESENT.value, "events": class_events}
    else:
        class_schedule = {
            "status": ScheduleStatus.NOT_SPECIFIED.value,
            "events": [],
            "reason": "No explicit class meeting time found.",
        }

    return {
        "doc_id": doc_id,
        "class_schedule": class_schedule,
        "time_candidates": time_candidates,
        "rejected_time_candidates": rejected,
    }
