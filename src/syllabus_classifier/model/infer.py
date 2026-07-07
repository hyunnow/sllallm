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
_ASSIGN_CUES = ["과제", "제출", "마감", "deadline", "assignment", "homework", "숙제", "레포트", "리포트", "제출기한"]
_WEEKPLAN_CUES = ["주차", "week", "강의계획", "진도", "차시", "주별", "weekly"]
_POLICY_CUES = ["정책", "규정", "policy", "유의사항", "안내사항", "성적", "출결"]
_CLASS_CUES = ["수업", "강의", "class", "lecture", "강의시간", "수업시간", "정규"]

_DURATION_RE = re.compile(r"\d+\s*분(?:간)?")
# The SHAPE of a real class time: a time RANGE or a 교시 (period). A single point
# time (e.g. a "2:45 PM" export timestamp, or an "11:59pm" deadline) is
# deliberately NOT a class-time shape — this is what keeps precision high.
_TIME_RANGE_RE = re.compile(r"(?:\d{1,2}:\d{2}|\d{1,2}\s*시)\s*[~\-–—]\s*(?:\d{1,2}:\d{2}|\d{1,2}\s*시)")
_PERIOD_RE = re.compile(r"\d*\s*교시")
# 23:59 / 11:59pm — the classic assignment-deadline instant.
_DEADLINE_RE = re.compile(r"23:59|11:59\s*pm", re.IGNORECASE)
# any clock time (a single start time counts, but only inside a class-time field)
_ANY_TIME_RE = re.compile(r"\d{1,2}:\d{2}|\d{1,2}\s*시")
# a table row/col explicitly labeled as the class-meeting-time field. A time in
# such a cell IS the class time even if written as a single start (월 18:00).
_CLASS_FIELD_RE = re.compile(
    r"강의\s*시간|수업\s*시간|강의\s*요일|수업\s*요일|class\s*time|class\s*hour|meeting\s*time|lecture\s*time",
    re.IGNORECASE,
)


def _is_class_time_shape(text: str) -> bool:
    return bool(_TIME_RANGE_RE.search(text) or _PERIOD_RE.search(text))


def _in_class_field(candidate) -> bool:
    where = f"{candidate.table_row_label or ''} {candidate.table_col_label or ''} {candidate.section_title or ''}"
    return bool(_CLASS_FIELD_RE.search(where))


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

        # Cue families are resolved SAME-LINE first, full context second: the
        # ±context window crosses line breaks, so "Midterm Exam: Week 3" must not
        # flip to assignment because the NEXT line says "과제 제출" (and vice
        # versa). Within a scope the order stays office > assignment > exam
        # (office is the flagship risk; §3-9 keeps homework rows deterministic).
        before_line = (candidate.nearby_text_before or "").splitlines()[-1] if candidate.nearby_text_before else ""
        after_line = (candidate.nearby_text_after or "").splitlines()[0] if candidate.nearby_text_after else ""
        line_ctx = " ".join(p for p in (
            candidate.section_title, candidate.table_row_label, candidate.table_col_label,
            before_line, after_line, text) if p)

        for scope in (line_ctx, ctx):
            if _contains_any(scope, _OFFICE_HOURS_CUES):
                if _contains_any(scope, _TA_CUES) or _contains_any(ctx, _TA_CUES):
                    return self._c(Label.TA_OFFICE_HOURS, 0.9, candidate, "TA office-hours context")
                return self._c(Label.INSTRUCTOR_OFFICE_HOURS, 0.95, candidate, "office-hours context")
            if _contains_any(scope, _ASSIGN_CUES) or _DEADLINE_RE.search(text):
                return self._c(Label.ASSIGNMENT_DEADLINE, 0.8, candidate, "assignment/deadline context")
            if _contains_any(scope, _EXAM_CUES):
                return self._c(Label.EXAM_TIME, 0.85, candidate, "exam context")

        # week/plan references (8주차, week 3) with no concrete class time
        if _contains_any(text, _WEEKPLAN_CUES) or _contains_any(ctx, _WEEKPLAN_CUES):
            if not _is_class_time_shape(text):
                return self._c(Label.WEEKLY_PLAN, 0.75, candidate, "weekly-plan reference")

        if _contains_any(ctx, _POLICY_CUES):
            return self._c(Label.POLICY_TEXT, 0.6, candidate, "policy text")

        # class time. Two ways to qualify (both need a class cue in context):
        #  1. a class-time SHAPE (range or 교시) anywhere, or
        #  2. any clock time sitting in an explicit class-time FIELD/row
        #     (강의시간/Class Time) — a single start time there is the class time.
        # A lone time with neither is NOT class (kills export timestamps).
        if _contains_any(ctx, _CLASS_CUES):
            if _is_class_time_shape(text):
                return self._c(Label.CLASS_SCHEDULE, 0.9, candidate, "class cue + time range/period")
            if _in_class_field(candidate) and _ANY_TIME_RE.search(text):
                return self._c(Label.CLASS_SCHEDULE, 0.85, candidate, "start time in an explicit class-time field")

        # a lone point time, bare weekday, or no class context — do NOT guess class.
        return self._c(Label.UNKNOWN, 0.4, candidate, "insufficient context / not a class-time shape")

    @staticmethod
    def _c(label: Label, conf: float, cand: TimeCandidate, reason: str) -> Classification:
        return Classification(
            classified_as=label.value,
            include_in_class_schedule=include_in_class_schedule(label),
            confidence=conf,
            evidence_label=cand.table_row_label or cand.section_title,
            reason=reason,
        )


class EncoderClassifier:
    """Trained-encoder classifier (Phase 7 output) behind the same `Classifier`
    interface as HeuristicClassifier — so the pipeline/validator are unchanged.

    Applies the conservative class_schedule threshold: a low-confidence
    class_schedule prediction is demoted to its runner-up (precision > recall).
    torch/transformers are imported lazily in __init__.
    """

    def __init__(self, model_dir: str, threshold: float = 0.80, max_length: int = 256, device=None):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        from .train import ID2LABEL, predict_with_threshold

        self._torch = torch
        self._id2label = ID2LABEL
        self._pwt = predict_with_threshold
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device).eval()
        self.threshold = threshold
        self.max_length = max_length

    @staticmethod
    def _compose(candidate: TimeCandidate) -> str:
        from ..dataset.build import compose_input

        return compose_input(candidate.to_dict())

    def predict(self, candidate: TimeCandidate) -> Classification:
        enc = self.tokenizer(
            self._compose(candidate), truncation=True, max_length=self.max_length, return_tensors="pt"
        ).to(self.device)
        with self._torch.no_grad():
            logits = self.model(**enc).logits
        probs = self._torch.softmax(logits, dim=1).cpu().numpy()
        top = self._pwt(probs, self.threshold)[0]
        label = self._id2label[top]
        return Classification(
            classified_as=label,
            include_in_class_schedule=include_in_class_schedule(label),
            confidence=float(probs[0][top]),
            evidence_label=candidate.table_row_label or candidate.section_title,
            reason="encoder",
        )
