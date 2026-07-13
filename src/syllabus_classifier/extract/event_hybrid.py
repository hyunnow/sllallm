"""Event hybrid (v6 §2): LLM reads the surface, our layer blocks fabrication.

Division of labor measured on trusted gold (v6 §2):
  - the LLM extracts what is WRITTEN: title, type, and the raw date reference
    (it was the strong surface reader: title 53/78, date 32/78);
  - our deterministic layer judges date_kind and gates resolution: an
    "absolute" date must be EVIDENCED in the document text or it is demoted to
    needs_review with no resolved date (we were the only method with
    date_kind 26-30/78 and fabrication 0 — SYL-032 must stay impossible).

The LLM is never asked for date_kind and never asked to convert references.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from .candidate_extractor import classify_date_kind
from ..normalize import normalize_date

_SYSTEM = (
    "You list the exam/assignment/presentation events written in a university "
    "syllabus (Korean or English). Return JSON {\"events\": [...]}, each event:\n"
    '  {"title": <name as written in the document>,\n'
    '   "type": "exam" | "assignment" | "other",\n'
    '   "date_raw": <the date REFERENCE exactly as the document states it — '
    'e.g. "2026-08-06", "8/6", "Week 3 Thu", "매주 금요일", "추후 공지" — or null '
    "if the document gives no date>}\n"
    "STRICT RULES: copy references as written; NEVER convert a week number to a "
    "real date; NEVER infer or invent a date that is not in the text; include "
    "undated assignments with date_raw null. Presentations (발표), quizzes and "
    'other scheduled deliverables count as events (type "other" unless they are '
    "an exam or an assignment). Do not include regular class meetings or office "
    "hours."
)


def llm_read_events(text: str, client, model: str = "gpt-4o-mini") -> list[dict]:
    """Surface reading only. Returns the raw LLM event list (unvalidated)."""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": _SYSTEM},
                  {"role": "user", "content": text[:24000]}],
        response_format={"type": "json_object"},
        temperature=0,
        timeout=60,
    )
    data = json.loads(resp.choices[0].message.content)
    events = data.get("events", [])
    return [e for e in events if isinstance(e, dict) and (e.get("title") or e.get("date_raw"))]


# --- our risk layer ---------------------------------------------------------

def _norm_loose(s: str) -> str:
    return re.sub(r"[\s|;:,.()\[\]~\-–—/]+", "", str(s or "")).lower()


def _document_absolute_dates(text: str) -> set[str]:
    """Every date literally present in the text, as ISO / MM-DD forms."""
    out: set[str] = set()
    pats = [r"\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}",
            r"(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일",
            r"\d{1,2}\s*[./-]\s*\d{1,2}(?![./-]?\d)",
            r"\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*(?:\s+\d{4})?"]
    for pat in pats:
        for m in re.finditer(pat, text, re.IGNORECASE):
            iso = normalize_date(m.group(0))
            if iso:
                out.add(iso)
            elif re.fullmatch(r"\d{1,2}\s*[./-]\s*\d{1,2}", m.group(0).strip()):
                mo, d = re.split(r"[./-]", m.group(0).strip().replace(" ", ""))
                if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
                    out.add(f"{int(mo):02d}-{int(d):02d}")
    return out


def _evidenced(iso: str, doc_dates: set[str]) -> bool:
    if iso in doc_dates:
        return True
    return len(iso) == 10 and iso[5:] in doc_dates      # "2026-08-06" vs "8/6" in text


# 범주형 rubric 라벨은 무기한과제 제목이 아니다. 배치4 gold가 경계를 그었다:
# 'Homework'(단일 산출물 관용명)는 인정, 'Individual Assignments'/'과제'/'Report'/
# 'Team project' 같은 범주·복수 라벨은 거부 — homework/hw/숙제만 통과 예외로 두고
# 전 단어가 이 셋에 속하면 드롭. ('SQL 과제', '서평 보고서'는 고유어가 있어 통과.)
_GENERIC_ASSIGN_WORDS = {
    "출석", "발표", "참여", "토론", "퀴즈", "과제", "과제물", "보고서",
    "attendance", "presentation", "presentations", "participation",
    "quiz", "quizzes", "class", "regular", "optional", "and", "or", "etc",
    "assignment", "assignments", "individual", "weekly", "team",
    "report", "reports", "project", "projects", "problem", "set", "sets",
}


# 무기한과제는 gold 자체가 'Homework' 단독을 문서마다 다르게 판정한다(B4-016/021은
# 인정, B3-005/036·B4-020은 빈칸) — 제목만으론 학습 불가. 번호/시기 접두 제네릭을
# 더 걷어내려 시도했으나 holdout에서 정답(gold-kept Homework)까지 날려 정밀도가
# 29→15로 떨어졌다(2026-07-13 실측). 그래서 배치4 경계를 그대로 둔다: 전 단어가
# rubric 집합이면 드롭, homework/hw/숙제 단독은 통과.
def _is_generic_assignment_title(title: str) -> bool:
    words = re.findall(r"[a-zA-Z가-힣]+", (title or "").lower())
    return bool(words) and all(w in _GENERIC_ASSIGN_WORDS for w in words)


def risk_gate(raw_events: list[dict], text: str) -> tuple[list[dict], list[str]]:
    """Apply date_kind + no-fabrication rules to LLM surface output.

    Returns (dated_events, undated_assignment_titles). A dated event carries the
    4-part contract fields; an absolute date that is not evidenced in the text
    is demoted (resolved stripped, needs_review) rather than trusted.
    """
    doc_dates = _document_absolute_dates(text)
    text_loose = _norm_loose(text)
    dated: list[dict] = []
    undated: list[str] = []

    for e in raw_events:
        title = str(e.get("title") or "").strip()[:80]
        etype = e.get("type") if e.get("type") in ("exam", "assignment", "other") else "other"
        date_raw = (str(e.get("date_raw")).strip() if e.get("date_raw") not in (None, "", "null") else None)

        if title and _norm_loose(title) not in text_loose:
            # a title the document never states is surface hallucination — drop.
            continue

        if not date_raw:
            # 통일 규칙 (2026-07-10 사용자 결정): 무기한 과제류 → 무기한과제 필드만,
            # 무기한 시험 → 이벤트에 null|uncertain (시험은 본질적으로 일정 이벤트),
            # 둘 다 두 곳에 중복 기재 금지.
            if etype == "assignment" and title and not _is_generic_assignment_title(title):
                undated.append(title)
            elif etype == "exam" and title:
                dated.append({
                    "title": title, "kind": "exam",
                    "raw_reference": "null", "date_kind": "uncertain",
                    "resolved_date": None, "resolved_by": None,
                    "needs_review": True,
                })
            continue

        kind = classify_date_kind(date_raw)
        resolved = None
        needs_review = True
        if kind == "absolute":
            iso = normalize_date(date_raw)
            if iso and len(iso) == 10 and _evidenced(iso, doc_dates):
                resolved, needs_review = iso, False
            elif iso and not _evidenced(iso, doc_dates):
                # LLM produced a concrete date the document never states: BLOCK
                # the resolution, keep the reference for review (SYL-032 gate).
                kind = "uncertain"
        dated.append({
            "title": title or None, "kind": "exam" if etype == "exam" else
            ("assignment" if etype == "assignment" else "other"),
            "raw_reference": date_raw, "date_kind": kind,
            "resolved_date": resolved, "resolved_by": "in_document" if resolved else None,
            "needs_review": needs_review,
        })
    return dated, undated


_NO_SESSION_MARK = re.compile(r"no\s*(?:lab|class)|수업\s*없음|실험\s*없음|휴강", re.I)


def suppress_no_session_exams(events: list[dict], weekly_rows: list[dict]) -> list[dict]:
    """무기한(null) 시험 이벤트인데 주차표에 같은 시험이 'no lab/no class' 표시와 함께
    있으면 — 시험이 아니라 '그 주간엔 수업 없음' 기간 표시다 (B4-008, B5-013: 실험
    과목의 Mid-Term(no lab)). 날짜 있는 이벤트는 건드리지 않는다."""
    blobs = [_norm_loose(" ".join(filter(None, [r.get("topic")] + list(r.get("extras") or []))))
             for r in weekly_rows
             if _NO_SESSION_MARK.search(" ".join(filter(None, [r.get("topic")] + list(r.get("extras") or []))))]
    if not blobs:
        return events
    out = []
    for e in events:
        if e.get("kind") == "exam" and e.get("raw_reference") in (None, "null"):
            k = _norm_loose(e.get("title"))
            if k and any(k in b for b in blobs):
                continue
        out.append(e)
    return out


def suppress_scheduled(undated: list[str], dated_events: list[dict],
                       weekly_rows: list[dict]) -> list[str]:
    """무기한 후보가 (i) 날짜 있는 이벤트와 같은 제목이거나 (ii) 주차표 행 안에
    등장하면 이미 일정이 있는 산출물 — 무기한과제에서 제거하고 중복도 접는다
    (B4-035/037: 주차표의 case report/problem set가 무기한으로도 중복 방출됐다)."""
    dated_keys = [_norm_loose(e.get("title")) for e in dated_events if e.get("title")]
    weekly = [_norm_loose(" ".join(filter(None, [r.get("topic")] + list(r.get("extras") or []))))
              for r in weekly_rows]
    out: list[str] = []
    seen: set[str] = set()
    for t in undated:
        k = _norm_loose(t)
        if not k or k in seen:
            continue
        seen.add(k)
        if any(k in d or d in k for d in dated_keys if d):
            continue
        if any(k in w for w in weekly if w):
            continue
        out.append(t)
    return out


def merge_events(table_events: list[dict], llm_events: list[dict]) -> list[dict]:
    """Union, table first (it carries in_document resolution); dedupe by a loose
    (title, week/date) key so the same exam isn't listed twice."""
    def key(e):
        wk = re.search(r"week\s*(\d+)|(\d+)\s*주차", str(e.get("raw_reference") or ""), re.I)
        wk = wk.group(1) or wk.group(2) if wk else None
        return (_norm_loose(e.get("title"))[:24] or None, wk or _norm_loose(e.get("raw_reference")))
    out, seen = [], set()
    for e in list(table_events) + list(llm_events):
        k = key(e)
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out


def serialize_events(events: list[dict]) -> Optional[str]:
    parts = [f"{e.get('title') or '?'} | {e.get('kind', 'other')} | "
             f"{e.get('raw_reference')} | {e.get('date_kind')}" for e in events]
    return " ; ".join(parts) or None
