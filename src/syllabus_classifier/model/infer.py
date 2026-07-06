"""Classifier interface + a heuristic baseline (mechanism M).

The trained encoder (Phase 7) will implement the same `Classifier.predict`
interface, so everything downstream — validator, eval, scripts — works today
against the heuristic baseline and swaps in the real model unchanged.

The heuristic is intentionally conservative about `class_schedule`: it assigns
that label only when a time looks like a meeting time AND no disqualifying cue
(office hours, exam, deadline, week plan) is present. When unsure it does NOT
pick class_schedule — precision > recall (classifier spec §1, §7).
"""
from __future__ import annotations

import re
from typing import Protocol

from ..common.schema import Classification, Label, TimeCandidate, include_in_class_schedule

# --- context cue lexicons --------------------------------------------------

_OFFICE_HOURS_CUES = [
    "면담", "상담", "office hour", "office hours", "office location", "오피스아워",
    "office-hour", "appointment", "연구실", "webex 상담",
]
_TA_CUES = ["조교", "t/a", "ta ", " ta", "t.a", "조교 ", "teaching assistant"]
_EXAM_CUES = ["시험", "고사", "exam", "midterm", "중간고사", "final", "기말고사", "퀴즈", "quiz"]
_ASSIGN_CUES = ["과제", "제출", "마감", "deadline", "assignment", "숙제", "레포트", "리포트", "제출기한"]
_WEEKPLAN_CUES = ["주차", "week", "강의계획", "진도", "차시", "주별", "weekly"]
_POLICY_CUES = ["정책", "규정", "policy", "유의사항", "안내사항", "성적", "출결"]
_CLASS_CUES = ["수업", "강의", "class", "lecture", "강의시간", "수업시간", "정규"]

_DURATION_RE = re.compile(r"\d+\s*분(?:간)?")
# A genuine time-of-day signal. A weekday ALONE is deliberately NOT enough to
# call something a class time (precision > recall).
_HAS_TIME_RE = re.compile(r"\d{1,2}:\d{2}|\d{1,2}\s*시|\d+\s*교시", re.IGNORECASE)


def _contains_any(haystack: str, needles: list[str]) -> bool:
    h = haystack.lower()
    return any(n.lower() in h for n in needles)


class Classifier(Protocol):
    """Anything that maps a candidate to a Classification. The encoder model and
    the heuristic baseline both satisfy this."""

    def predict(self, candidate: TimeCandidate) -> Classification: ...


class HeuristicClassifier:
    """Keyword/context baseline. No training required. Serves as the pre-model
    baseline and as a sane default in the rule-first pipeline."""

    def predict(self, candidate: TimeCandidate) -> Classification:
        ctx = (candidate.context_blob() + " " + (candidate.candidate_text or "")).strip()
        text = candidate.candidate_text or ""

        # duration ("50분간 진행") is not a time-of-day event at all
        if _DURATION_RE.fullmatch(text.strip()) or (_DURATION_RE.search(text) and ":" not in text and "시" not in text):
            return self._c(Label.POLICY_TEXT, 0.6, candidate, "duration, not a start/end time")

        # office hours — the flagship failure mode. Check first, hardest.
        if _contains_any(ctx, _OFFICE_HOURS_CUES):
            if _contains_any(ctx, _TA_CUES):
                return self._c(Label.TA_OFFICE_HOURS, 0.9, candidate, "TA office-hours context")
            return self._c(Label.INSTRUCTOR_OFFICE_HOURS, 0.95, candidate, "office-hours context")

        if _contains_any(ctx, _EXAM_CUES):
            return self._c(Label.EXAM_TIME, 0.85, candidate, "exam context")

        if _contains_any(ctx, _ASSIGN_CUES) or text.strip() in {"23:59", "23:59:59"}:
            return self._c(Label.ASSIGNMENT_DEADLINE, 0.8, candidate, "assignment/deadline context")

        # week/plan references (8주차, week 3) with no concrete class time
        if _contains_any(text, _WEEKPLAN_CUES) or _contains_any(ctx, _WEEKPLAN_CUES):
            if not _HAS_TIME_RE.search(text):
                return self._c(Label.WEEKLY_PLAN, 0.75, candidate, "weekly-plan reference")

        if _contains_any(ctx, _POLICY_CUES):
            return self._c(Label.POLICY_TEXT, 0.6, candidate, "policy text")

        # class time: needs a positive class cue AND a real time (not just a
        # weekday), with no disqualifier. When in doubt, we do NOT pick class.
        if _HAS_TIME_RE.search(text) and _contains_any(ctx, _CLASS_CUES):
            return self._c(Label.CLASS_SCHEDULE, 0.9, candidate, "class-time context with clock time")

        # a bare weekday or clock time with no class context — do NOT guess class.
        return self._c(Label.UNKNOWN, 0.4, candidate, "insufficient context")

    @staticmethod
    def _c(label: Label, conf: float, cand: TimeCandidate, reason: str) -> Classification:
        return Classification(
            classified_as=label.value,
            include_in_class_schedule=include_in_class_schedule(label),
            confidence=conf,
            evidence_label=cand.table_row_label or cand.section_title,
            reason=reason,
        )
