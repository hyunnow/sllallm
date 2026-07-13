"""Document normalization (Phase 1): raw file -> text + tables + pages.

Format handling (measured on the real corpus: ~90% text PDF, ~10% scanned,
a few HWP):
  - text PDF     -> pdfplumber (page text + tables, row/col labels preserved)
  - scanned PDF  -> pdf2image + EasyOCR   (lazy; needs poppler + torch, runs on Colab)
  - HWP          -> pyhwp `hwp5txt`

Tables MUST retain row/col labels — whether a time sits in the "면담시간" row is
the single strongest classification cue (spec Phase 1). Low-quality / failed
extractions are recorded in `notes`, never silently dropped.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, Optional

# pdfminer (under pdfplumber) is noisy about CropBox etc.; quiet it.
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)

# below this many characters per page on average, treat the PDF as scanned.
_SCAN_CHARS_PER_PAGE = 30

# hwp5txt may live in a user bin not on PATH.
_HWP5TXT = shutil.which("hwp5txt") or str(Path.home() / "Library/Python/3.9/bin/hwp5txt")


def repair_doubled_runs(text: str) -> str:
    """볼드 오버프린트가 글자를 2배로 뽑는 PDF 제목 줄을 복원한다 (B7-040:
    '강강의의계계획획서서 [[22002266년년도도 11 학학기기]]' → '강의계획서 [2026년도 1 학기]').
    판정은 줄 단위: 글자의 60% 이상이 연속쌍인 줄만 전체 쌍을 접는다 — 정상
    문장('bookkeeper', '031-8005')은 쌍 비율이 낮아 건드리지 않는다."""
    if not text:
        return text
    out = []
    for line in text.split("\n"):
        n = len(line)
        paired = i = 0
        while i + 1 < n:
            if line[i] == line[i + 1]:
                paired += 2
                i += 2
            else:
                i += 1
        if n >= 8 and paired / n > 0.6:
            res = []
            i = 0
            while i < n:
                res.append(line[i])
                i += 2 if (i + 1 < n and line[i] == line[i + 1]) else 1
            out.append("".join(res))
        else:
            out.append(line)
    return "\n".join(out)


@dataclass
class Table:
    header: list[str] = field(default_factory=list)   # column labels (first row)
    rows: list[list[str]] = field(default_factory=list)

    def cells(self) -> Iterator[tuple[str, str, str]]:
        """Yield (row_label, col_label, cell_text) for each non-empty body cell.
        row_label = first cell of the row; col_label = header of the column."""
        for row in self.rows:
            row_label = row[0].strip() if row else ""
            for c, cell in enumerate(row):
                text = (cell or "").strip()
                if not text:
                    continue
                col_label = self.header[c].strip() if c < len(self.header) and self.header[c] else ""
                yield row_label, col_label, text

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Page:
    page_no: int
    text: str = ""
    tables: list[Table] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"page_no": self.page_no, "text": self.text, "tables": [t.to_dict() for t in self.tables]}


@dataclass
class NormalizedDoc:
    doc_id: str
    pages: list[Page] = field(default_factory=list)
    source_format: Optional[str] = None     # pdf_text | pdf_scan | hwp
    extraction_quality: str = "ok"          # ok | low | needs_ocr | failed
    notes: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(repair_doubled_runs(p.text) for p in self.pages)

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "source_format": self.source_format,
            "extraction_quality": self.extraction_quality,
            "notes": self.notes,
            "pages": [p.to_dict() for p in self.pages],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NormalizedDoc":
        pages = [
            Page(
                page_no=p["page_no"],
                text=p.get("text", ""),
                tables=[Table(header=t.get("header", []), rows=t.get("rows", [])) for t in p.get("tables", [])],
            )
            for p in d.get("pages", [])
        ]
        return cls(
            doc_id=d["doc_id"],
            pages=pages,
            source_format=d.get("source_format"),
            extraction_quality=d.get("extraction_quality", "ok"),
            notes=d.get("notes", []),
        )


# --- text blob (used by tests/smoke and already-extracted text) ------------
def normalize_text_blob(doc_id: str, text: str) -> NormalizedDoc:
    """Wrap flat text as a NormalizedDoc. Flattened-table lines that use pipe
    delimiters ("CREDIT | 3 | INSTRUCTOR | Kelly Jeong") are reconstructed as
    pseudo-tables so the label→next-cell extraction path fires on them.

    CONSECUTIVE pipe lines form one table each (runs split at non-pipe lines):
    a meta block and a weekly-plan block become separate tables, which lets the
    weekly-plan detector see the plan instead of one giant mixed table."""
    tables: list[Table] = []
    run: list[list[str]] = []
    for ln in text.splitlines() + [""]:
        if "|" in ln:
            run.append([c.strip() for c in ln.split("|")])
        elif run:
            tables.append(Table(header=[], rows=run))
            run = []
    return NormalizedDoc(doc_id=doc_id, pages=[Page(page_no=1, text=text, tables=tables)],
                         source_format="text")


# --- PDF -------------------------------------------------------------------
def normalize_pdf(path: str, doc_id: str) -> NormalizedDoc:
    """Text PDF -> NormalizedDoc via pdfplumber. Falls back to OCR if the PDF has
    no extractable text layer (scanned)."""
    import pdfplumber

    pages: list[Page] = []
    total_chars = 0
    try:
        with pdfplumber.open(path) as pdf:
            for i, pg in enumerate(pdf.pages, 1):
                text = pg.extract_text() or ""
                total_chars += len(text)
                tables = []
                try:
                    for raw in pg.extract_tables():
                        rows = [[(c or "").strip() for c in row] for row in raw if row]
                        if rows:
                            tables.append(Table(header=rows[0], rows=rows[1:]))
                except Exception as e:  # table extraction can fail on odd layouts
                    pages_note = f"table extract failed p{i}: {type(e).__name__}"
                pages.append(Page(page_no=i, text=text, tables=tables))
    except Exception as e:
        return NormalizedDoc(doc_id=doc_id, source_format="pdf", extraction_quality="failed",
                             notes=[f"pdfplumber open failed: {type(e).__name__}: {e}"])

    npages = max(len(pages), 1)
    # CID-garbage: a broken font map exposes glyph ids "(cid:123)" instead of
    # text — human-readable on screen, useless as text (SYL-036/040 reviewer
    # memo). Treat like a scan: OCR is the only way to read it.
    all_text = "".join(p.text for p in pages)
    if all_text and all_text.count("(cid:") * 8 > len(all_text) * 0.3:
        return NormalizedDoc(doc_id=doc_id, pages=pages, source_format="pdf_cid",
                             extraction_quality="needs_ocr",
                             notes=["CID-encoded text layer (broken font map); needs OCR"])
    if total_chars / npages < _SCAN_CHARS_PER_PAGE:
        # no usable text layer -> scanned; defer to OCR.
        doc = normalize_scanned_pdf(path, doc_id)
        if doc is not None:
            return doc
        return NormalizedDoc(doc_id=doc_id, pages=pages, source_format="pdf_scan",
                             extraction_quality="needs_ocr",
                             notes=[f"no text layer ({total_chars} chars / {npages} pages); OCR unavailable here"])

    quality = "ok" if total_chars / npages >= 100 else "low"
    return NormalizedDoc(doc_id=doc_id, pages=pages, source_format="pdf_text", extraction_quality=quality)


def normalize_scanned_pdf(path: str, doc_id: str, langs: tuple[str, ...] = ("ko", "en")) -> Optional[NormalizedDoc]:
    """Scanned PDF -> NormalizedDoc via pdf2image + EasyOCR.

    Returns None if the local environment lacks poppler/EasyOCR (e.g. this Mac);
    the caller then marks the doc needs_ocr. On Colab (poppler + torch present)
    this runs for real.
    """
    try:
        from pdf2image import convert_from_path  # needs poppler
        import easyocr  # needs torch
    except Exception:
        return None
    try:
        reader = easyocr.Reader(list(langs), gpu=True)
        images = convert_from_path(path, dpi=200)
        pages = []
        for i, img in enumerate(images, 1):
            import numpy as np
            lines = reader.readtext(np.array(img), detail=0, paragraph=True)
            pages.append(Page(page_no=i, text="\n".join(lines)))
        return NormalizedDoc(doc_id=doc_id, pages=pages, source_format="pdf_scan", extraction_quality="ok",
                             notes=["OCR via EasyOCR"])
    except Exception as e:
        return NormalizedDoc(doc_id=doc_id, source_format="pdf_scan", extraction_quality="failed",
                             notes=[f"OCR failed: {type(e).__name__}: {e}"])


# --- HWP -------------------------------------------------------------------
def normalize_hwp(path: str, doc_id: str) -> NormalizedDoc:
    """HWP -> NormalizedDoc via pyhwp `hwp5txt`. Tables come through as text with
    <표> markers; structural row/col labels are not recovered (only 8 files)."""
    if not Path(_HWP5TXT).exists():
        return NormalizedDoc(doc_id=doc_id, source_format="hwp", extraction_quality="failed",
                             notes=["hwp5txt not found (pip install pyhwp)"])
    try:
        out = subprocess.run([_HWP5TXT, str(path)], capture_output=True, timeout=60)
        text = out.stdout.decode("utf-8", errors="replace")
        if not text.strip():
            return NormalizedDoc(doc_id=doc_id, source_format="hwp", extraction_quality="failed",
                                 notes=["hwp5txt produced no text"])
        return NormalizedDoc(doc_id=doc_id, pages=[Page(page_no=1, text=text)],
                             source_format="hwp", extraction_quality="ok")
    except Exception as e:
        return NormalizedDoc(doc_id=doc_id, source_format="hwp", extraction_quality="failed",
                             notes=[f"hwp5txt failed: {type(e).__name__}: {e}"])


# --- dispatch + corpus iteration ------------------------------------------
def normalize_file(path: str, doc_id: Optional[str] = None) -> NormalizedDoc:
    p = Path(path)
    doc_id = doc_id or p.stem
    ext = p.suffix.lower()
    if ext == ".pdf":
        return normalize_pdf(str(p), doc_id)
    if ext in (".hwp", ".hwpx"):
        return normalize_hwp(str(p), doc_id)
    return NormalizedDoc(doc_id=doc_id, source_format=ext.lstrip("."), extraction_quality="failed",
                         notes=[f"unsupported format {ext}"])


def iter_corpus_files(raw_dir: str, exts: tuple[str, ...] = (".pdf", ".hwp", ".hwpx", ".doc", ".docx")) -> list[tuple[str, Path]]:
    """Return (doc_id, path) for every syllabus under raw_dir. doc_id is a slug of
    the path relative to raw_dir (keeps school + filename, unique across the corpus)."""
    root = Path(raw_dir)
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in exts and not p.name.startswith("."):
            rel = p.relative_to(root)
            slug = str(rel.with_suffix("")).replace("/", "__").replace(" ", "_")
            out.append((slug, p))
    return out
