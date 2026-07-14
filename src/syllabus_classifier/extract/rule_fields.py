"""Rule extraction for short structured fields (v4 Phase 2, minimal-but-correct).

Implements the three observed-failure rules that belong to the rule layer:
  §3-1 academic_year: only `N학년도` / `N년 M학기`-shaped evidence counts — a bare
       year is NEVER taken, which structurally excludes print/export dates.
  §3-2 school vs department: a school is confirmed only against the school
       dictionary; a department-labeled value can never become the school.
  §3-8 field bleed: values are cut at the next known field label
       ("미분적분학과벡터해석(1) 학점 3" -> title stops before "학점").

Everything is label-dictionary driven (config/label_dictionary.yaml), so new
form layouts are covered by extending config, not code.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from ..common.config import load_config

# --- label dictionary ---------------------------------------------------------


def _norm(s: str) -> str:
    return re.sub(r"[\s()/·:：]+", "", (s or "")).lower()


def _labels() -> dict[str, list[str]]:
    return load_config("label_dictionary.yaml")["labels"]


def _all_label_tokens() -> list[str]:
    toks = {a for aliases in _labels().values() for a in aliases if len(a) >= 2}
    return sorted(toks, key=len, reverse=True)


_WORD_CHAR = re.compile(r"[0-9A-Za-z가-힣]")


def cut_at_next_label(value: str, *, exclude: tuple[str, ...] = ()) -> str:
    """Truncate a value at the earliest occurrence of any OTHER field label (§3-8).

    A label only counts at a WORD BOUNDARY — "학과" inside "미분적분학과벡터해석"
    must not cut, while " 학점 3" after the title must. For ASCII labels the
    following char must also be non-letter ("Tel" must not cut "Television").
    """
    if not value:
        return value
    cut = len(value)
    for tok in _all_label_tokens():
        if tok in exclude:
            continue
        start = 1                          # never cut at position 0
        while True:
            idx = value.find(tok, start)
            if idx <= 0:
                break
            prev_ok = not _WORD_CHAR.match(value[idx - 1])
            nxt = value[idx + len(tok):idx + len(tok) + 1]
            next_ok = not (tok.isascii() and tok.isalpha() and nxt.isalpha())
            if prev_ok and next_ok:
                cut = min(cut, idx)
                break
            start = idx + 1
    return value[:cut].strip(" :：|-\t")


def _is_any_label(cell: str) -> bool:
    """True when a cell is (nearly) exactly some field's label — such a cell is a
    LABEL, never a value. Blocks label-as-value bleed in column-oriented layouts
    (UNIST: `Instructor | Office | Tel.` header row -> name must not be 'Office')."""
    n = _norm(cell)
    if not n:
        return False
    for aliases in _labels().values():
        for a in aliases:
            na = _norm(a)
            if n.startswith(na) and len(n) <= len(na) + 2:
                return True
    return False


def find_labeled_values(doc, field: str) -> list[str]:
    """All raw values for a field, located by its label.

    Looks in (a) table rows — the cell right after a label cell — and
    (b) flat text — `label: value` up to end of line.
    """
    aliases = _labels().get(field, [])
    norm_aliases = [_norm(a) for a in aliases]
    found: list[str] = []

    def is_label(cell: str) -> bool:
        # 라벨 셀은 흔히 한/영 2줄("개설학기\nYear - Semester") — 줄 단위로도 대조해야
        # 길이 제한(+14)에 안 걸린다 (B5-002 홍익/단국 그리드형)
        for line in (cell or "").splitlines():
            n = _norm(line)
            if n and any(n.startswith(a) and len(n) <= len(a) + 14 for a in norm_aliases):
                return True
        return False

    for page in doc.pages:
        for table in page.tables:
            for row in [table.header] + table.rows:
                for i, cell in enumerate(row):
                    if not is_label(cell or ""):
                        continue
                    lines = (cell or "").splitlines()
                    rest = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
                    if (len(lines) > 1 and _is_any_label(lines[0]) and rest
                            and not _is_any_label(rest)
                            and re.search(r"\d|[월화수목금토일]", rest)):
                        # 결합 셀 "강의시간\n월 12:00~13:15 / 목 14:00~15:50" (boxed): 라벨
                        # 다음 줄이 값. 콜론 분리를 쓰면 시각의 ':'(12:00)에서 잘려 망가진다
                        # ("00~13:15 …" → 월 유실). 단 이중언어 라벨 "개설학기\nYear-Semester"
                        # 의 둘째 줄(영문 라벨)은 값 아님 → 숫자/요일이 있는 값만 취한다.
                        found.append(rest)
                    else:
                        inline = re.split(r"[:：]", cell, maxsplit=1)
                        if len(inline) == 2 and inline[1].strip():
                            found.append(inline[1].strip())
                    for j in range(i + 1, len(row)):
                        v = (row[j] or "").strip()
                        if v and not _is_any_label(v):
                            found.append(v)
                            break
                        if v:          # the neighbor is itself a label -> stop;
                            break      # this layout is column-oriented, not row-oriented
        for alias in aliases:
            for m in re.finditer(
                rf"{re.escape(alias)}\s*[:：]\s*([^\n]{{1,120}})", page.text
            ):
                found.append(m.group(1).strip())
    # de-dup, keep order
    seen, out = set(), []
    for v in found:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def labeled_value(doc, field: str, *, cut: bool = True) -> Optional[str]:
    """First usable labeled value. A candidate that is itself (or cuts down to)
    another field's label is never a value — better null than wrong."""
    for v in find_labeled_values(doc, field):
        if cut:
            v = cut_at_next_label(v)
        if v and not _is_any_label(v):
            return v
    return None


