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


def _clean_instructor(value: Optional[str]) -> Optional[str]:
    """직함·라벨 접두 제거 + 괄호 안팎 이메일 제거 (B3-002/020/036, B4-006)."""
    if not value:
        return None
    v = _NAME_LABEL_PREFIX.sub("", value)
    v = _TITLE_PREFIX.sub("", v)
    v = _EMAIL_INLINE.sub("", v)                      # "(임보해, bhim@…)" → "(임보해)"
    v = re.sub(r"\(\s*\)", "", v)                     # 이메일만 있던 괄호는 빈 껍데기 → 제거
    v = re.sub(r"\s*교수(?:님)?\s*$", "", v)
    # 뒤따르는 다른 라벨 조각 컷 ("홈페이지:" 등)은 labeled_value가 이미 처리
    v = v.strip(" ,:：\t")
    return v or None


def extract_rule_fields(doc) -> dict:
    """One pass over a NormalizedDoc -> flat {field_path: value} for the rule method."""
    school, campus = extract_school_campus(doc)
    raw_title = labeled_value(doc, "title")
    if not raw_title:
        # 폴백: 콜론 없거나 값이 다음 줄인 포털/KOCW형 "교과목명 <값>" / "교과목명\n<값>"
        # (이화 '교과목명\n시스템소프트웨어', 한양 '교과목명 (영문)FLUID…'). title 전용·가드.
        m = re.search(r"교\s*과\s*목\s*명\s*(?:\((?:국문|영문)\))?\s*[:：]?[ \t]*\n?[ \t]*([^\n]{1,50})",
                      doc.full_text)
        if m:
            cand = cut_at_next_label(m.group(1).strip())
            if cand and not _is_any_label(cand) and re.search(r"[가-힣A-Za-z]", cand):
                raw_title = cand
    title, title_code = split_code_from_title(raw_title) if raw_title else (None, None)
    title_ko = title_en = None
    if title:
        if re.search(r"[가-힣]", title):
            title_ko = title
            m = re.search(r"[A-Za-z][A-Za-z0-9 ,:&()'\-]{4,}", title)
            title_en = m.group(0).strip() if m else None
        else:
            title_en = title
    credits_v = labeled_value(doc, "credits")
    credits = None
    if credits_v:
        m = re.search(r"\d+(?:\.\d+)?", credits_v)
        credits = float(m.group(0)) if m else None
        if credits and credits > 10:      # "학점/시수 3/3" style safety
            credits = None

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

    # 교시 코드(P1, 1A)나 시간범위 딸린 교시("P1(09:00~10:40)"), 1-2자리 bare 숫자는
    # 강의실이 아니다 — 시간표가 강의실 칸으로 새는 반복 오파싱 차단 (B5-007/034/038)
    location = _clean_location(labeled_value(doc, "location"))
    # 결합 셀("월2,3(사범313)")로 강의실을 못 얻으면 수업시간 문자열 꼬리 괄호에서 회수
    if location is None and raw_time:
        location = _room_from_meeting(raw_time)

    instructor = _clean_instructor(labeled_value(doc, "instructor"))

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
        "admin.attendance_policy": labeled_value(doc, "attendance_policy"),
    }
