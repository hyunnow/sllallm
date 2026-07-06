"""Surface augmentation (Phase 5-A). Meaning (the label) is preserved; only the
surface text changes, so 1 real candidate becomes many training rows.

All randomness flows through a caller-supplied `random.Random` so runs are
reproducible (spec: fixed seeds). Probabilities come from config/noise.yaml.

Phase 5-B (reverse synthesis: canonical -> fake doc -> noise -> re-extract) is a
larger generator that lands once canonical JSON exists; its entry point is
stubbed at the bottom.
"""
from __future__ import annotations

import random
from dataclasses import replace
from typing import Optional

from ..common.schema import TimeCandidate

# OCR confusion pairs (both directions applied) — Latin + a few 한글 자모 look-alikes
_OCR_CONFUSION = {
    "0": "O", "O": "0", "1": "l", "l": "1", "5": "S", "S": "5",
    "8": "B", "B": "8", "2": "Z", "Z": "2",
}

# label-expression synonyms — swapping these keeps the class identical
_LABEL_SYNONYMS = [
    ["면담시간", "상담시간", "Office Hours", "오피스아워", "office hour"],
    ["연구실 및 면담시간", "Office Location&Hours", "상담 시간", "면담 시간"],
    ["수업시간", "강의시간", "class time", "정규 수업시간"],
    ["과제 제출", "과제 마감", "assignment due", "제출 기한"],
]

# time-format equivalents (same instant, different surface)
_TIME_FORMAT_VARIANTS = [
    ["22:00~23:00", "22:00-23:00", "오후 10시~11시", "22시~23시", "10:00 PM~11:00 PM"],
    ["15:00~16:00", "15:00-16:00", "오후 3시~4시", "15시~16시"],
    ["09:00~09:50", "9:00-9:50", "오전 9시~9시 50분", "1교시"],
]


def _apply_ocr_confusion(text: str, prob: float, rng: random.Random) -> str:
    return "".join(
        _OCR_CONFUSION[c] if (c in _OCR_CONFUSION and rng.random() < prob) else c
        for c in text
    )


def _apply_char_drop_insert(text: str, prob: float, rng: random.Random) -> str:
    out = []
    for c in text:
        r = rng.random()
        if r < prob / 2:
            continue  # drop
        out.append(c)
        if prob / 2 <= r < prob:
            out.append(c)  # duplicate/insert
    return "".join(out)


def _swap_synonyms(text: str, prob: float, rng: random.Random) -> str:
    for group in _LABEL_SYNONYMS:
        for term in group:
            if term in text and rng.random() < prob:
                alt = rng.choice([t for t in group if t != term])
                text = text.replace(term, alt)
                break
    return text


def _swap_time_format(text: str, prob: float, rng: random.Random) -> str:
    for group in _TIME_FORMAT_VARIANTS:
        for term in group:
            if term in text and rng.random() < prob:
                text = text.replace(term, rng.choice([t for t in group if t != term]))
                break
    return text


def augment_text(text: str, cfg: dict, rng: random.Random) -> str:
    """Apply the configured surface transforms to a single string."""
    s = cfg.get("surface", cfg)  # accept either full config or the 'surface' block

    def p(name: str) -> float:
        node = s.get(name, {})
        return node.get("prob", 0.0) if node.get("enabled", False) else 0.0

    text = _swap_synonyms(text, p("label_synonym_swap"), rng)
    text = _swap_time_format(text, p("time_format_swap"), rng)
    text = _apply_ocr_confusion(text, p("ocr_confusion"), rng)
    text = _apply_char_drop_insert(text, p("char_drop_insert"), rng)
    return text


def augment_candidate(
    candidate: TimeCandidate, cfg: dict, rng: random.Random, n: Optional[int] = None
) -> list[TimeCandidate]:
    """Return `n` augmented copies of a candidate (label unchanged).

    raw_text on each copy keeps the ORIGINAL surface for debugging.
    """
    surface = cfg.get("surface", {})
    n = n or surface.get("variants_per_candidate", 3)
    variants: list[TimeCandidate] = []
    for _ in range(n):
        variants.append(
            replace(
                candidate,
                candidate_text=augment_text(candidate.candidate_text, cfg, rng),
                nearby_text_before=augment_text(candidate.nearby_text_before, cfg, rng),
                nearby_text_after=augment_text(candidate.nearby_text_after, cfg, rng),
                section_title=(augment_text(candidate.section_title, cfg, rng) if candidate.section_title else None),
                table_row_label=(augment_text(candidate.table_row_label, cfg, rng) if candidate.table_row_label else None),
                raw_text=candidate.raw_text or candidate.candidate_text,
            )
        )
    return variants


def synthesize_from_canonical(canonical: dict, cfg: dict, rng: random.Random) -> list[dict]:
    """Phase 5-B reverse synthesis. Lands with real canonical JSON."""
    raise NotImplementedError(
        "Phase 5-B: canonical -> fake doc -> noise -> re-extract. Implement once "
        "canonical JSON exists; emphasize hard negatives (spec §5 table)."
    )
