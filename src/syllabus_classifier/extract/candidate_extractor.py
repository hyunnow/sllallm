"""Rule-based date/time candidate extractor (Phase 3).

Goal: RECALL. Miss nothing. A rule (not the model) pulls every plausible
date/time span out of the text; the model's job later is only to *classify*
each one. Over-extraction is fine here — the classifier and validator filter.

Each candidate carries the surrounding context (before/after window, section
title, table row/col label) that the classifier needs (classifier spec §4).
"""
from __future__ import annotations

import re
from typing import Optional

from ..common.schema import DateKind, TimeCandidate

# Order matters only for readability; all patterns are searched independently and
# overlapping spans are de-duplicated afterwards (longest span wins).
_PATTERNS: list[re.Pattern] = [
    # Korean weekday: full form 월요일(+조사 allowed), or a single weekday char
    # that is NOT part of a longer Hangul word (avoids matching 수 in "수업").
    re.compile(r"(?<![가-힣])(?:[월화수목금토일]요일|[월화수목금토일](?![가-힣]))"),
    # English weekday: Mon / Monday / Wed. word-bounded.
    re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\b", re.IGNORECASE),
    # clock time range: 22:00~23:00 / 22:00-23:00 / 14:00–15:00
    re.compile(r"\d{1,2}:\d{2}\s*[~\-–—]\s*\d{1,2}:\d{2}"),
    # single clock time: 23:59 / 14:00
    re.compile(r"\d{1,2}:\d{2}"),
    # korean hour: 오후 10시~11시 / 22시 / 오전 9시 30분
    re.compile(r"(?:오전|오후)?\s*\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?(?:\s*[~\-–—]\s*(?:오전|오후)?\s*\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?)?"),
    # AM/PM: 10:00 PM / 2 PM
    re.compile(r"\d{1,2}(?::\d{2})?\s*(?:AM|PM)", re.IGNORECASE),
    # period: 7,8교시 / 3교시 / 월 7,8교시
    re.compile(r"\d+(?:\s*,\s*\d+)*\s*교시"),
    # week: 8주차 / week 3 / 3주차
    re.compile(r"(?:\d+\s*주차)|(?:week\s*\d+)", re.IGNORECASE),
    # class ordinal: 5일차 / 1강 / 3회차
    re.compile(r"\d+\s*(?:일차|강|회차)"),
    # absolute date: 2026.10.27 / 2026-10-27 / 10월 27일 / 27th Oct
    re.compile(r"\d{4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}"),
    re.compile(r"(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(r"\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)", re.IGNORECASE),
    # month-only: 3월 / 4월 (relative/tentative)
    re.compile(r"\d{1,2}\s*월(?!\s*\d)"),
    # duration (NOT a start/end time): 50분간 / 90분
    re.compile(r"\d+\s*분(?:간)?"),
    # tentative markers: 추후 공지 / 미정 / 추후공지
    re.compile(r"추후\s*공지|미정|추후\s*안내"),
]

# --- date-kind sorter (§4) -------------------------------------------------

_RE_ABSOLUTE = re.compile(
    r"\d{4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}|(?:\d{4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일"
)
_RE_RELATIVE = re.compile(r"\d+\s*주차|week\s*\d+|\d+\s*(?:일차|강|회차)|^\s*\d{1,2}\s*월\s*$", re.IGNORECASE)
_RE_UNCERTAIN = re.compile(r"추후\s*공지|미정|추후\s*안내|또는|말\b|초순|중순|하순|경\b")
_RE_RECURRING = re.compile(r"매주|매월|매일|격주|홀수\s*주|짝수\s*주|weekly|biweekly", re.IGNORECASE)


def classify_date_kind(text: str) -> str:
    """Sort a date/time expression into one of the 4 kinds (v2 §4).

    This is a coarse, deterministic pre-sort so absolute (10월27일) and relative
    (week3) expressions never enter the same downstream pipeline. Order of checks
    reflects priority: recurring > uncertain > relative > absolute > (default) absolute.
    """
    if _RE_RECURRING.search(text):
        return DateKind.RECURRING.value
    if _RE_UNCERTAIN.search(text):
        return DateKind.UNCERTAIN.value
    if _RE_RELATIVE.search(text):
        return DateKind.RELATIVE.value
    if _RE_ABSOLUTE.search(text):
        return DateKind.ABSOLUTE.value
    # a bare clock time (22:00~23:00) is treated as absolute-within-a-recurrence;
    # default to absolute so it is kept as a concrete time.
    return DateKind.ABSOLUTE.value


def extract_candidates(
    text: str,
    *,
    section_title: Optional[str] = None,
    table_row_label: Optional[str] = None,
    table_col_label: Optional[str] = None,
    page: Optional[int] = None,
    doc_id: Optional[str] = None,
    context_window: int = 40,
) -> list[TimeCandidate]:
    """Return every date/time candidate in `text` with its local context.

    De-duplicates overlapping matches, keeping the longest span so that
    `월요일 22:00~23:00` wins over the sub-spans `월요일` and `22:00`.
    """
    spans: list[tuple[int, int]] = []
    for pat in _PATTERNS:
        for m in pat.finditer(text):
            if m.group().strip():
                spans.append((m.start(), m.end()))

    spans = _dedupe_longest(spans)

    candidates: list[TimeCandidate] = []
    for start, end in spans:
        raw = text[start:end]
        before = text[max(0, start - context_window):start].strip()
        after = text[end:end + context_window].strip()
        candidates.append(
            TimeCandidate(
                candidate_text=raw.strip(),
                nearby_text_before=before,
                nearby_text_after=after,
                section_title=section_title,
                table_row_label=table_row_label,
                table_col_label=table_col_label,
                page=page,
                doc_id=doc_id,
                char_start=start,
                char_end=end,
                raw_text=raw,
                date_kind=classify_date_kind(raw),
            )
        )
    return candidates


def extract_candidates_from_doc(doc) -> list[TimeCandidate]:
    """Extract candidates from a NormalizedDoc (Phase 1 output).

    Table cells are processed first so a candidate carries its row/col labels
    (e.g. row_label='면담시간') — the strongest classification cue. Free page
    text then fills in anything not inside a table. De-duplicated per page by
    candidate text, preferring the table-context version.
    """
    seen: dict[tuple, TimeCandidate] = {}
    for page in doc.pages:
        for table in page.tables:
            for row_label, col_label, cell_text in table.cells():
                for c in extract_candidates(
                    cell_text,
                    table_row_label=row_label or None,
                    table_col_label=col_label or None,
                    page=page.page_no,
                    doc_id=doc.doc_id,
                ):
                    seen[(page.page_no, c.candidate_text)] = c
        for c in extract_candidates(page.text, page=page.page_no, doc_id=doc.doc_id):
            key = (page.page_no, c.candidate_text)
            if key not in seen:
                seen[key] = c
    return list(seen.values())


def _dedupe_longest(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Drop any span fully contained in another; sort by position."""
    spans = sorted(set(spans), key=lambda s: (s[0], -(s[1] - s[0])))
    kept: list[tuple[int, int]] = []
    for s in spans:
        if any(s[0] >= k[0] and s[1] <= k[1] and s != k for k in kept):
            continue
        # also remove previously-kept spans now contained in s
        kept = [k for k in kept if not (k[0] >= s[0] and k[1] <= s[1] and k != s)]
        kept.append(s)
    return sorted(set(kept), key=lambda s: s[0])