# --- §3-1 academic year / term -------------------------------------------------

_HAKNYEONDO = re.compile(r"(\d{4})\s*학년도")
_YEAR_TERM = re.compile(r"(\d{4})\s*(?:학?년도?)?[\s\-./]*([12])\s*학기")
# English evidence shapes: the year must sit NEXT TO a term word — still never a
# bare year (§3-1). "Spring 2026" / "2026 SUMMER (SCHOOL/SESSION/…)" both ways.
_EN_TERM_YEAR = re.compile(r"\b(spring|summer|fall|autumn|winter)\s*[,\s]\s*(20\d{2})\b", re.I)
_EN_YEAR_TERM = re.compile(r"\b(20\d{2})\b[^\n]{0,40}?\b(spring|summer|fall|autumn|winter)\b", re.I)
_TERM_ONLY = re.compile(
    r"([12])\s*학기"
    r"|(봄|여름|가을|겨울)\s*(?:계절)?학기"
    r"|\b(spring|summer|fall|autumn|winter)\b",   # word-bounded: waterfall ≠ fall
    re.IGNORECASE)
_FULL_DATE = re.compile(r"\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}")


def extract_academic_year(doc) -> Optional[int]:
    """§3-1: only 학년도/학기-shaped years count. A bare year (e.g. inside the
    print date `2016.10.6`) is never evidence, so print dates can't win."""
    text = doc.full_text
    m = _HAKNYEONDO.search(text)
    if m:
        return int(m.group(1))
    m = _YEAR_TERM.search(text)
    if m:
        return int(m.group(1))
    m = _EN_TERM_YEAR.search(text)
    if m:
        return int(m.group(2))
    m = _EN_YEAR_TERM.search(text)
    if m and not _FULL_DATE.search(m.group(0)):
        return int(m.group(1))
    v = labeled_value(doc, "academic_year")
    if v:
        m = re.search(r"\d{4}", v)
        # a labeled value that is a full date is a print date, not a year
        if m and not _FULL_DATE.search(v):
            return int(m.group(0))
    # "개설학기 | 2026 - 5": 학기 라벨 값이 연도를 지니는 그리드형 (B5-002 홍익) —
    # 연도-코드 형태일 때만 (bare 연도 금지 원칙 유지: 라벨+형태 이중 증거)
    v = labeled_value(doc, "term")
    if v:
        m = re.search(r"\b(20\d{2})\s*[-–.]\s*\d{1,2}\b", v)
        if m and not _FULL_DATE.search(v):
            return int(m.group(1))
    return None


# 학기 canonical = 계절 (B3-007/B3-039 reviewer policy: 숫자가 아닌 계절로 표기).
# 한국어 N학기만 결정론 변환(1학기=봄, 2학기=가을 — 국내 학사 구조상 고정);
# 영어 "Semester N"류 숫자는 나라마다 계절이 반대일 수 있어 변환하지 않는다.
_SEASON = {"1": "봄", "2": "가을", "봄": "봄", "여름": "여름", "가을": "가을", "겨울": "겨울",
           "spring": "봄", "summer": "여름", "fall": "가을", "autumn": "가을", "winter": "겨울"}


def extract_term(doc) -> Optional[str]:
    text = doc.full_text
    m = _YEAR_TERM.search(text)
    if m:
        return _SEASON[m.group(2)]
    m = _TERM_ONLY.search(text)
    if m:
        key = (m.group(1) or m.group(2) or m.group(3) or "").lower()
        return _SEASON.get(key)
    # 라벨형: "개설학기 | 2026 - 5" (홍익/단국 그리드) — 코드 1/2만 계절로 변환,
    # 3+ (계절학기 코드)는 의미 미상이라 abstain (B5-002: 코드 5 → 빈칸이 정답)
    v = labeled_value(doc, "term")
    if v:
        m = re.search(r"(?:20\d{2}\s*[-–.]\s*)?([12])\s*$", v.strip())
        if m:
            return _SEASON[m.group(1)]
    return None


# --- §3-2 school / campus / department -----------------------------------------


def _dict_school_hits(text: str, cfg) -> tuple[Optional[dict], int, int]:
    """Best dictionary entry for a text surface; (entry, hits, first_pos)."""
    # macOS filenames carry NFD-decomposed hangul — NFC first or "국민대" never hits
    text = unicodedata.normalize("NFC", text or "")
    best, best_hits, best_pos = None, 0, 10 ** 9
    for entry in cfg["schools"].values():
        names = [entry["canonical"]] + entry.get("aliases", [])
        hits, first = 0, 10 ** 9
        for n in names:
            # short acronyms (KU/KNU/CAU/SNU…) only count as exact-case whole
            # words — IGNORECASE substrings hit inside "because"/"kudos"
            if re.fullmatch(r"[A-Z]{2,5}", n):
                pat = re.compile(rf"(?<![A-Za-z]){n}(?![A-Za-z])")
            else:
                pat = re.compile(re.escape(n), re.IGNORECASE)
            for m in pat.finditer(text):
                hits += 1
                first = min(first, m.start())
        if hits and (hits > best_hits or (hits == best_hits and first < best_pos)):
            best, best_hits, best_pos = entry, hits, first
    return best, best_hits, best_pos


