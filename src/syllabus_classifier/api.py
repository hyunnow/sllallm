"""Stable entry point for host applications (e.g. gwatop-backend).

One call runs the full deterministic pipeline and returns both the structured
record and the 3-bucket compiled calendar, so callers never import internals.
"""
from __future__ import annotations

from typing import Any, Optional

from .compile import compile_record
from .extract.field_router import route_document
from .extract.normalize_doc import normalize_file
from .merge import build_record
from .model import load_classifier


def extract_syllabus(
    path: str,
    *,
    classifier: str = "heuristic",
    current_year: Optional[int] = None,
) -> dict[str, Any]:
    """Full extraction for one syllabus file.

    path         PDF/HWP/text file (the ORIGINAL file — pdfplumber tables are
                 load-bearing for table_plan; do not pass pre-extracted text).
    classifier   'heuristic' (pyyaml-only, no ML deps) or a trained-checkpoint
                 directory path (lazy-loads torch/transformers).
    current_year Confirmed events older than this year are demoted to
                 needs_review (product is for current/upcoming terms, v7 §0).
                 None = no past-year filter.

    Returns {"record", "compiled", "quality", "notes"}:
      record    full structured record (record/schema.py shape). compile_record
                resolves dates in place, so this is the post-resolution record.
      compiled  3-bucket calendar: {course, confirmed_events, weekly_timetable,
                needs_review_events, stats}. Every confirmed/needs_review event
                carries a "kind" in {class, exam, assignment, office_hours}.
      quality   doc.extraction_quality: ok | low | needs_ocr | failed.
      notes     doc.notes (extraction warnings; never silently dropped).
    """
    clf = load_classifier(classifier)
    doc = normalize_file(path)
    outputs = route_document(doc, classifier=clf)
    record = build_record(doc, outputs)
    compiled = compile_record(record, current_year=current_year)
    return {
        "record": record,
        "compiled": compiled,
        "quality": doc.extraction_quality,
        "notes": list(doc.notes),
    }
