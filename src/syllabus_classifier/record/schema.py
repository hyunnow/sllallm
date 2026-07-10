"""Full syllabus record schema (v4 §1) — the single target every extractor
fills and the method harness scores against.

Contract inherited from v1/v2: a field with no evidence is null (never
invented); an uncertain field carries needs_review. The time/exam/assignment
subsystem (the v1 classifier + KB + validator) fills meeting.events,
schedule.exams, schedule.assignments and instructors[].office_hours.
"""
from __future__ import annotations

import copy
from typing import Any

_EMPTY: dict[str, Any] = {
    "meta": {
        "syllabus_id": None,
        "source_file": None,
        "format": None,            # pdf | image | hwp
        "school": None,            # never a department (§3-2)
        "campus": None,            # period timetables differ per campus (§3-3)
        "department": None,
        "academic_year": None,     # 학년도 — never the print/export date (§3-1)
        "term": None,              # 봄 | 여름 | 가을 | 겨울 (계절 canonical, B3-039)
        "course_code": None,
    },
    "course": {
        "title_ko": None,
        "title_en": None,
        "credits": None,
        "classification": None,
        "target_students": None,
        "keywords": [],
    },
    "instructors": [],             # [{name_ko,name_en,affiliation,office,phone,email,office_hours,bio}]
    "tas": [],                     # [{name,office,phone,email}]
    "meeting": {
        "location": None,
        "raw_time": None,          # original text, e.g. "화5,6,수7(수8)"
        "status": "not_specified", # present | tba | async | not_specified
        "events": [],              # subsystem output
    },
    "content": {
        "objectives": None,
        "description": None,
        "prerequisites": None,
        "teaching_method": None,
        "grading": {"raw": None, "components": []},
        "textbooks": [],
        "english_syllabus": None,
    },
    "schedule": {
        "weekly_plan": [],
        "exams": [],
        "assignments": [],
    },
    "admin": {
        "attendance_policy": None,
        "disability_support": None,
        "learning_ethics": None,
    },
    "needs_review": [],            # [{field, reason}]
}


def empty_record() -> dict:
    return copy.deepcopy(_EMPTY)


def instructor_entry(**kw) -> dict:
    base = {"name_ko": None, "name_en": None, "affiliation": None, "office": None,
            "phone": None, "email": None, "office_hours": [], "bio": None}
    base.update(kw)
    return base


# Fields the method harness compares (doc × field × method → output vs gold).
# eval kind drives the per-field metric (§4): exact | fuzzy | risk.
HARNESS_FIELDS: dict[str, dict] = {
    "meta.school":            {"eval": "exact"},
    "meta.campus":            {"eval": "exact"},
    "meta.department":        {"eval": "exact"},
    "meta.academic_year":     {"eval": "exact"},
    "meta.term":              {"eval": "exact"},
    "meta.course_code":       {"eval": "exact"},
    "course.title_ko":        {"eval": "fuzzy"},
    "course.title_en":        {"eval": "fuzzy"},
    "course.credits":         {"eval": "exact"},
    "course.classification":  {"eval": "exact"},
    "course.target_students": {"eval": "fuzzy"},
    "instructors.name":       {"eval": "exact"},
    "instructors.email":      {"eval": "exact"},
    "instructors.phone":      {"eval": "exact"},
    "instructors.office":     {"eval": "fuzzy"},
    "instructors.office_hours": {"eval": "risk"},
    "meeting.location":       {"eval": "fuzzy"},
    "meeting.raw_time":       {"eval": "exact"},
    "meeting.status":         {"eval": "exact"},
    "content.objectives":     {"eval": "fuzzy"},
    "content.description":    {"eval": "fuzzy"},
    "content.prerequisites":  {"eval": "fuzzy"},
    "content.teaching_method": {"eval": "fuzzy"},
    "content.grading":        {"eval": "fuzzy"},
    "content.textbooks":      {"eval": "fuzzy"},
    "schedule.weekly_plan":   {"eval": "fuzzy"},
    "schedule.exams":         {"eval": "risk"},   # hallucination 0 (§3-4)
    "schedule.assignments":   {"eval": "risk"},
    "admin.attendance_policy": {"eval": "fuzzy"},
}


def get_path(record: dict, dotted: str):
    """Read a dotted field path; 'instructors.email' means first instructor."""
    cur: Any = record
    for part in dotted.split("."):
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if cur is None:
            return None
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur
