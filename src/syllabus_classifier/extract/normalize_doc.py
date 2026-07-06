"""Document normalization (Phase 1): raw file -> text + tables + sections.

Tables MUST retain row/col labels — whether a time sits in the "면담시간" row is
the single strongest classification cue (spec Phase 1).

Format plan (answered so far: text PDF + scan PDF):
  - text PDF  -> pdfplumber (text + tables)
  - scan PDF  -> pdf2image + OCR   (OCR engine TBD — see README "Open question")
Low-quality / failed extractions are logged, never silently dropped (spec Phase 1).

STATUS: `normalize_text_blob` is implemented so synthetic text flows end-to-end
today (smoke test). The PDF/OCR paths are stubbed until the real data location
and OCR engine are confirmed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NormalizedSection:
    title: Optional[str]
    text: str
    page: int = 1
    rows: list[dict] = field(default_factory=list)  # [{"row_label":..., "col_label":..., "text":...}]


@dataclass
class NormalizedDoc:
    doc_id: str
    sections: list[NormalizedSection] = field(default_factory=list)
    source_format: Optional[str] = None
    extraction_quality: str = "ok"       # ok | low | failed
    notes: list[str] = field(default_factory=list)


def normalize_text_blob(doc_id: str, text: str, section_title: Optional[str] = None) -> NormalizedDoc:
    """Wrap a plain-text blob as a NormalizedDoc (used by the smoke test and by
    already-extracted text). No parsing magic — one section, one page."""
    return NormalizedDoc(
        doc_id=doc_id,
        sections=[NormalizedSection(title=section_title, text=text, page=1)],
        source_format="text",
    )


def normalize_pdf(path: str, doc_id: str) -> NormalizedDoc:
    """Text PDF -> NormalizedDoc via pdfplumber (Phase 1)."""
    raise NotImplementedError(
        "Phase 1: implement with pdfplumber once data/raw location is confirmed. "
        "Preserve table row/col labels."
    )


def normalize_scanned_pdf(path: str, doc_id: str, ocr_engine: Optional[str] = None) -> NormalizedDoc:
    """Scanned PDF/image -> NormalizedDoc via pdf2image + OCR (Phase 1).

    OCR engine is an open question (Korean-capable): candidates are PaddleOCR,
    EasyOCR, or Tesseract(+kor). To be decided with the user before implementing.
    """
    raise NotImplementedError(
        "Phase 1: implement OCR path after choosing a Korean-capable OCR engine."
    )
