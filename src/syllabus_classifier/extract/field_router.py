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
_EXAM_TYPE = [("midterm", re.compile(r"중간\s*고사|중간\s*시험|중간|midterm(?:\s+exam)?", re.I)),
              ("final", re.compile(r"기말\s*고사|기말\s*시험|기말|final(?:\s+exam)?", re.I)),
              ("quiz", re.compile(r"퀴즈|quiz(?:\s*#?\d+)?", re.I))]

# row/section labels that are generic headers, not event titles
_GENERIC_EVENT_LABEL = re.compile(
    r"^\s*(?:시험|고사|평가|성적|일정|이벤트|과제|숙제|주차|week|exams?|assignments?|homework|"
    r"evaluation|schedule|grading|date|일자|날짜)\s*$", re.IGNORECASE)


def _event_title(cand) -> "str | None":
    """Best-effort event title from the candidate's own context — text that is
    literally in the document, never invented (§3-4 spirit).

    Priority: a non-generic table row label / section title; else the phrase
    ending right before the date on the same line ("Midterm Exam: Week 3").
    """
    from .rule_fields import cut_at_next_label

    for source in (cand.table_row_label, cand.section_title):
        if not source:
            continue
        t = cut_at_next_label(str(source)).strip(" :|·-–—,\t")
        if t and len(t) <= 80 and not _GENERIC_EVENT_LABEL.match(t):
            return t

    before = (cand.nearby_text_before or "").rstrip(" \t")
    if before and not before.endswith("\n"):
        line = before.splitlines()[-1]
        for sep in (";", "|", "•", "·"):
            if sep in line:
                line = line.rsplit(sep, 1)[-1]
        line = line.strip(" :|·,\t")
        line = re.sub(r"^\W+", "", line)
        line = re.sub(r"[#(\[{№-]+$", "", line).strip()   # dangling "Quiz #", "Exam ("
        # a title starts like a title — a lowercase English start is a sentence
        # fragment from the context window, not an event name.
        if 3 <= len(line) <= 80 and not line.replace(" ", "").isdigit() \
                and not line[0].islower() \
                and not _GENERIC_EVENT_LABEL.match(line):
            return line
    return None


def _matched_cue(ctx: str) -> "tuple[str | None, str | None]":
    """(etype, the literal matched text) for exam-type cues in context."""
    for etype, pat in _EXAM_TYPE:
        m = pat.search(ctx)
        if m:
            return etype, m.group(0).strip()
    return None, None


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
            etype, cue_text = _matched_cue(ctx + " " + cand.candidate_text)
            # title: real context title first; else the literal matched cue
            # ("Midterm Exam") — text that appears in the document.
            title = _event_title(cand) or cue_text
            exams.append(_dated_entry(cand, {"type": etype, "title": title}))
        elif label == "assignment_deadline":
            assignments.append(_dated_entry(cand, {"title": _event_title(cand)}))

    # C4 multi-section detection (B2-035/036 memos: 4 분반이 한 문서에 — 수업
    # 시간·강의실이 여러 벌). 서로 다른 라벨 값이 3개 이상이면 분반 혼합 의심 —
    # 하나를 골라 채우지 말고 needs_review로 올린다 (v4 §3 C4).
    from .rule_fields import find_labeled_values

    distinct_times = {v.strip() for v in find_labeled_values(doc, "class_time")}
    distinct_rooms = {v.strip() for v in find_labeled_values(doc, "location")}
    multi_section = len(distinct_times) >= 3 or len(distinct_rooms) >= 3

    raw_time = labeled_value(doc, "class_time", cut=False)
    if raw_time and _TBA.search(raw_time):
        status = "tba"
    elif class_events:
        status = "present"
    elif _ASYNC.search(doc.full_text):
        status = "async"
    else:
        status = "not_specified"

    # Phase 4: the weekly-plan table — the main home of exams/assignments (v6 §0).
    from .table_plan import _EXAM_CUE, parse_weekly_plan

    _EXAM_ONLY_WORDS = {"midterm", "mid", "term", "final", "exam", "exams", "quiz",
                        "week", "중간", "기말", "시험", "고사", "퀴즈"}
    # "각 주차에 어떤 챕터를 공부하는지 specify 되어 있으면 그게 가장 중요" (B4-035/037
    # 메모) — 부속 열에서는 챕터 지정 줄만 주차 내용으로 승격한다. 참조문헌·행정 줄까지
    # 합치면 사람 gold(요약 전사)와 어긋나고 내용도 잡음이 된다 (배치4 prec 36→9% 실측).
    _CHAPTER_LINE = re.compile(r"\bch(?:apter)?s?\.?\s*\d|챕터\s*\d|\d+\s*단원|\d+\s*장\b", re.I)

    def _topic_with_extras(r):
        """주차 내용 = topic + 부속 열의 챕터 지정 줄. 시험 단서 줄은 이벤트로 승격.
        시험뿐인 행('Midterm week')은 통째로 이벤트 소관 — 내용에서 제외 (B4-029)."""
        # 셀 내 개행은 대부분 시각적 wrap — 소문자로 시작하는 줄은 앞 줄의 연속
        # ("CH 1: Consumption" + "theory")
        lines: list[str] = []
        for ln in (r.extras or []):
            if lines and re.match(r"^[a-z0-9(]", ln):
                lines[-1] += " " + ln
            else:
                lines.append(ln)
        keep = [ln for ln in lines
                if _CHAPTER_LINE.search(ln) and not _EXAM_CUE.search(ln)]
        # 셀 내 줄바꿈은 시각적 개행(단어 중간 wrap)이 대부분 — 공백으로 잇는다
        tail = " ".join(keep)
        merged = f"{r.topic}, {tail}" if (r.topic and tail) else (r.topic or tail or None)
        if merged:
            words = set(re.findall(r"[a-zA-Z가-힣]+", merged.lower()))
            if words and words <= _EXAM_ONLY_WORDS:
                return None
        return merged

    plan = parse_weekly_plan(doc)
    others: list[dict] = []
    seen_keys = {(e.get("type"), e["raw_reference"]) for e in exams} | \
                {(None, a["raw_reference"]) for a in assignments}
    for ev in plan.events:
        key = (ev.get("type"), ev["raw_reference"])
        if key in seen_keys:
            continue
        entry = {k: ev[k] for k in ("title", "type", "raw_reference", "date_kind",
                                    "resolved_date", "resolved_by", "needs_review") if k in ev}
        bucket = {"exam": exams, "assignment": assignments}.get(ev["kind"], others)
        bucket.append(entry)

    return {
        "meeting.status": status,
        "meeting.events": class_events if status == "present" else [],
        "meeting.multi_section_suspect": multi_section,
        "instructors.office_hours": office_hours,
        "schedule.exams": exams,
        "schedule.assignments": assignments,
        "schedule.others": others,
        "schedule.weekly_plan": [
            {"week": r.week, "date_range": r.date_range, "topic": _topic_with_extras(r),
             "textbook_range": r.textbook_range, "remarks": r.remarks,
             "extras": r.extras,          # 원문 줄 보존 — 무기한과제 중복 억제의 대조원
             "date_labeled": r.date_labeled}
            for r in plan.rows
        ],
        "schedule.total_weeks": plan.total_weeks,
        "schedule.plan_needs_review": plan.needs_review,
        "schedule.plan_issues": plan.issues,
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
