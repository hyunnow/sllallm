"""Build the candidate-level training dataset (Phase 4).

Phase 2 labeled each candidate directly (LLM draft + human review), so a training
example is just "(candidate + context) -> gold label". This module turns the
label-review rows into clean training rows and reports the class distribution
(spec Phase 4) so severe imbalance surfaces early.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from ..common.schema import ALL_LABELS, include_in_class_schedule

# how the encoder sees each example (mirrors config/train.yaml input_format)
def compose_input(row: dict) -> str:
    section = row.get("section_title") or ""
    row_label = row.get("table_row_label") or ""
    col_label = row.get("table_col_label") or ""
    where = " / ".join(x for x in (section, row_label, col_label) if x)
    nearby = " ".join(x for x in (row.get("nearby_text_before") or "", row.get("nearby_text_after") or "") if x)
    return f"{row.get('candidate_text','')} [SEP] {where} [SEP] {nearby}".strip()


def gold_label(row: dict) -> str | None:
    """Prefer the human-corrected label; fall back to the LLM draft. None if unusable."""
    lab = (row.get("corrected_label") or "").strip() or (row.get("predicted_label") or "").strip()
    return lab if lab in ALL_LABELS else None


def build_dataset_from_labels(label_rows: list[dict]) -> list[dict]:
    """Turn Phase 2 label-review rows into training examples.

    Each example carries the composed input text, the raw context fields (so the
    features can be recomputed), the gold label, the derived
    include_in_class_schedule flag, and doc_id (the leakage-safe split key).
    Rows without a valid label are dropped and counted by the caller.
    """
    out = []
    for r in label_rows:
        label = gold_label(r)
        if label is None:
            continue
        out.append({
            "doc_id": r.get("doc_id"),
            "input_text": compose_input(r),
            "candidate_text": r.get("candidate_text"),
            "section_title": r.get("section_title"),
            "table_row_label": r.get("table_row_label"),
            "table_col_label": r.get("table_col_label"),
            "nearby_text_before": r.get("nearby_text_before"),
            "nearby_text_after": r.get("nearby_text_after"),
            "date_kind": r.get("date_kind"),
            "label": label,
            "include_in_class_schedule": include_in_class_schedule(label),
            "source": "human" if (r.get("corrected_label") or "").strip() else "llm_draft",
        })
    return out


def class_distribution(rows: list[dict], label_key: str = "label") -> dict[str, int]:
    """Report label counts — call this and log it (spec Phase 4)."""
    return dict(Counter(r[label_key] for r in rows))
