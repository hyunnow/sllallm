"""LLM-assisted labeling + human review (Phase 2).

Since no gold labels exist yet, Phase 2 drafts labels with an LLM (OpenAI key is
available) and puts them in front of a human to correct. Only the
class_schedule / office_hours distinction must be perfectly reviewed — a
mislabel there teaches the model the exact error we are trying to kill
(spec Phase 2).

Implemented here: the labeling prompt builder and the human-review export
(deterministic, no network). The OpenAI call is wired but guarded so the module
imports without the SDK/key present.
"""
from __future__ import annotations

import csv
import json
from typing import Iterable, Optional

from ..common.schema import ALL_LABELS, TimeCandidate

_SYSTEM = (
    "You label date/time candidates extracted from Korean/English university "
    "syllabi. For each candidate, choose exactly one label from this set:\n"
    f"{', '.join(ALL_LABELS)}.\n"
    "Rule that matters most: a time under an office-hours / 면담 / 상담 / "
    "Office Hours / 연구실 context is NEVER class_schedule. When unsure, prefer "
    "'unknown' over class_schedule. Return JSON: "
    '{"classified_as": <label>, "include_in_class_schedule": <bool>, '
    '"confidence": <0..1>, "evidence": <short quote>}.'
)


def build_labeling_prompt(candidate: TimeCandidate) -> list[dict]:
    """Build the chat messages for drafting one candidate's label."""
    user = (
        f"candidate_text: {candidate.candidate_text}\n"
        f"section_title: {candidate.section_title}\n"
        f"table_row_label: {candidate.table_row_label}\n"
        f"nearby_before: {candidate.nearby_text_before}\n"
        f"nearby_after: {candidate.nearby_text_after}\n"
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


def _candidate_lines(candidate: TimeCandidate, idx: int) -> str:
    def clip(s, n=120):
        s = (s or "").replace("\n", " ").strip()
        return s[:n]

    return (
        f"[{idx}] candidate_text: {clip(candidate.candidate_text, 60)}\n"
        f"    section_title: {clip(candidate.section_title)}\n"
        f"    table_row_label: {clip(candidate.table_row_label)}\n"
        f"    table_col_label: {clip(candidate.table_col_label)}\n"
        f"    nearby_before: {clip(candidate.nearby_text_before)}\n"
        f"    nearby_after: {clip(candidate.nearby_text_after)}"
    )


def build_batch_prompt(candidates: list[TimeCandidate]) -> list[dict]:
    """One prompt labeling many candidates at once (cheaper than one call each)."""
    body = "\n".join(_candidate_lines(c, i) for i, c in enumerate(candidates))
    user = (
        "Label EACH candidate below. Return a JSON object of the form "
        '{"labels": [{"index": <int>, "classified_as": <label>, '
        '"include_in_class_schedule": <bool>, "confidence": <0..1>, '
        '"evidence": <short quote from the context>}]} with exactly one entry per index.\n\n'
        + body
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


def draft_labels_batch(
    candidates: list[TimeCandidate], model: str = "gpt-4o-mini", client=None, temperature: float = 0.1
) -> list[dict]:
    """Draft labels for a batch of candidates in a single API call. Returns a list
    aligned to `candidates` (index i -> label dict, or {} if the model omitted it)."""
    if not candidates:
        return []
    if client is None:
        from openai import OpenAI

        client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        messages=build_batch_prompt(candidates),
        response_format={"type": "json_object"},
        temperature=temperature,
    )
    data = json.loads(resp.choices[0].message.content)
    by_index = {item.get("index"): item for item in data.get("labels", [])}
    return [by_index.get(i, {}) for i in range(len(candidates))]


def draft_label_with_openai(candidate: TimeCandidate, model: str = "gpt-4o-mini") -> dict:
    """Call OpenAI to draft one label. Requires OPENAI_API_KEY and the openai SDK."""
    try:
        from openai import OpenAI
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("pip install openai to use LLM-assisted labeling") from e

    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        messages=build_labeling_prompt(candidate),
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content)


def export_for_review(
    rows: Iterable[dict], path: str, fmt: str = "csv"
) -> None:
    """Write drafted labels to a file a human can quickly correct.

    Each row: candidate_text, context, predicted label + evidence, and an empty
    `corrected_label` column for the reviewer to fill (spec Phase 2).
    """
    rows = list(rows)
    fields = [
        "doc_id", "candidate_text", "section_title", "table_row_label",
        "nearby_text_before", "nearby_text_after",
        "predicted_label", "include_in_class_schedule", "confidence", "evidence",
        "corrected_label",
    ]
    if fmt == "jsonl":
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({k: r.get(k) for k in fields}, ensure_ascii=False) + "\n")
        return
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
