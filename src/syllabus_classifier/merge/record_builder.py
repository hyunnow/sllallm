"""Record builder (v4 §5/§6): assemble the full syllabus record from per-method
outputs, taking each field from its configured winner method, then apply the
cross-validation rules that block the observed failure classes:

  §3-2 school ≠ department — a department-marked value never survives as school
  §3-1 academic_year sanity window
  §3-4 no unsupported resolved dates — a non-absolute exam/assignment date with
       no KB resolution is stripped back to null + needs_review
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ..common.config import load_config
from ..record.schema import empty_record, instructor_entry

# which method's output feeds each field until the harness picks winners (§4).
# subsystem fields are fixed by architecture; everything else defaults to rule
# (and rule_llm / llm once Phase 3 lands).
_SUBSYSTEM_FIELDS = {
    "meeting.status", "meeting.events", "instructors.office_hours",
    "schedule.exams", "schedule.assignments", "schedule.weekly_plan",
}
_METHOD_ORDER = ("rule_llm", "rule", "llm")   # first non-null wins for non-subsystem fields


def _pick(field: str, outputs: dict[str, dict]) -> Any:
    if field in _SUBSYSTEM_FIELDS:
        return outputs.get("subsystem", {}).get(field)
    for method in _METHOD_ORDER:
        v = outputs.get(method, {}).get(field)
        if v not in (None, "", []):
            return v
    return None


def build_record(doc, outputs: dict[str, dict]) -> dict:
    rec = empty_record()
    rec["meta"]["syllabus_id"] = doc.doc_id
    rec["meta"]["source_file"] = doc.doc_id
    rec["meta"]["format"] = doc.source_format

    def take(field):
        return _pick(field, outputs)

    m = rec["meta"]
    m["school"], m["campus"] = take("meta.school"), take("meta.campus")
    m["department"] = take("meta.department")
    m["academic_year"], m["term"] = take("meta.academic_year"), take("meta.term")
    m["course_code"] = take("meta.course_code")

    c = rec["course"]
    c["title_ko"], c["title_en"] = take("course.title_ko"), take("course.title_en")
    c["credits"] = take("course.credits")
    c["classification"] = take("course.classification")
    c["target_students"] = take("course.target_students")

    inst = instructor_entry(
        name_ko=take("instructors.name"),
        email=take("instructors.email"),
        phone=take("instructors.phone"),
        office=take("instructors.office"),
        office_hours=take("instructors.office_hours") or [],
    )
    if any(v for k, v in inst.items() if k != "office_hours") or inst["office_hours"]:
        rec["instructors"].append(inst)

    mt = rec["meeting"]
    mt["location"] = take("meeting.location")
    mt["raw_time"] = take("meeting.raw_time")
    mt["status"] = take("meeting.status") or "not_specified"
    mt["events"] = take("meeting.events") or []

    ct = rec["content"]
    for f in ("objectives", "description", "prerequisites", "teaching_method", "english_syllabus"):
        ct[f] = take(f"content.{f}")
    g = take("content.grading")
    if isinstance(g, dict):
        ct["grading"] = g
    elif isinstance(g, str):
        ct["grading"]["raw"] = g
    tb = take("content.textbooks")
    if isinstance(tb, list):
        ct["textbooks"] = tb

    rec["schedule"]["exams"] = take("schedule.exams") or []
    rec["schedule"]["assignments"] = take("schedule.assignments") or []
    rec["schedule"]["weekly_plan"] = take("schedule.weekly_plan") or []

    for f in ("attendance_policy", "disability_support", "learning_ethics"):
        rec["admin"][f] = take(f"admin.{f}")

    # abstain-on-uncertain (v6 §1-2): a shifted/discontinuous plan table emits
    # nothing but must be visible as needs_review, not silently absent.
    sub = outputs.get("subsystem", {})
    if sub.get("schedule.plan_needs_review"):
        _flag(rec, "schedule.weekly_plan",
              f"plan table alignment issues: {', '.join(sub.get('schedule.plan_issues', []))}")

    _cross_validate(rec)
    return rec


# --- cross-validation (the safety net) -----------------------------------------


def _flag(rec: dict, field: str, reason: str) -> None:
    rec["needs_review"].append({"field": field, "reason": reason})


def _cross_validate(rec: dict) -> None:
    cfg = load_config("school_dictionary.yaml")
    dept_markers = cfg.get("department_markers", [])
    school = rec["meta"]["school"]

    # §3-2: a school value that looks like a department is demoted.
    if school and any(mk.lower() in school.lower() for mk in dept_markers):
        _flag(rec, "meta.school", f"school value '{school}' looks like a department")
        if not rec["meta"]["department"]:
            rec["meta"]["department"] = school
        rec["meta"]["school"] = None

    # §3-2: school and department must differ.
    dept = rec["meta"]["department"]
    if school and dept and school.strip() == dept.strip():
        _flag(rec, "meta.department", "department equals school")
        rec["meta"]["department"] = None

    # §3-1: academic year sanity window.
    year = rec["meta"]["academic_year"]
    if year is not None and not (2000 <= int(year) <= 2035):
        _flag(rec, "meta.academic_year", f"year {year} outside sane window")
        rec["meta"]["academic_year"] = None

    # §3-4: strip any resolved date that lacks absolute evidence or KB backing.
    for kind in ("exams", "assignments"):
        for entry in rec["schedule"][kind]:
            if entry.get("resolved_date") and entry.get("date_kind") != "absolute" \
                    and not entry.get("resolved_by"):
                _flag(rec, f"schedule.{kind}", f"unsupported resolved_date {entry['resolved_date']!r} stripped")
                entry["resolved_date"] = None
                entry["needs_review"] = True

    # meeting consistency: tba/async/not_specified must not carry events.
    if rec["meeting"]["status"] != "present" and rec["meeting"]["events"]:
        _flag(rec, "meeting.events", f"events present but status={rec['meeting']['status']}; cleared")
        rec["meeting"]["events"] = []