def _school_from_email_domain(text: str, cfg) -> Optional[dict]:
    """B3-005/014/017: an institutional email domain is deterministic school
    evidence (@unist.ac.kr 도메인 → UNIST). gmail류 공용 도메인은 사전에 없어
    자연 배제; 서로 다른 학교 도메인이 섞이면 abstain."""
    doc_domains = {m.group(0).rsplit("@", 1)[1].lower() for m in _EMAIL.finditer(text)}
    return _school_from_domains(doc_domains, cfg)


_URL = re.compile(r"https?://[^\s/]+", re.IGNORECASE)


def _school_from_url_domain(text: str, cfg) -> Optional[dict]:
    """포털/아카이브 URL 호스트로 학교 확정 (ysweb.yonsei.ac.kr → 연세). 깨진 PDF 에서
    학교명이 뭉개져도 소스 URL 은 남는 경우가 많다 (이식 3단계 실측 — 연세 포털 export).
    이메일 도메인과 동일하게 서로 다른 학교가 섞이면 abstain."""
    hosts = {m.group(0).split("://", 1)[1].split(":")[0].lower() for m in _URL.finditer(text)}
    return _school_from_domains(hosts, cfg)


def _school_from_domains(hosts: "set[str]", cfg) -> Optional[dict]:
    """도메인/호스트 집합 → 유일하게 매치되는 학교 entry (없거나 복수면 None)."""
    matched = {}
    for entry in cfg["schools"].values():
        for d in entry.get("domains", []):
            if any(h == d or h.endswith("." + d) for h in hosts):
                matched[entry["canonical"]] = entry
    return next(iter(matched.values())) if len(matched) == 1 else None


_SURFACE_SCHOOL = re.compile(r"(?<![가-힣])([가-힣]{2,12}(?:대학교|과학기술원))")


def _surface_school(text: str) -> Optional[str]:
    """사전 미등재 학교의 표면형 폴백. 문서 상단(헤더)에서 첫 'X대학교'/'X과학기술원'.
    '단과대학'/'대학원'/'○○학과'는 매칭 안 됨(교 접미 필수). 상단 600자 한정으로
    본문 속 타 대학 언급(파트너·인용)을 배제한다."""
    head = unicodedata.normalize("NFC", text or "")[:600]
    m = _SURFACE_SCHOOL.search(head)
    return m.group(1) if m else None


def extract_school_campus(doc) -> tuple[Optional[str], Optional[str]]:
    """School only from the dictionary. 증거 우선순위: 본문 > 이메일 도메인 >
    포털 URL 도메인 > 수집 파일명(doc_id). 파일명 폴백은 kocw류 아카이브(파일명에
    학교가 박힌 명명 규칙, 본문엔 학교명 없음) 때문에 존재 — 2026-07-12 사용자 최종
    판정으로 유지. URL 도메인은 깨진 포털 export(학교명 뭉개짐)에서 학교 복구용."""
    cfg = load_config("school_dictionary.yaml")
    text = doc.full_text
    entry, _, _ = _dict_school_hits(text, cfg)
    if entry is None:
        entry = _school_from_email_domain(text, cfg)
    if entry is None:
        entry = _school_from_url_domain(text, cfg)          # 포털 URL 도메인 (깨진 PDF 복구)
    if entry is None:
        entry, _, _ = _dict_school_hits(getattr(doc, "doc_id", "") or "", cfg)
    if entry is None:
        # 사전에 없는 학교 일반화 (제품은 임의 한국 대학을 받는다): 문서 상단의
        # 'X대학교'/'X과학기술원' 표면형. '대학교'(교 포함)는 단과대학·학과와 달리
        # 대학교만 지칭해 모호하지 않다(§3-2 정밀도 유지). 캠퍼스/교시표 해석은
        # 사전 학교에만 있으므로 표면 학교는 무해(하류가 school 을 직접 쓰지 않음).
        surface = _surface_school(text)
        if surface:
            return surface, None
    if entry is None:
        return None, None
    campus = None
    for c in entry.get("campuses", []):
        if re.search(rf"{re.escape(c)}\s*캠퍼스|캠퍼스\s*[:：]?\s*{re.escape(c)}|\b{re.escape(c)}\b", text):
            campus = c
            break
    return entry["canonical"], campus


def extract_department(doc) -> Optional[str]:
    """Department comes ONLY from a department-labeled value (§3-2)."""
    return labeled_value(doc, "department")


# --- course code (labeled + unlabeled shapes) -----------------------------------

# Real-world code shapes observed in the corpus + user examples:
#   MTH101001 (미적분학: MTH101001) · PH301 / MSE35401 (KAIST/UNIST) ·
#   ISM4508-11 (YISS section) · TECH-UB.25.001 (NYU dotted)
_CODE_SHAPES = [
    re.compile(r"\b[A-Z]{2,5}-[A-Z]{2}\.\d+(?:\.\d+)?\b"),        # NYU: TECH-UB.25.001
    re.compile(r"\b[A-Z]{2,4}\s?\d{3,6}(?:-\d{1,3})?\b"),         # MTH101001, PH301, ISM4508-11
]
# uppercase+digit tokens that are never course codes
_CODE_BLOCKLIST = re.compile(r"^(?:COVID|SARS|H\d|ISBN|ISSN|MP\d|A\d|B\d|PC\d|IP\d)", re.I)
# a code-shaped token right after a room label is a CLASSROOM, not a course code
# (B3-033: "Classroom: EDU 306" must not become 학수번호)
_ROOM_CONTEXT = re.compile(
    r"(?:classroom|lecture\s*room|\broom|강의실|강의동|호실|장소)\s*[:：]?\s*$", re.I)


