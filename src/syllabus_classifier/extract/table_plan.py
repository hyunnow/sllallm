"""Phase 4 — weekly-plan table extractor (v6 §1).

Structure is RULE-driven: header keywords fix the column map; a numeric first
column is the fallback. The LLM is never asked to infer table structure.

The risk rule is abstain-on-uncertain (v6 §1-2): tables corrupt silently — one
shifted column misaligns every row — so on shift/discontinuity we mark
needs_review and do NOT emit weekly rows or promote events from that table.

In-table events (v6 §1-3): a row whose topic mentions exam/assignment cues is
promoted to an event with date_kind=relative (Week N). If the row carries an
explicit date (기간 column), that date resolves it as in_document (v7 §2
priority 1) — no calendar KB needed. Never a fabricated date.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..normalize import normalize_date

_WEEK_H = re.compile(r"^\s*(?:주\s*차?|week|wk|제?\s*\d*\s*주)\s*$", re.I)
_DATE_H = re.compile(r"기간|날짜|일자|date|일정", re.I)
# topic column selection is TIERED (batch-2 gold evidence: reviewers take the
# short 주제/제목 column, not the long 학습목표/상세내용 one — B2-001/010/013):
#   tier 1: explicit topic headers   tier 2: content-ish fallback
# and some headers are NEVER the topic (핵심어 B2-003, 학습목표, 방법, 추가설명).
_TOPIC_H1 = re.compile(r"주제|제목|단원|강의\s*주제|topic|subject|title", re.I)
_TOPIC_H2 = re.compile(r"수업\s*내용|강의\s*내용|학습\s*내용|내용|content", re.I)
_TOPIC_EXCLUDE = re.compile(r"핵심어|키워드|keyword|목표|objective|방법|method|평가|과제|추가\s*설명|비고", re.I)
_BOOK_H = re.compile(r"교재|범위|reading|chapter|자료", re.I)
_REMARK_H = re.compile(r"비고|remark|note|기타", re.I)

# 주차 셀은 괄호 날짜범위를 달고 다닌다: "WEEK1 (June 29 to July 2, 2026)" (B4-037
# YISS형 — 셀 내 개행은 위에서 공백으로 접힘). 괄호 접미만 허용, 그 외 텍스트는 불허.
_WEEK_CELL = re.compile(
    r"^\s*(?:제)?\s*(\d{1,2})\s*(?:주차?|週)?\s*(?:\([^)]*\))?\s*$"
    r"|^\s*week\s*(\d{1,2})\s*(?:\([^)]*\))?\s*$", re.I)
# 단어형 주차 표기(week N / N주차)만 — 단일행 프래그먼트 병합 허용의 근거가 되는
# 강한 증거 (bare 숫자 "1"은 우연 매치가 흔해 여기 못 들어온다)
_WEEK_STRONG = re.compile(
    r"^\s*(?:제\s*)?(\d{1,2})\s*(?:주차?|週)\s*(?:\([^)]*\))?\s*$"
    r"|^\s*week\s*(\d{1,2})\s*(?:\([^)]*\))?\s*$", re.I)
_DATE_LIKE = re.compile(r"\d{1,4}\s*[./\-]\s*\d{1,2}(\s*[./\-]\s*\d{1,2})?|(\d{1,2}\s*월\s*\d{1,2}\s*일)")
_FILENAMEY = re.compile(r"\.(pdf|pptx?|hwp|docx?|zip)\b|week\s*\d+\s*$", re.I)

_EXAM_CUE = re.compile(r"중간\s*고사|기말\s*고사|중간\s*시험|기말\s*시험|midterm|final\s*exam|\bexam\b|퀴즈|quiz|시험", re.I)
_ASSIGN_CUE = re.compile(r"과제|assignment|homework|레포트|리포트|report\s*due|제출|presentation|발표", re.I)
# "Mid-Term (no lab)": 시험 주간이라 수업/실험이 없다는 기간 표시지 시험 이벤트가
# 아니다 — 실험과목에서 반복 관찰 (B4-008, B5-013)
_NO_SESSION = re.compile(r"no\s*(?:lab|class)|수업\s*없음|실험\s*없음|휴강", re.I)
# 주차표 토픽의 대괄호 태그([Event]/[Workshop]/[Mentoring]/[Mini Project])와 데모데이는
# 일정성 산출물 — other 이벤트로 승격 (B5-037 gold)
_OTHER_TAG = re.compile(r"\[\s*(?:event|workshop|mentoring|mini\s*project)\s*\]|데모\s*데이", re.I)


@dataclass
class PlanRow:
    week: Optional[int]
    date_range: Optional[str] = None
    topic: Optional[str] = None
    textbook_range: Optional[str] = None
    remarks: Optional[str] = None
    extras: Optional[list] = None      # 비지정 열의 줄 단위 텍스트 (챕터·시험 단서 — B4-035/037)
    date_labeled: bool = False         # 날짜에서 합성한 주차 — 직렬화에 `Week N (날짜):` (정책 A)


@dataclass
class WeeklyPlan:
    rows: list[PlanRow] = field(default_factory=list)
    total_weeks: Optional[int] = None
    events: list[dict] = field(default_factory=list)
    needs_review: bool = False
    issues: list[str] = field(default_factory=list)


def _colmap_from_header(header: list[str]) -> Optional[dict]:
    cmap: dict = {}
    topic_tier = 99
    for i, cell in enumerate(header or []):
        c = (cell or "").strip()
        if not c:
            continue
        if "week" not in cmap and _WEEK_H.match(c):
            cmap["week"] = i
        elif "date" not in cmap and _DATE_H.search(c):
            cmap["date"] = i
        elif not _TOPIC_EXCLUDE.search(c) and _TOPIC_H1.search(c) and topic_tier > 1:
            cmap["topic"], topic_tier = i, 1
        elif not _TOPIC_EXCLUDE.search(c) and _TOPIC_H2.search(c) and topic_tier > 2:
            cmap["topic"], topic_tier = i, 2
        elif "book" not in cmap and _BOOK_H.search(c):
            cmap["book"] = i
        elif "remark" not in cmap and _REMARK_H.search(c):
            cmap["remark"] = i
    return cmap if "week" in cmap and "topic" in cmap else None


def _parse_week(cell: str) -> Optional[int]:
    m = _WEEK_CELL.match(cell or "")
    if not m:
        return None
    n = int(m.group(1) or m.group(2))
    return n if 1 <= n <= 30 else None


def _numeric_first_col(rows: list) -> Optional[dict]:
    """Headerless fallback: first column mostly week numbers -> week col 0,
    topic = the column with the most text."""
    rows = rows or []
    if len(rows) < 3:
        return None
    hits = sum(1 for r in rows if r and _parse_week(r[0] or "") is not None)
    if hits < max(3, int(0.6 * len(rows))):
        return None
    width = max(len(r) for r in rows)
    if width < 2:
        return None
    text_len = [0] * width
    for r in rows:
        for i in range(1, min(width, len(r))):
            cell = r[i] or ""
            if not _parse_week(cell):
                text_len[i] += len(cell)
    topic = max(range(1, width), key=lambda i: text_len[i])
    cmap = {"week": 0, "topic": topic}
    for i in range(1, width):
        if i != topic and any(_DATE_LIKE.search(r[i] or "") for r in rows if i < len(r)):
            cmap["date"] = i
            break
    return cmap


# --- 날짜/세션 기반 표 → 주차 부여 (정책 A, 2026-07-13 사용자 위임 결정) ----------
# 주차 열 없이 세션 날짜만 있는 표(B6-019/020)는 날짜를 달력 주(월요일 시작)로 묶어
# `Week N (날짜): 내용1 / 내용2` 로 직렬화한다. 연도는 그룹 경계 계산에만 쓰며
# (출력은 원문 날짜 그대로), 학년도를 모르면 주 경계를 확정할 수 없어 abstain.

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_EN_DATE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*(\d{1,2})\b", re.I)
_NUM_DATE = re.compile(r"(?:(\d{4})\s*[./\-])?\s*(\d{1,2})\s*[./\-]\s*(\d{1,2})\b")
_KO_DATE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def _first_md(cell: str):
    """셀의 첫 날짜를 (month, day)로 — 형식: Sep 2 / 3/11 / 2026-03-11 / 3월 11일."""
    s = cell or ""
    m = _EN_DATE.search(s)
    if m:
        return _MONTHS[m.group(1).lower()[:3]], int(m.group(2))
    m = _KO_DATE.search(s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _NUM_DATE.search(s)
    if m:
        mo, d = int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return mo, d
    return None


def _date_entries_from_table(table, year: int, first_month_ref: list) -> list:
    """표 하나에서 (월요일 서수, 원문 날짜, topic, extras) 엔트리 추출.
    first_month_ref는 문서 전체의 첫 달(해 넘김 판정용) — 표 간 공유."""
    data = list(table.rows or [])
    if not data:
        return []
    width = max((len(r) for r in data), default=0)
    if width < 2:
        return []
    best_col, best_hits = None, 0
    for i in range(width):
        nonempty = [(r[i] or "") for r in data if i < len(r) and (r[i] or "").strip()]
        hits = sum(1 for c in nonempty if _first_md(c))
        if nonempty and hits >= max(2, int(0.6 * len(nonempty))) and hits > best_hits:
            best_col, best_hits = i, hits
    if best_col is None:
        return []
    dens = [0] * width
    for r in data:
        for i in range(min(width, len(r))):
            if i != best_col:
                dens[i] += len((r[i] or "").strip())
    if not max(dens):
        return []
    topic_col = min(i for i in range(width) if dens[i] >= 0.5 * max(dens))

    import datetime as _dt
    entries = []
    for r in data:
        cell = (r[best_col] or "") if best_col < len(r) else ""
        md = _first_md(cell)
        if not md:
            continue
        mo, day = md
        if not first_month_ref:
            first_month_ref.append(mo)
        y = year + 1 if mo < first_month_ref[0] - 6 else year   # 학기가 해를 넘는 경우
        try:
            d = _dt.date(y, mo, day)
        except ValueError:
            continue
        topic = re.sub(r"\s+", " ", (r[topic_col] or "")).strip() if topic_col < len(r) else ""
        extras = []
        for i, c in enumerate(r):
            if i in (best_col, topic_col) or not (c or "").strip():
                continue
            extras.extend(ln for ln in (re.sub(r"\s+", " ", x).strip() for x in c.splitlines()) if ln)
        entries.append((d.toordinal() - d.weekday(), re.sub(r"\s+", " ", cell).strip(), topic, extras))
    return entries


def _plan_rows_from_entries(entries: list) -> list[PlanRow]:
    """(월요일 서수, 원문 날짜, topic, extras) 엔트리들 → 전역 주차 PlanRow.
    주차 번호는 달력 연속(첫 주부터 7일 간격) — 세션 없는 주(방학 등)를 건너뛰어도
    번호는 이어진다 (B6-019 gold: 감사절 휴강 주 포함 16주)."""
    if len(entries) < 3:
        return []
    mondays = sorted({e[0] for e in entries})
    first = mondays[0]
    rows: list[PlanRow] = []
    for monday in mondays:
        group = [e for e in entries if e[0] == monday]
        topics = list(dict.fromkeys(t for _, _, t, _ in group if t))   # 같은 주 중복 제거
        extras = [x for _, _, _, xs in group for x in xs]
        dates = list(dict.fromkeys(dr for _, dr, _, _ in group))
        rows.append(PlanRow(
            week=(monday - first) // 7 + 1,
            date_range="·".join(dates),
            topic=" / ".join(topics) or None,
            extras=extras or None,
            date_labeled=True,
        ))
    return rows


def _date_grouped_rows(tables: list, year: Optional[int]) -> list[PlanRow]:
    """문서의 모든 표에서 날짜 엔트리를 모아 달력 주 단위로 전역 주차를 부여
    (표가 페이지마다 쪼개져도 번호는 문서 전체 기준 — B6-020 9주)."""
    if not year:
        return []                          # 주 경계를 확정할 수 없다 — abstain
    first_month_ref: list = []
    entries: list = []
    for t in tables:
        entries.extend(_date_entries_from_table(t, year, first_month_ref))
    return _plan_rows_from_entries(entries)


def _date_grouped_text_rows(doc, year: Optional[int]) -> list[PlanRow]:
    """표 없는 산문형 일정 (B6-019: 'Schedule of Classes' 아래 'Sept. 2, & 7- 주제'
    줄들) — 일정 제목 이후의 날짜-선행 줄을 엔트리로 모아 같은 주차 부여를 적용.
    날짜 줄 사이의 이어짐 줄은 topic에 최대 2줄까지 연결."""
    if not year:
        return []
    import datetime as _dt

    def _headline_incomplete(t: str) -> bool:
        """헤드라인이 줄바꿈으로 잘렸는가 — 소문자 단어/쉼표로 끝나고 종결부호가
        없으면 다음 줄이 이어짐 ('function of the' ✓ / 'Hedge Funds' ✗)."""
        t = t.rstrip()
        if not t or t.endswith((".", "!", "?", ")")):
            return False
        last = t.split()[-1]
        return last[0].islower() or t.endswith((",", ";", "&"))

    def _looks_section_header(s: str) -> bool:
        """'The Asset Managers' 같은 짧은 TitleCase 단독 줄 — gold는 다음 세션에
        [태그]로 붙인다 (B5-034 표기, B6-019 gold)."""
        words = s.split()
        return (1 < len(words) <= 6 and not s.endswith((".", ",", ";", ":"))
                and sum(1 for w in words if w[:1].isupper()) >= max(2, len(words) - 1))

    def parse_from(start: int) -> list:
        entries: list = []
        first_month_ref: list = []
        cur = None
        pending_header = None
        dry = 0
        for ln in doc.full_text[start:].splitlines():
            s = ln.strip()
            if not s:
                continue
            if re.match(r"^[•·▪‣]\s*", s):
                continue                                  # 세션 하위 불릿 상세 — 헤드라인만 취한다 (B6-019 gold)
            md = _first_md(s[:28])
            sep = re.search(r"\s*[-–—:]\s+|[-–—:]\s*", s[2:])
            if md and sep:
                mo, day0 = md
                if not first_month_ref:
                    first_month_ref.append(mo)
                y = year + 1 if mo < first_month_ref[0] - 6 else year
                raw = s[:sep.start() + 2].strip(" ,&–—-:")
                topic = s[sep.end() + 2:].strip()
                if pending_header:
                    topic = f"[{pending_header}] {topic}".strip()
                    pending_header = None
                # 'Sept. 9, 14 & 16' — 세션이 여러 날이면 날짜별 엔트리 (주 걸침 반영)
                days = [day0] + [int(x) for x in re.findall(r"[,&]\s*(?:and\s+)?(\d{1,2})\b", raw)]
                cur = None
                for day in days:
                    try:
                        d = _dt.date(y, mo, day)
                    except ValueError:
                        continue
                    cur = [d.toordinal() - d.weekday(), raw, topic, []]
                    entries.append(cur)
                dry = 0
            elif cur is not None and _headline_incomplete(cur[2]) and len(s) > 2:
                # 잘린 헤드라인 이어붙임 — 같은 세션의 모든 날짜 엔트리에 반영
                for e in entries:
                    if e[1] == cur[1]:
                        e[2] = (e[2] + " " + s).strip()
            elif _looks_section_header(s):
                pending_header = s
            else:
                dry += 1
                if dry >= 12:                             # 일정 블록이 끝났다
                    break
        return [tuple(e) for e in entries]

    # 'schedule' 단어는 본문 곳곳에 나온다 — 헤딩 후보마다 시도해 날짜 줄이
    # 실제로 이어지는(≥3) 첫 블록을 쓴다 (B6-019: 진짜 헤딩은 문서 후반)
    for m in re.finditer(r"^.*(?:schedule|weekly\s*plan|강의\s*계획|수업\s*계획|주별|주차별).*$",
                         doc.full_text, re.IGNORECASE | re.MULTILINE):
        rows = _plan_rows_from_entries(parse_from(m.end()))
        if rows:
            return rows
    return []


def _check_alignment(rows: list[PlanRow]) -> list[str]:
    issues = []
    weeks = [r.week for r in rows if r.week is not None]
    if not weeks:
        return ["no_week_numbers"]
    if len(set(weeks)) != len(weeks):
        issues.append("duplicate_weeks")
    if weeks != sorted(weeks):
        issues.append("weeks_not_monotonic")
    expected = list(range(min(weeks), min(weeks) + len(weeks)))
    if sorted(set(weeks)) != expected:
        issues.append("week_gap")
    # shift: topic cells that are dates/filenames in 2+ rows (SYL-031)
    shifty = sum(1 for r in rows if r.topic and (_DATE_LIKE.fullmatch(r.topic.strip())
                                                 or _FILENAMEY.search(r.topic)))
    if shifty >= 2:
        issues.append("column_shift")
    # every week carrying the IDENTICAL topic is a stray neighboring cell sucked
    # into all rows, not a plan (B3-004: 15 weeks of "선택") — zero information
    topics = {(r.topic or "").strip() for r in rows if (r.topic or "").strip()}
    if len(weeks) >= 5 and len(topics) == 1:
        issues.append("uniform_topic")
    return issues


def _row_date(date_cell: Optional[str]) -> Optional[str]:
    """Normalize a plan-row date (start of range) to ISO if a full date exists."""
    if not date_cell:
        return None
    first = re.split(r"[~〜–—]|부터", date_cell)[0].strip()
    return normalize_date(first)


def _events_from_rows(rows: list[PlanRow]) -> list[dict]:
    events = []
    for r in rows:
        if r.week is None:
            continue
        resolved = _row_date(r.date_range)
        full = resolved is not None and len(resolved) == 10
        # 단서 소스: topic+remarks 블롭(기존) + extras 줄 각각 — YISS형은 시험이
        # 별도 열에 산다 ("Midterm"/"Final Exam" 단독 셀, B4-037)
        sources = []
        if r.topic:
            sources.append((r.topic.strip()[:80], f"{r.topic} {r.remarks or ''}"))
        sources += [(ln[:80], ln) for ln in (r.extras or [])]
        seen_kinds = set()
        for title, blob in sources:
            if _NO_SESSION.search(blob):
                continue                    # 시험 주간 표시("Mid-Term (no lab)") ≠ 시험
            is_exam = _EXAM_CUE.search(blob)
            is_assign = _ASSIGN_CUE.search(blob)
            is_other = _OTHER_TAG.search(blob)
            if is_other and not is_exam:
                events.append({
                    "title": title, "type": None, "kind": "other",
                    "raw_reference": f"Week {r.week}", "date_kind": "relative",
                    "resolved_date": resolved if full else None,
                    "resolved_by": "in_document" if full else None,
                    "needs_review": not full,
                })
                continue
            if not (is_exam or is_assign):
                continue
            # 혼합 단서("Homework & Quiz")는 assignment — 시험 오탐이 더 해롭다 (§3-9)
            kind = "assignment" if is_assign else "exam"
            etype = None if kind == "assignment" else \
                    ("midterm" if re.search(r"중간|midterm", blob, re.I)
                     else "final" if re.search(r"기말|final", blob, re.I)
                     else ("quiz" if re.search(r"퀴즈|quiz", blob, re.I) else None))
            if (kind, etype) in seen_kinds:            # 같은 주에 같은 종류는 한 번
                continue
            seen_kinds.add((kind, etype))
            events.append({
                "title": title,
                "type": etype,
                "kind": kind,
                "raw_reference": f"Week {r.week}",
                "date_kind": "relative",
                "resolved_date": resolved if full else None,
                "resolved_by": "in_document" if full else None,   # v7 §2 priority 1
                "needs_review": not full,
            })
    return events


def _repair_topic_col(cmap: dict, data_rows: list) -> dict:
    """헤더가 가리키는 topic 열이 주차 행에서 대부분 비어 있으면(헤더-데이터 열
    어긋남, pdfplumber 고스트 열 — B4-035) 텍스트 밀도가 가장 높은 열로 재선정."""
    wcol = cmap["week"]
    wrows = [r for r in data_rows
             if wcol < len(r) and _parse_week(re.sub(r"\s+", " ", r[wcol] or ""))]
    if not wrows:
        return cmap
    t = cmap.get("topic")
    filled = sum(1 for r in wrows if t is not None and t < len(r) and (r[t] or "").strip())
    if filled >= max(1, int(0.4 * len(wrows))):
        return cmap
    width = max(len(r) for r in wrows)
    dens = [0] * width
    for r in wrows:
        for i in range(min(width, len(r))):
            if i in (wcol, cmap.get("date")):
                continue
            dens[i] += len((r[i] or "").strip())
    peak = max(dens)
    if not peak:
        return cmap
    # 읽기 순서상 본문(CONTENTS)은 부속 열(ASSIGNMENTS 등)보다 왼쪽 — 최고 밀도의
    # 절반 이상인 열 중 가장 왼쪽을 topic으로 (B4-035: 참고문헌이 더 길어도 본문 우선)
    best = min(i for i in range(width) if dens[i] >= 0.5 * peak)
    return {**cmap, "topic": best}


def _week_strong_cmap(rows: list) -> Optional[dict]:
    """단어형 주차 셀("WEEK 6", "3주차")이 있으면 헤더 없이도, 행이 하나뿐이어도
    주차 표로 인정 — 페이지 분할로 홀로 남은 마지막 주가 헤더로 오분류되면 표
    전체가 증발한다 (B4-037 WEEK6 단독 표). topic은 _repair_topic_col이 채운다."""
    from collections import Counter

    hits = [ci for r in rows for ci, c in enumerate(r)
            if _WEEK_STRONG.match(re.sub(r"\s+", " ", c or ""))]
    if not hits:
        return None
    return {"week": Counter(hits).most_common(1)[0][0]}


def _rows_from_table(table) -> list[PlanRow]:
    data = list(table.rows or [])
    hdr = list(table.header or [])
    # pdfplumber는 첫 행을 header로 승격한다 — 그 행이 주차 데이터 행이면 되돌린다
    if hdr and any(_WEEK_STRONG.match(re.sub(r"\s+", " ", c or "")) for c in hdr):
        data, hdr = [hdr] + data, []
    cmap = _colmap_from_header(hdr) or _numeric_first_col(data) or _week_strong_cmap(data)
    if not cmap:
        return []
    cmap = _repair_topic_col(cmap, data)
    rows = []
    known = set(cmap.values())
    strong = 0
    for raw in data:
        def cell(key):
            i = cmap.get(key)
            if i is None or i >= len(raw):
                return None
            # PDF cells wrap mid-word — collapse internal whitespace
            return re.sub(r"\s+", " ", raw[i] or "").strip() or None
        week = _parse_week(cell("week") or "")
        if week is None and not (cell("topic") or "").strip():
            continue
        if week is not None and _WEEK_STRONG.match(cell("week") or ""):
            strong += 1
        # 지정 밖 열의 텍스트는 줄 단위로 보존 — 챕터/시험 단서가 산다 (B4-035/037:
        # ASSIGNMENTS 열 "CH 1: Consumption theory\nProblem set", 마지막 열 "Midterm")
        extras = []
        for i, c in enumerate(raw):
            if i in known or not (c or "").strip():
                continue
            for line in (c or "").splitlines():
                line = re.sub(r"\s+", " ", line).strip()
                if line and not _parse_week(line):
                    extras.append(line)
        rows.append(PlanRow(week=week, date_range=cell("date"), topic=cell("topic"),
                            textbook_range=cell("book"), remarks=cell("remark"),
                            extras=extras or None))
    rows = [r for r in rows if r.week is not None or r.topic]
    n_week = len([r for r in rows if r.week is not None])
    # 프래그먼트 인정: 주차 행 2개 이상, 또는 단어형 주차("WEEK 6")가 있는 단일 행 —
    # 페이지 분할로 마지막 주가 홀로 남는 표를 버리면 뒷주차가 통째로 증발한다 (B4-037)
    return rows if (n_week >= 2 or (n_week >= 1 and strong >= 1)) else []


def _plan_from_rows(rows: list[PlanRow], allow_boundary_gap: bool = False) -> WeeklyPlan:
    issues = _check_alignment(rows)
    plan = WeeklyPlan(rows=rows, issues=issues)
    if issues == ["uniform_topic"]:
        # topics are a stray repeated cell (B3-004) but the week NUMBERING is
        # intact — abstain on contents only, keep the week count
        plan.needs_review = True
        plan.rows = []
        plan.total_weeks = max(r.week for r in rows if r.week is not None)
    elif issues == ["week_gap"] and allow_boundary_gap:
        # 갭이 프래그먼트 경계에만 있고 각 프래그먼트 내부는 연속 — 정렬 붕괴가
        # 아니라 페이지 경계에서 행이 유실된 것 (B4-037: week 5 행이 어느 표에도
        # 없음). 검증된 행은 내고 플래그만 남긴다. 단일 표 내부 갭은 인접 셀
        # 오염(흡수·병합) 위험이라 기존대로 전체 abstain.
        plan.needs_review = True
        weeks = [r.week for r in rows if r.week is not None]
        plan.total_weeks = max(weeks)
        plan.events = _events_from_rows(rows)
    elif issues:
        # abstain-on-uncertain: corrupted alignment must not emit values
        plan.needs_review = True
        plan.rows = []
        plan.total_weeks = None
    else:
        weeks = [r.week for r in rows if r.week is not None]
        plan.total_weeks = max(weeks)
        plan.events = _events_from_rows(rows)
    return plan


def parse_weekly_plan(doc) -> WeeklyPlan:
    """Find and parse the weekly-plan table(s) of a NormalizedDoc.

    A plan often SPANS PAGES as several tables (weeks 1-13 + 14-16). Fragments
    with disjoint week sets are merged before the alignment checks — taking only
    the biggest fragment silently drops the final weeks (the SYL-022 15-vs-16
    failure, reproduced on B2-002)."""
    fragments: list[list[PlanRow]] = []
    for page in doc.pages:
        for table in page.tables:
            rows = _rows_from_table(table)
            if rows:
                fragments.append(rows)
    synthesized = False
    if not fragments:
        # 주차 열이 전혀 없으면 날짜/세션 기반 표에 주차를 부여해 본다 (정책 A) —
        # 전 표를 한 번에 묶어 전역 주차 번호 (표가 페이지로 쪼개져도 이어진다).
        # 표가 아예 없으면 산문형 일정 줄(B6-019)에 같은 규칙을 적용.
        from .rule_fields import extract_academic_year

        year = extract_academic_year(doc)
        rows = _date_grouped_rows([t for p in doc.pages for t in p.tables], year) \
            or _date_grouped_text_rows(doc, year)
        if rows:
            fragments.append(rows)
            synthesized = True             # 달력 공백 주(방학)의 번호 건너뜀은 실제 — 갭 허용
    if not fragments:
        return WeeklyPlan()

    # merge fragments whose week sets don't overlap (page-split plans)
    fragments.sort(key=lambda rs: min((r.week for r in rs if r.week is not None), default=99))
    merged: list[PlanRow] = []
    seen_weeks: set[int] = set()
    for rs in fragments:
        weeks = {r.week for r in rs if r.week is not None}
        if weeks and not (weeks & seen_weeks):
            merged.extend(rs)
            seen_weeks |= weeks

    def _contiguous(rs: list[PlanRow]) -> bool:
        ws = sorted({r.week for r in rs if r.week is not None})
        return not ws or ws == list(range(ws[0], ws[0] + len(ws)))

    # 병합 후보만 경계 갭을 허용 — 모든 프래그먼트가 내부 연속이거나, 날짜 합성
    # 주차(공백 주 번호 건너뜀이 날짜로 검증됨)일 때
    allow_merged = all(_contiguous(rs) for rs in fragments) or synthesized
    candidates = [(merged, allow_merged)] + \
                 [(rs, synthesized) for rs in sorted(fragments, key=len, reverse=True)]

    first: Optional[WeeklyPlan] = None
    for rows, allow_gap in candidates:
        plan = _plan_from_rows(rows, allow_boundary_gap=allow_gap)
        first = first or plan
        # 경계 갭만 있는 병합본이 "깨끗한 부분집합"에 지면 마지막 주가 증발한다
        # (SYL-022 재발 방지) — 행을 방출한 후보면 갭 플래그가 있어도 승리.
        if plan.rows and (not plan.needs_review or plan.issues == ["week_gap"]):
            return plan
    return first or WeeklyPlan()
