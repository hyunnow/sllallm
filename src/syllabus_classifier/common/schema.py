"""Single source of truth for the project's vocabulary and typed records.

Everything downstream imports its labels and structures from here so the
configs, the edge-case registry, the KB resolver, the validator, and the tests
never drift apart. If a name changes, it changes here first.

References:
  - classifier spec §4 (label set, classifier I/O)
  - master spec v2 §1 (S/M/KB/R mechanisms), §4 (date_kind), §6 (integrated schema)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class Label(str, Enum):
    """The 8 classes the model (mechanism M) predicts for a time candidate."""

    CLASS_SCHEDULE = "class_schedule"
    INSTRUCTOR_OFFICE_HOURS = "instructor_office_hours"
    TA_OFFICE_HOURS = "ta_office_hours"
    EXAM_TIME = "exam_time"
    ASSIGNMENT_DEADLINE = "assignment_deadline"
    WEEKLY_PLAN = "weekly_plan"
    POLICY_TEXT = "policy_text"
    UNKNOWN = "unknown"


ALL_LABELS: list[str] = [l.value for l in Label]

# Only this label may ever be placed into class_schedule; everything else is
# filtered out. This single rule is what actually prevents the office-hours bug.
_INCLUDE_IN_CLASS_SCHEDULE = {Label.CLASS_SCHEDULE}


def include_in_class_schedule(label: "str | Label") -> bool:
    """Derived boolean: True only for class_schedule (classifier spec §4)."""
    return Label(label) in _INCLUDE_IN_CLASS_SCHEDULE


class DateKind(str, Enum):
    """Every date/time expression is sorted into one of these first (v2 §4)."""

    ABSOLUTE = "absolute"      # 2026.10.27, 10월 27일~11월 10일
    RELATIVE = "relative"      # week 3, 5일차, 1강, 3월  -> resolved via KB
    UNCERTAIN = "uncertain"    # 27일 또는 29일, 추후 공지, 10월 말
    RECURRING = "recurring"    # 매주 금요일, 격주


class Mechanism(str, Enum):
    """How a given variation is handled (v2 §1)."""

    SCHEMA = "S"   # null / array structure — value missing or multiple
    MODEL = "M"    # kind classification — the only thing the model does
    KB = "KB"      # knowledge-base lookup — period->time, week->date
    RULE = "R"     # deterministic rule + needs_review


class ScheduleStatus(str, Enum):
    """class_schedule.status values (v2 §6)."""

    PRESENT = "present"
    NOT_SPECIFIED = "not_specified"   # U1: no class time found — do not invent
    TENTATIVE = "tentative"           # relative/uncertain only
    ASYNC = "async"                   # U6: online/cyber course


@dataclass
class TimeCandidate:
    """One extracted date/time candidate plus its context (classifier input, §4).

    The context fields (section_title, table_row_label, ...) carry the single
    most important signal for classification: *where* in the document the time
    was found. "면담시간" in a row label is what tells us it is not a class time.
    """

    candidate_text: str
    nearby_text_before: str = ""
    nearby_text_after: str = ""
    section_title: Optional[str] = None
    table_row_label: Optional[str] = None
    table_col_label: Optional[str] = None
    page: Optional[int] = None
    doc_id: Optional[str] = None
    # span in the source text, for dedup/debugging
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    # filled by the normalization layer (§5) and date-kind sorter (§4)
    normalized_text: Optional[str] = None
    date_kind: Optional[str] = None
    # the untouched original — always preserved for debugging (v2 §5)
    raw_text: Optional[str] = None

    def context_blob(self) -> str:
        """All context joined — convenient for keyword checks and model input."""
        parts = [
            self.section_title,
            self.table_row_label,
            self.table_col_label,
            self.nearby_text_before,
            self.nearby_text_after,
        ]
        return " ".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Classification:
    """Classifier output for one candidate (classifier spec §4)."""

    classified_as: str
    include_in_class_schedule: bool
    confidence: float
    evidence_label: Optional[str] = None
    # why the classifier / validator landed here — aids debugging and review
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DateReference:
    """Structured date expression after the §4 four-way sort.

    resolved_date stays None until a KB fills it. We never invent a date.
    """

    date_expression: str
    date_kind: str
    raw_reference: Optional[dict] = None       # {"type": "week", "value": 3}
    resolved_date: Optional[str] = None        # ISO or null
    resolved_by: Optional[str] = None          # in_document | *_kb | null
    needs_review: bool = False
    review_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)
