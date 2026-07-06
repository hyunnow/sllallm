"""End-to-end inference: a normalized document -> final per-document JSON.

Ties the pieces together (spec §3 architecture): extract every candidate ->
classify each (any Classifier: heuristic baseline or trained encoder) -> rule
validator safety net -> assemble the Phase 9 / v2 §6 output. The classifier is
injected, so the same pipeline runs with `HeuristicClassifier` today and
`EncoderClassifier` once a model is trained — nothing else changes.
"""
from __future__ import annotations

from .extract import extract_candidates_from_doc
from .validator import assemble_document_output, validate_candidate


def run_pipeline(doc, classifier) -> dict:
    """Run extract -> classify -> validate -> assemble for one NormalizedDoc."""
    validated = []
    for cand in extract_candidates_from_doc(doc):
        cls, rejection = validate_candidate(cand, classifier.predict(cand))
        validated.append((cand, cls, rejection))
    return assemble_document_output(doc.doc_id, validated)