def find_course_code(text: str) -> Optional[str]:
    """First plausible course-code token in a string; None if nothing safe."""
    for pat in _CODE_SHAPES:
        for m in pat.finditer(text or ""):
            tok = m.group(0)
            if _CODE_BLOCKLIST.match(tok.replace(" ", "")):
                continue
            if _ROOM_CONTEXT.search((text or "")[max(0, m.start() - 30):m.start()]):
                continue
            return tok.replace(" ", "")
    return None


def split_code_from_title(title: str) -> tuple[str, Optional[str]]:
    """'미적분학: MTH101001' / 'PH301 Quantum Mechanics' -> (clean title, code)."""
    for pat in _CODE_SHAPES:
        m = pat.search(title or "")
        if m and not _CODE_BLOCKLIST.match(m.group(0).replace(" ", "")):
            cleaned = (title[:m.start()] + " " + title[m.end():])
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" :：()[]-–—/·,\t")
            return (cleaned or title), m.group(0).replace(" ", "")
    return title, None


def extract_course_code(doc, title_candidates: "list[str] | None" = None) -> Optional[str]:
    """Priority: 학수번호-labeled value > code embedded in the title > page-1
    header region (syllabi print the code up top). Never a blocklisted token."""
    v = labeled_value(doc, "course_code")
    if v:
        # 숫자형 코드는 분반 접미를 지닌다: "567140-1", "120845- 001" (B5-031/037)
        m = re.search(r"[A-Za-z]{2,6}[-_ ]?\d{2,5}[A-Za-z0-9.\-]*|\d{4,8}(?:\s*-\s*\d{1,3})?", v)
        if m:
            return re.sub(r"\s+", "", m.group(0))
    for t in title_candidates or []:
        code = find_course_code(t)
        if code:
            return code
    if doc.pages:
        return find_course_code(doc.pages[0].text[:500])
    return None


# --- contacts (regex-first fields) ---------------------------------------------

_OBFUSCATIONS = [
    (re.compile(r"\s*(?:\[at\]|\(at\)|＠|\s+at\s+)\s*", re.IGNORECASE), "@"),
    (re.compile(r"\s*(?:\[dot\]|\(dot\))\s*", re.IGNORECASE), "."),
]
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+82[-\s]?\d{1,2}|0\d{1,2})[-.\s)]?\d{3,4}[-.\s]?\d{4}")


def extract_emails(doc) -> list[str]:
    text = doc.full_text
    for pat, rep in _OBFUSCATIONS:
        text = pat.sub(rep, text)
    seen, out = set(), []
    for m in _EMAIL.finditer(text):
        e = m.group(0).lower().rstrip(".")
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def extract_phones(doc) -> list[str]:
    seen, out = set(), []
    for m in _PHONE.finditer(doc.full_text):
        p = re.sub(r"[.\s)]", "-", m.group(0)).strip("-")
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


# --- assembled rule pass --------------------------------------------------------


# a labeled class-time value must carry day/time/period evidence; a bare digit
# string from a mangled table (B3-038: "678") is never a class time (§3 abstain)
_TIME_EVIDENCE = re.compile(
    r"[월화수목금토일]|(?:mon|tue|wed|thu|fri|sat|sun)|\d{1,2}\s*[:시]\s*\d{0,2}|교시|am|pm", re.I)

# 라벨 없는 강의시간 폴백 (boxed 결합셀·minimal ·-라인 등 라벨이 없는 레이아웃).
# '요일+시각범위' 또는 '요일+교시' 세그먼트의 연속 run 을 표면형 그대로 잡아 to_notation
# 에 넘긴다(해석은 기존 파서 몫). 문서 상단 한정 → 주차표/시험시각 오인 방지.
_DAYTIME_SEG = (
    r"[월화수목금토일]\s*"
    r"(?:\d{1,2}:\d{2}\s*[~\-–—]\s*\d{1,2}:\d{2}"      # 월 12:00~13:15
    r"|\d{1,2}(?:\s*[,·]\s*\d{1,2})*\s*교시)")           # 월5,6교시 (bare 교시는 KB 필요·모호 → 제외)
_CLASSTIME_RUN = re.compile(rf"{_DAYTIME_SEG}(?:\s*[/,]\s*{_DAYTIME_SEG})*")
_OFFICE_CUE = re.compile(r"면담|상담|office\s*hour", re.I)


def _fallback_class_time(text: str) -> Optional[str]:
    head = text[:1000]
    for m in _CLASSTIME_RUN.finditer(head):
        # 바로 앞 문맥이 면담/상담이면 office hours — 강의시간 아님
        ctx = head[max(0, m.start() - 12):m.start()]
        if _OFFICE_CUE.search(ctx):
            continue
        return m.group(0).strip()
    return None


# --- 강의실/교수 위생 (② 약한 필드) --------------------------------------------

