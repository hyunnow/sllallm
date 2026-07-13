#!/usr/bin/env python3
"""Colab OCR 러너 (④ 실행) — data/records/ocr_manifest.jsonl의 각 원본을 텍스트로
뽑아 <doc_id>.txt 로 저장한다. 로컬 Mac엔 OCR 엔진이 없으므로 이 스크립트는
**Colab에서** 돌린다(무거운 의존성은 지연 import). 산출 폴더를 그대로
`21_ocr_backlog.py --reingest` 에 넣으면 정규화 코퍼스에 흡수된다.

처리:
  .pdf              → pdf2image로 페이지 이미지 → EasyOCR(ko+en) → 텍스트
  .doc/.docx/.hwp   → libreoffice --headless 로 txt 변환 (OCR 아님); 실패 시 건너뜀

Colab 준비:
  !apt-get -qq install -y poppler-utils libreoffice
  !pip -q install easyocr pdf2image
  !python scripts/24_colab_ocr.py --out data/records/ocr_text
  # 그다음(로컬 또는 Colab):
  !python scripts/21_ocr_backlog.py --reingest data/records/ocr_text
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import resolve_path
from syllabus_classifier.extract.ocr_backlog import is_low_content


def ocr_pdf(path: str, reader) -> str:
    from pdf2image import convert_from_path

    pages = convert_from_path(path, dpi=200)
    chunks = []
    for img in pages:
        import numpy as np

        for line in reader.readtext(np.array(img), detail=0, paragraph=True):
            chunks.append(line)
    return "\n".join(chunks)


def convert_office(path: str, tmp: Path) -> str:
    """libreoffice headless로 txt 변환 (doc/docx/hwp). 실패 시 빈 문자열."""
    try:
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "txt:Text",
             "--outdir", str(tmp), path],
            check=True, capture_output=True, timeout=120)
        out = tmp / (Path(path).stem + ".txt")
        return out.read_text(encoding="utf-8", errors="ignore") if out.exists() else ""
    except Exception as e:
        print(f"    office 변환 실패 {type(e).__name__}")
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--out", default="data/records/ocr_text")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    manifest = Path(args.manifest) if args.manifest else resolve_path("data/records/ocr_manifest.jsonl")
    items = [json.loads(l) for l in manifest.read_text(encoding="utf-8").splitlines()]
    if args.limit:
        items = items[: args.limit]
    out_dir = resolve_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "_tmp"
    tmp.mkdir(exist_ok=True)

    reader = None
    done = skipped = 0
    for m in items:
        src = m.get("source_path")
        if not src or not Path(src).exists():
            print(f"  원본 없음: {m['doc_id'][:50]}")
            skipped += 1
            continue
        ext = Path(src).suffix.lower()
        try:
            if ext == ".pdf":
                if reader is None:
                    import easyocr
                    reader = easyocr.Reader(["ko", "en"], gpu=True)
                text = ocr_pdf(src, reader)
            elif ext in (".doc", ".docx", ".hwp", ".hwpx"):
                text = convert_office(src, tmp)
            else:
                print(f"  미지원 확장자 {ext}: {m['doc_id'][:50]}")
                skipped += 1
                continue
        except Exception as e:
            print(f"  실패 {type(e).__name__}: {m['doc_id'][:50]}")
            skipped += 1
            continue

        if is_low_content(text, 1):
            print(f"  여전히 저내용(건너뜀): {m['doc_id'][:50]}")
            skipped += 1
            continue
        (out_dir / f"{m['doc_id']}.txt").write_text(text.strip(), encoding="utf-8")
        done += 1
        print(f"  OK [{ext}] {m['doc_id'][:56]}  ({len(text.strip())}자)")

    print(f"\n완료: {done}건 텍스트화 / {skipped}건 건너뜀 -> {out_dir}")
    print(f"다음: python scripts/21_ocr_backlog.py --reingest {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
