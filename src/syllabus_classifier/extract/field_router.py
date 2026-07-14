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
# async 는 배달 방식의 **긍정 근거**가 있을 때만. OCW/KOCW 는 출처(오픈코스웨어)일 뿐
# 배달 방식이 아니다 — 이걸 넣으면 KOCW 코퍼스 전체가 async 로 오탐돼 교시표 KB 가
# 아예 호출되지 않았다(2026-07 이식 3단계에서 실측). 그래서 제거한다.
_ASYNC = re.compile(r"사이버\s*강의|온라인\s*강의|비대면|원격\s*수업|동영상\s*강의|e-?learning", re.IGNORECASE)
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


# 한 시험/과제 문장이 날짜·요일·시각 토큰마다 겹치는 후보로 쪼개져 다중 항목이 되는 것을
# 접기 위한 유틸 (2026-07 섀도 실측: "기말고사 12월14일 (화) 2:00-3:00PM" 한 줄이 시험 5개로).
_DATE_SIG = re.compile(
    r"\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}\s*[/.\-]\s*\d{1,2}|\d{1,4}\s*주\s*차?|week\s*\d+", re.I)


def _date_sig(entry: dict) -> "str | None":
    """이벤트의 날짜 서명(제목+raw 에서 첫 날짜/주차 토큰) — 같은 시험 판별용."""
    m = _DATE_SIG.search(f"{entry.get('title') or ''} {entry.get('raw_reference') or ''}")
    return re.sub(r"\s+", "", m.group(0).lower()) if m else None


def _merge_events(keep: dict, drop: dict) -> None:
    """drop 을 keep 에 흡수 — 확정 날짜는 물려받고, 더 짧고 깨끗한 이벤트명을 남긴다."""
    if not keep.get("resolved_date") and drop.get("resolved_date"):
        keep["resolved_date"] = drop["resolved_date"]
        keep["resolved_by"] = drop.get("resolved_by")
        keep["needs_review"] = drop.get("needs_review", keep.get("needs_review"))
    kt, dt = (keep.get("title") or ""), (drop.get("title") or "")
    if dt and (not kt or len(dt) < len(kt)):
        keep["title"] = dt


def _dedup_events(entries: list, *, by_date_sig: bool) -> list:
    """① 인접 조각 접기: 같은 page·type 이고 char_start 가 인접하며 뒤 조각이 새 날짜
    anchor 가 아니면(요일·시각 등 연속 세부) 한 이벤트로. ② by_date_sig 면 (type, 날짜
    서명)이 같은 것을 교차-출처(분류기·주차표)까지 병합. 위치 없는 항목은 그대로 흐른다."""
    positioned = sorted((e for e in entries if e.get("_char_start") is not None),
                        key=lambda e: (e.get("_page") or 0, e["_char_start"]))
    collapsed = [e for e in entries if e.get("_char_start") is None]
    for e in positioned:
        e = dict(e)
        e["_end"] = e["_char_start"] + len(e.get("raw_reference") or "")
        prev = collapsed[-1] if collapsed and collapsed[-1].get("_char_start") is not None else None
        if prev and e.get("_page") == prev.get("_page") and e.get("type") == prev.get("type") \
                and e["_char_start"] - prev["_end"] <= 30 \
                and (_date_sig(e) is None or _date_sig(e) == _date_sig(prev)):
            _merge_events(prev, e)
            prev["_end"] = max(prev["_end"], e["_end"])
            continue
        collapsed.append(e)
    if by_date_sig:
        out: list = []
        index: dict = {}
        for e in collapsed:
            sig = _date_sig(e)
            key = (e.get("type"), sig) if sig else None
            if key and key in index:
                _merge_events(index[key], e)
                continue
            out.append(e)
            if key:
                index[key] = e
        collapsed = out
    for e in collapsed:
        for k in ("_char_start", "_page", "_end"):
            e.pop(k, None)
    return collapsed


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
    elif class_events or raw_time:
        # 시간 근거가 있으면 present — 미해석(교시표 miss 등)은 compiler 가 needs_review 로.
        # 시간이 있는데 async 로 내려가 교시 KB 를 건너뛰던 구조 버그를 막는다.
        status = "present"
    elif _ASYNC.search(doc.full_text):
        # 시간 근거가 없고 배달 방식의 긍정 근거가 있을 때만 async.
        status = "async"
    else:
        # 근거 없음 — async 로 단정하지 않고 not_specified 로 두고 needs_review 로 표면화
        # (compiler 에서 "수업시간 미상" review 생성). 이식 3단계 사용자 지시.
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

    # 한 이벤트가 인접 후보로 쪼개진 조각을 접는다. 시험은 (type,날짜서명)으로 분류기·
    # 주차표 교차-출처까지 병합; 과제는 같은 마감이라도 서로 다른 과제일 수 있어 인접
    # 조각만 접는다(날짜서명 병합은 안 함).
    exams = _dedup_events(exams, by_date_sig=True)
    assignments = _dedup_events(assignments, by_date_sig=False)

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
        # 문서 텍스트에서 정규화한 절대 날짜의 출처 스탬프 — 컴파일러의 "근거 없는
        # 확정" 가드가 이 표기를 요구한다 (v3 §9; 전 코퍼스 스모크에서 미표기 19건)
        "resolved_by": "in_document" if resolved else None,
        "needs_review": resolved is None,
        # 조각 접기용 소스 위치 (dedup 후 제거됨)
        "_char_start": getattr(cand, "char_start", None),
        "_page": cand.page,
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
