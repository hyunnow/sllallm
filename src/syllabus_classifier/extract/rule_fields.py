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
        n = _norm(cell)
        return bool(n) and any(n.startswith(a) and len(n) <= len(a) + 14 for a in norm_aliases)

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
_YEAR_TERM = re.compile(r"(\d{4})\s*년?[\s\-./]*([12])\s*학기")
# English evidence shapes: the year must sit NEXT TO a term word — still never a
# bare year (§3-1). "Spring 2026" / "2026 SUMMER (SCHOOL/SESSION/…)" both ways.
_EN_TERM_YEAR = re.compile(r"\b(spring|summer|fall|autumn|winter)\s*[,\s]\s*(20\d{2})\b", re.I)
_EN_YEAR_TERM = re.compile(r"\b(20\d{2})\b[^\n]{0,40}?\b(spring|summer|fall|autumn|winter)\b", re.I)
_TERM_ONLY = re.compile(r"([12])\s*학기|여름\s*(?:계절)?학기|겨울\s*(?:계절)?학기|summer|winter|spring|fall", re.IGNORECASE)
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
    return None


def extract_term(doc) -> Optional[str]:
    text = doc.full_text
    m = _YEAR_TERM.search(text)
    if m:
        return m.group(2)
    m = _TERM_ONLY.search(text)
    if m:
        s = m.group(0).lower()
        if "여름" in s or "summer" in s:
            return "summer"
        if "겨울" in s or "winter" in s:
            return "winter"
        if "spring" in s:
            return "1"
        if "fall" in s:
            return "2"
        return m.group(1)
    return None


# --- §3-2 school / campus / department -----------------------------------------


def extract_school_campus(doc) -> tuple[Optional[str], Optional[str]]:
    """School only from the dictionary; ties broken by hit count then position."""
    cfg = load_config("school_dictionary.yaml")
    text = doc.full_text
    best, best_hits, best_pos = None, 0, 10 ** 9
    best_campuses: list[str] = []
    for entry in cfg["schools"].values():
        names = [entry["canonical"]] + entry.get("aliases", [])
        hits, first = 0, 10 ** 9
        for n in names:
            for m in re.finditer(re.escape(n), text, re.IGNORECASE):
                hits += 1
                first = min(first, m.start())
        if hits and (hits > best_hits or (hits == best_hits and first < best_pos)):
            best, best_hits, best_pos = entry["canonical"], hits, first
            best_campuses = entry.get("campuses", [])
    campus = None
    if best:
        for c in best_campuses:
            if re.search(rf"{re.escape(c)}\s*캠퍼스|캠퍼스\s*[:：]?\s*{re.escape(c)}|\b{re.escape(c)}\b", text):
                campus = c
                break
    return best, campus


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


def find_course_code(text: str) -> Optional[str]:
    """First plausible course-code token in a string; None if nothing safe."""
    for pat in _CODE_SHAPES:
        for m in pat.finditer(text or ""):
            tok = m.group(0)
            if not _CODE_BLOCKLIST.match(tok.replace(" ", "")):
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
        m = re.search(r"[A-Za-z]{2,6}[-_ ]?\d{2,5}[A-Za-z0-9.\-]*|\d{4,8}", v)
        if m:
            return m.group(0).strip()
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


def extract_rule_fields(doc) -> dict:
    """One pass over a NormalizedDoc -> flat {field_path: value} for the rule method."""
    school, campus = extract_school_campus(doc)
    raw_title = labeled_value(doc, "title")
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
        "instructors.name": labeled_value(doc, "instructor"),
        "instructors.email": emails[0] if emails else None,
        "instructors.phone": phones[0] if phones else None,
        "instructors.office": labeled_value(doc, "office"),
        "meeting.location": labeled_value(doc, "location"),
        "meeting.raw_time": labeled_value(doc, "class_time", cut=False),
        "admin.attendance_policy": labeled_value(doc, "attendance_policy"),
    }
