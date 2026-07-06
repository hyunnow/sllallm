"""LLM extraction for free-text fields (v4 Phase 3) — section-scoped prompts.

STATUS: interface + prompt builder now; enabled in Phase 3. The field router
records `None` (method not run) for llm outputs until then, so the harness
columns exist from day one.

Design (per spec §2): never prompt on the whole document — locate the field's
section via the label dictionary, then prompt gpt-4o-mini on that slice only.
"""
from __future__ import annotations

import json
from typing import Optional

from .rule_fields import find_labeled_values

FREE_TEXT_FIELDS = [
    "content.objectives", "content.description", "content.prerequisites",
    "content.teaching_method", "content.grading", "content.textbooks",
    "content.english_syllabus", "admin.attendance_policy",
    "admin.disability_support", "admin.learning_ethics",
]

_LABEL_FOR_FIELD = {
    "content.objectives": "objectives",
    "content.description": "description",
    "content.prerequisites": "prerequisites",
    "content.teaching_method": "teaching_method",
    "content.grading": "grading",
    "content.textbooks": "textbooks",
    "content.english_syllabus": "english_syllabus",
    "admin.attendance_policy": "attendance_policy",
    "admin.disability_support": "disability_support",
    "admin.learning_ethics": "learning_ethics",
}


def section_slice(doc, field: str, max_chars: int = 1500) -> Optional[str]:
    """The text slice the LLM is allowed to see for this field (section-scoped)."""
    label_key = _LABEL_FOR_FIELD.get(field)
    if not label_key:
        return None
    vals = find_labeled_values(doc, label_key)
    if not vals:
        return None
    return "\n".join(vals)[:max_chars]


def build_field_prompt(field: str, slice_text: str) -> list[dict]:
    return [
        {"role": "system", "content": (
            "You extract one field from a Korean/English university syllabus "
            "section. Return JSON {\"value\": ...}. If the section does not "
            "actually contain the field, return {\"value\": null}. Never invent "
            "content that is not in the text."
        )},
        {"role": "user", "content": f"field: {field}\nsection:\n{slice_text}"},
    ]


def extract_llm_fields(doc, client=None, model: str = "gpt-4o-mini", enabled: bool = False) -> dict:
    """Phase 3 entry point. With enabled=False (default), returns {} so the
    harness records the llm method as not-run rather than pretending."""
    if not enabled:
        return {}
    if client is None:
        from openai import OpenAI

        client = OpenAI(timeout=45.0, max_retries=3)
    out = {}
    for field in FREE_TEXT_FIELDS:
        sl = section_slice(doc, field)
        if not sl:
            out[field] = None
            continue
        resp = client.chat.completions.create(
            model=model, messages=build_field_prompt(field, sl),
            response_format={"type": "json_object"}, temperature=0,
        )
        out[field] = json.loads(resp.choices[0].message.content).get("value")
    return out