_PERIODCODE_ONLY = re.compile(r"P?\d{1,2}[A-Z]?\s*(?:\(\s*\d{1,2}:\d{2}[^)]*\))?|\d{1,2}", re.I)
# 결합 셀의 강의실 = 교시/요일 나열 뒤 꼬리 괄호 "(사범313)" / "(소프트102)".
# 괄호 안이 순수 시각·분(100)·요일·교시면 강의실이 아니다.
_ROOM_PAREN = re.compile(r"\(([^)]*[가-힣A-Za-z][^)]*)\)\s*$")
_ROOM_CODE = re.compile(r"^\s*(\d{2,4}-[A-Za-z]?\d{1,4}(?:\([A-Za-z]\))?)\s*$")
_TIMEISH_DAYS = re.compile(r"[월화수목금토일]|mon|tue|wed|thu|fri|sat|sun|교시|\d{1,2}:\d{2}", re.I)


def _room_from_meeting(value: str) -> Optional[str]:
    """'월2,3,4(사범313)' 같은 결합 표기에서 강의실만. 시각/분/요일뿐인 괄호는 제외."""
    m = _ROOM_PAREN.search(value or "")
    if not m:
        return None
    room = m.group(1).strip()
    if re.fullmatch(r"[\d:~\-\s]+", room) or re.fullmatch(r"\d{2,3}", room):
        return None                                  # (09:00~10:40) / (100)분 — 강의실 아님
    return room


def _clean_location(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if _PERIODCODE_ONLY.fullmatch(v):
        return None                                  # 교시 코드가 강의실 칸으로 샌 것
    if _ROOM_CODE.match(v):
        return _ROOM_CODE.match(v).group(1)          # 108-319(E), 106-T101 — 그대로
    # 결합 셀이면 꼬리 괄호의 방을 취한다 (요일·교시 나열 + (방))
    if _TIMEISH_DAYS.search(v):
        room = _room_from_meeting(v)
        return room or None
    return v


_NAME_LABEL_PREFIX = re.compile(r"^\s*(?:이름|성명|담당\s*교수|담당|교수|instructor|professor|name)\s*[:：]\s*", re.I)
_TITLE_PREFIX = re.compile(r"^\s*(?:professor|prof\.?|dr\.?|instructor)\s+", re.I)
_EMAIL_INLINE = re.compile(r"[,\s]*[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# 직위: 이름 뒤에 붙는 직함. 긴 것부터(alternation 순서 = 최장일치 보장).
_INSTRUCTOR_TITLE = (
    r"(?:산학협력중점교수|산학협력교수|명예교수|조교수|부교수|초빙교수|겸임교수|객원교수"
    r"|석좌교수|정교수|초빙강사|겸임강사|교수|교강사|교원|강사)")
# 직위가 이름 뒤에 (괄호 포함) 남은 것을 잘라낸다 — '황규 (초빙교수)'·'문경연 교수'.
_TRAIL_TITLE = re.compile(rf"\s*[\(（]?\s*{_INSTRUCTOR_TITLE}\s*(?:님)?\s*[\)）]?\s*$")
# 직위가 잘려 접두어만 남은 것 — '석미태 산학협력'·'임혜욱 겸임'.
_TRAIL_POS = re.compile(r"\s*(?:산학협력중점|산학협력|석좌|명예|초빙|겸임|객원|전임|비전임)\s*$")


def _clean_instructor(value: Optional[str]) -> Optional[str]:
    """직함·라벨 접두/접미 제거 + 괄호 안팎 이메일 제거 (B3-002/020/036, B4-006)."""
    if not value:
        return None
    v = _NAME_LABEL_PREFIX.sub("", value)
    v = _TITLE_PREFIX.sub("", v)
    v = _EMAIL_INLINE.sub("", v)                      # "(임보해, bhim@…)" → "(임보해)"
    v = re.sub(r"\(\s*\)", "", v)                     # 이메일만 있던 괄호는 빈 껍데기 → 제거
    v = _TRAIL_TITLE.sub("", v)                       # '(초빙교수)'·'부교수' 꼬리 제거
    v = _TRAIL_POS.sub("", v)                         # '산학협력'·'겸임' 잘린 직위 제거
    v = re.sub(r"\s*[\(（]\s*$", "", v)                # '위연나 (' 처럼 남은 여는 괄호
    # 뒤따르는 다른 라벨 조각 컷 ("홈페이지:" 등)은 labeled_value가 이미 처리
    v = v.strip(" ,:：\t")
    return v or None


_HEADER_INSTRUCTOR = re.compile(rf"(?:담당\s*)?([가-힣]{{2,4}})\s*{_INSTRUCTOR_TITLE}")
# form 형: '교강사 <이름> 직위 <직함>' — 이름은 교수라벨과 '직위' 사이(직위 뒤가 직함).
_NAME_BEFORE_JIKWI = re.compile(r"(?:교강사|교수자|교원|담당\s*교수|담당\s*교원|교수)\s+([가-힣]{2,4})\s+직위")
_NOT_A_NAME = re.compile(r"[과부원실팀학]$")      # 학과/학부/대학원 등 조직 꼬리는 이름 아님
_NAME_STOPWORDS = frozenset(
    "담당 책임 운영 성명 직위 이름 교수 교강사 교원 소속 전공 소속대학 개설".split())


def _header_instructor(text: str) -> Optional[str]:
    """라벨 없는 헤더형 교수 ('… 수학과 문경연 교수', '담당 은하호 부교수', form 의
    '교강사 <이름> 직위 …'). 상단 한정, 이름만. 조직명·라벨은 배제(정밀도 우선)."""
    head = text[:600]
    m = _NAME_BEFORE_JIKWI.search(head)              # '<라벨> <이름> 직위' 우선 (form)
    if m and m.group(1) not in _NAME_STOPWORDS and not _NOT_A_NAME.search(m.group(1)):
        return m.group(1)
    for m in _HEADER_INSTRUCTOR.finditer(head):
        name = m.group(1)
        if name in _NAME_STOPWORDS or _NOT_A_NAME.search(name) or _is_any_label(name):
            continue
        return name
    return None


def _clean_title(s: Optional[str]) -> Optional[str]:
    """과목명 표면 정규화: 셀 내 개행/중복 공백을 한 칸으로, 선두 불릿·마커 제거.
    포털/PDF 표에서 값이 여러 줄로 wrap 되어 '*BUSINESS\\nMANAGEMENT' 처럼 들어오는 걸
    'BUSINESS MANAGEMENT' 로 편다 (2026-07 섀도 실측)."""
    if not s:
        return s
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^[\*•▪◦·\-–—]+\s*", "", s).strip()
    s = re.sub(r"^[\(（]\s*(?:국문|영문|한글|공통|국|영)\s*[\)）]\s*", "", s).strip()   # 이중언어/공통 마커 접두
    s = re.sub(r"^\d{1,2}\.\s+(?=[A-Za-z가-힣])", "", s).strip()                    # 번호 매김 접두 'N. '
    return s or None


def _derive_titles(title: Optional[str]) -> "tuple[Optional[str], Optional[str]]":
    """정제된 제목 -> (title_ko, title_en). 개행/마커 정규화 후, 한국어+영문이 한 값에
    섞이면(컴퓨터활용기초 COMPUTER…) 영문 앞을 title_ko, 영문 run 을 title_en 으로 분리."""
    title = _clean_title(title)
    if not title:
        return None, None
    if not re.search(r"[가-힣]", title):
        return None, title
    m = re.search(r"[A-Za-z][A-Za-z0-9 ,:&()'\-]{4,}", title)
    if not m:
        return title, None
    title_en = m.group(0).strip()
    head = title[:m.start()].strip(" -–—/·|()[]")
    title_ko = head if re.search(r"[가-힣]", head) else title
    return title_ko, title_en


def _looks_like_title(v: Optional[str]) -> bool:
    """제목 후보 sanity — 타임스탬프/수정이력 메타데이터는 과목명이 아니다.
    연세 포털 export 는 '교과목명' 라벨 이웃 셀에 '최종수정일 2014-…' 가 붙어 그게
    제목으로 새던 것을 막는다 (2026-07 섀도 실측)."""
    v = (v or "").strip()
    if not (2 <= len(v) <= 60):
        return False
    return not re.search(r"최종수정일|최초등록일|\d{1,2}:\d{2}:\d{2}|\d{4}-\d{2}-\d{2}", v)


def _labeled_title(doc) -> Optional[str]:
    """제목 라벨 값 중 '제목처럼 생긴' 첫 값 — 타임스탬프/메타데이터/문서제목 셀은 건너뛴다."""
    for cand in find_labeled_values(doc, "title"):
        c = cut_at_next_label(cand)
        if c and not _is_any_label(c) and _looks_like_title(c) and not _DOCTYPE_TITLE.search(c):
            return c
    return None


# 콜론 없는 인라인 라벨 "과목 <값> 교과목번호 …" / "교과목 : <값>" (grid/plain/portal/
# mono 레이아웃). bare '과목'/'교과목'을 전역 라벨 사전에 넣으면 _all_label_tokens 를
# 오염시켜 cut_at_next_label 이 모든 값을 '과목'에서 잘라버린다 → title 경로 국한 정규식
# 으로만 처리. 줄머리 앵커라 '선수과목'/'이수과목'은 매칭 안 되고(과목 앞이 줄머리 아님),
# '교과목번호'는 라벨 뒤 공백 요구로 배제된다.
_INLINE_TITLE = re.compile(
    r"(?:^|\n)[ \t]*(?:교과목명|과목명|교과목|과목|교과명|강좌명|강의명)"
    r"[ \t]*[:：]?[ \t]+([^\n]{1,60})")

# '교과목 목표' / '교과목 개요' 같은 섹션 헤더가 '교과목 <제목>' 으로 새는 것 차단.
# 실제 과목명은 이런 단어만으로 이뤄지지 않는다 (정밀도 우선).
_SECTION_WORDS = frozenset(
    "목표 개요 소개 설명 내용 정보 요약 구성 특징 목적 평가 교재 참고 참고문헌 계획 "
    "진도 진도계획 방법 방침 안내 유의사항 비고 기타 정책 운영 상세 조회 "
    "학습목표 수업목표 강의목표 교과목표 학습개요 강의개요 교과개요 수업개요 강의내용 교과내용".split())


def _is_section_word(cand: str) -> bool:
    c = re.sub(r"[\s()/·:：]+", "", cand or "")
    return c in _SECTION_WORDS


def _inline_label_title(doc) -> Optional[str]:
    for m in _INLINE_TITLE.finditer(doc.full_text):
        cand = cut_at_next_label(m.group(1).strip())
        if (cand and not _is_any_label(cand) and not _is_section_word(cand)
                and not _DOCTYPE_TITLE.search(cand) and not _JUNK_TITLE.search(cand)
                and _looks_like_title(cand) and re.search(r"[가-힣A-Za-z]", cand)):
            return cand
    return None


# 라벨 자체가 없는 상단 헤딩형 제목 (boxed/minimal). 제목이 배너처럼 학교줄 다음에
# 단독으로 온다. 학교/문서제목/메타데이터/학과줄을 배제하고 상단 몇 줄에서 첫 '제목처럼
# 생긴' 줄을 취한다. 정밀도 우선 — 애매하면 None(→ 라벨 없으면 OpenAI 폴백).
_DOCTYPE_TITLE = re.compile(
    r"강\s*의\s*계\s*획|수\s*업\s*계\s*획|강\s*의\s*요\s*목|교수학습계획|운영\s*계획|운영\s*신청"
    r"|course\s*syllabus|course\s*plan|^\s*syllabus\s*$|진도표|강의\s*요강|상세\s*$", re.I)
_SCHOOL_LINE = re.compile(r"대학교|대학원|과학기술원|university|college", re.I)
_META_LINE = re.compile(
    r"학년도|학기|학점|이수구분|담당교수|담당교원|교강사|@|https?://"
    r"|강좌번호|학수번호|교과목?번호|\d{4}\s*[.\-/]\s*\d", re.I)
_DEPT_ONLY = re.compile(r"^\S{2,}(?:대학|대학원|학과|학부|계열|전공)$")
# 포털/웹스크랩 export 의 UI 크롬·네비·프로그램 배너·문서제목 — 라벨 없는 폴백이 이걸
# 제목으로 confident-wrong 하게 잡던 것 차단(실코퍼스 검증: 한양 302건 'Korean English
# Excel Print', 연세 YISS 프로그램 배너 등). 걸리면 None → OpenAI 폴백(fail-closed).
_JUNK_TITLE = re.compile(
    r"\b(?:print|excel|export|attach|login|logout|category|search|download|home|menu)\b"
    r"|인쇄|저장|목록|카테고리|첨부|조회|다운로드"
    r"|\bsyllabus\b|summer\s*school|winter\s*school|school\s*of\s*business|international\s*sum"
    r"|\bprogram\b|(?:cou[r]?se|class)\s+(?:information|outline|schedule)|subject\s+to\s+change"
    r"|time\s+place\s+lecturer|year\s*[-–]\s*semester|^\(?\s*course\s*\)?$"   # 헤더/라벨/조각
    r"|^[\(（]?\s*(?:spring|summer|fall|autumn|winter)\s+(?:semester\s+)?20\d{2}\s*[\)）]?\s*$"
    r"|^\(?\s*(?:국문|영문|en|ko)\s*\)?$", re.I)


# 포털/웹스크랩 export 마커 — 상단이 툴바·네비 탭 나열이라 '진짜 문서 헤더' 구조가 없다.
# 이런 문서에서 헤딩 추론은 네비 탭(Lecture·introduction…)을 제목으로 오인하므로 아예
# 끈다(→ 라벨/인라인 실패 시 OpenAI 폴백). 단어 블로클리스트로는 못 잡는 구조적 케이스.
_PORTAL_CHROME = re.compile(
    r"Korean\s+English\s+Excel|Attach\s+files?|조회를?\s*하지\s*않|조회된\s*데이터가\s*없", re.I)


def _heading_title(doc, school: Optional[str] = None) -> Optional[str]:
    text = doc.full_text
    if _PORTAL_CHROME.search(text[:400]):
        return None                                  # 포털 스크랩 — 헤딩 추론 금지(fail-closed)
    sn = _norm(school) if school else None
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for ln in lines[:8]:
        c = re.sub(r"^[\*•▪◦·\-–—=~\s]+", "", ln)
        c = re.sub(r"[=~]+\s*$", "", c).strip()
        if not (2 <= len(c) <= 40):
            continue
        if not re.search(r"[가-힣A-Za-z]", c):
            continue
        if c.count(" ") >= 6:                       # 문장/여러 필드가 한 줄
            continue
        if _DOCTYPE_TITLE.search(c) or _SCHOOL_LINE.search(c) or _META_LINE.search(c):
            continue
        if _DEPT_ONLY.match(c) or _is_any_label(c) or _is_section_word(c) or _JUNK_TITLE.search(c):
            continue
        if sn and sn in _norm(c):                    # 학교명 그 자체
            continue
        return c
    return None


_GRADE_LABEL = re.compile(
    r"(?:평가\s*및\s*성적|성적\s*평가\s*방법|평가\s*방법|성적\s*평가|평가\s*기준|평가\s*비율"
    r"|성적\s*비율|성적\s*반영|grading|evaluation|assessment|평가|성적)\s*[:：]?", re.I)
_GRADE_ITEM = re.compile(r"([가-힣A-Za-z][가-힣A-Za-z0-9()/ ]*?)\s*[:：]?\s*(\d{1,3})\s*%")
# 채점 run 확정 지표어 — 시험/과제/출석 계열만(발표·프로젝트는 수업방법 run 과 겹쳐 제외).
_GRADE_CUE = re.compile(r"중간|기말|시험|고사|퀴즈|과제|출석|참여도?|레포트|리포트|숙제")
_GRADE_STOP = re.compile(r"\n\s*\n|주차별|교재|참고문헌|수업\s*진도|선수과목|강의\s*개요|학습\s*목표")


def _extract_grading(text: str) -> Optional[dict]:
    """성적평가 비율을 규칙으로 추출 → {raw, components:[{name, weight}]}.
    평가 라벨 뒤 구간에서 '<항목> N%' 쌍을 모아 합이 ~100 이고 채점 지표어를 포함하는
    run 을 채택(수업방법 비율 run 은 배제). 구조(합100+지표어)가 강한 가드라 라벨-겹침
    필터는 쓰지 않는다(출석·중간고사 등이 타 필드 라벨과 겹쳐도 정당한 항목명)."""
    for lm in _GRADE_LABEL.finditer(text):
        region = _GRADE_STOP.split(text[lm.end(): lm.end() + 220])[0]
        items: list[dict] = []
        seen: set[str] = set()
        for m in _GRADE_ITEM.finditer(region):
            name = m.group(1).strip(" ·,/()").strip()
            w = int(m.group(2))
            if not name or len(name) > 12 or not (0 < w <= 100) or name in seen:
                continue
            seen.add(name)
            items.append({"name": name, "weight": w})
        total = sum(i["weight"] for i in items)
        if len(items) >= 2 and 95 <= total <= 105 and _GRADE_CUE.search(region):
            return {"raw": region.strip()[:150], "components": items}
    return None


def extract_rule_fields(doc) -> dict:
    """One pass over a NormalizedDoc -> flat {field_path: value} for the rule method."""
    school, campus = extract_school_campus(doc)
    # 제목 획득 캐스케이드 (정밀도 우선, 각 단계는 앞이 None 일 때만):
    #  1) 라벨 인접값(표/콜론) 2) 콜론없는 인라인 라벨 '과목 <값>' 3) 라벨 없는 상단 헤딩.
    # 라벨형이 잡히는 문서엔 2·3 이 발동하지 않아 무회귀.
    raw_title = _labeled_title(doc) or _inline_label_title(doc) or _heading_title(doc, school)
    if raw_title and _JUNK_TITLE.search(raw_title):
        raw_title = None                             # 포털 UI 크롬/배너 → fail-closed(OpenAI 폴백)
    title, title_code = split_code_from_title(raw_title) if raw_title else (None, None)
    title_ko, title_en = _derive_titles(title)
    credits_v = labeled_value(doc, "credits")
    credits = None
    if credits_v:
        m = re.search(r"\d+(?:\.\d+)?", credits_v)
        credits = float(m.group(0)) if m else None
        if credits and credits > 10:      # "학점/시수 3/3" style safety
            credits = None
    if credits is None:
        # 라벨 없는 '3학점'(minimal ·-라인·boxed 결합셀) 폴백 — 상단 한정, 강의 학점은 ≤10.
        m = re.search(r"(?<![\d.])(\d(?:\.\d)?)\s*학점", doc.full_text[:800])
        if m:
            credits = float(m.group(1))

    course_code = extract_course_code(doc, title_candidates=[raw_title] if raw_title else [])
    if not course_code:
        course_code = title_code

    emails = extract_emails(doc)
    phones = extract_phones(doc)

    raw_time = labeled_value(doc, "class_time", cut=False)
    if raw_time and not _TIME_EVIDENCE.search(raw_time):
        # 예외 (B6-002): 계절학기 문서의 bare 교시열("678")은 월~금 매일 수업의
        # 관행 표기 — 문서가 계절학기임을 스스로 밝힐 때만 raw로 남긴다 (해석은
        # resolver 몫). 정규학기 mangled 표의 bare 숫자열(B3-038)은 계속 차단.
        seasonal = re.search(
            r"계절\s*학기|하계|동계|(?:여름|겨울)\s*(?:계절)?\s*학기"
            r"|summer\s*(?:session|school|term)|winter\s*(?:session|term)",
            doc.full_text, re.IGNORECASE)
        if not (seasonal and re.fullmatch(r"[\d,.~\-\s]+", raw_time.strip())):
            raw_time = None
    if raw_time is None:
        # 라벨 인접값이 없을 때 문서 상단의 '요일+시각/교시' 표면형 폴백.
        raw_time = _fallback_class_time(doc.full_text)

    # 교시 코드(P1, 1A)나 시간범위 딸린 교시("P1(09:00~10:40)"), 1-2자리 bare 숫자는
    # 강의실이 아니다 — 시간표가 강의실 칸으로 새는 반복 오파싱 차단 (B5-007/034/038)
    location = _clean_location(labeled_value(doc, "location"))
    # 결합 셀("월2,3(사범313)")로 강의실을 못 얻으면 수업시간 문자열 꼬리 괄호에서 회수
    if location is None and raw_time:
        location = _room_from_meeting(raw_time)

    instructor = _clean_instructor(labeled_value(doc, "instructor"))
    if not instructor:
        instructor = _header_instructor(doc.full_text)

    return {
        "meta.school": school,
        "meta.campus": campus,
        "meta.department": extract_department(doc),
        "meta.academic_year": extract_academic_year(doc),
        "meta.term": extract_term(doc),
        "meta.course_code": course_code,
        "course.title_ko": title_ko,
        "course.title_en": title_en,
        "course.credits": credits,
        "course.classification": labeled_value(doc, "classification"),
        "course.target_students": labeled_value(doc, "target_students"),
        "instructors.name": instructor,
        "instructors.email": emails[0] if emails else None,
        "instructors.phone": phones[0] if phones else None,
        "instructors.office": labeled_value(doc, "office"),
        "meeting.location": location,
        "meeting.raw_time": raw_time,
        "content.grading": _extract_grading(doc.full_text),
        "admin.attendance_policy": labeled_value(doc, "attendance_policy"),
    }
