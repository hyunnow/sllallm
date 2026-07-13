#!/usr/bin/env python3
"""OCR 백로그 (HANDOFF §2 ④). 로컬엔 OCR 엔진(EasyOCR/tesseract)이 없다 —
설계상 OCR 실행은 Colab 몫. 이 스크립트가 하는 일:

  (기본) 백로그 매니페스트 작성: needs_ocr/failed/low + chrome-only 저내용 문서를
         모아 data/records/ocr_manifest.jsonl 로. 각 항목에 원본 경로를 붙여
         Colab EasyOCR 배치에 그대로 넣을 수 있게 한다.

  --reingest DIR: Colab이 뽑아온 OCR 텍스트(<doc_id>.txt)를 DIR에서 읽어
         data/normalized/<doc_id>.json 을 재작성(정규화)한다. 그러면 이후
         전 파이프라인이 그 문서를 정상 문서로 취급한다.

Usage:
  python scripts/21_ocr_backlog.py
  python scripts/21_ocr_backlog.py --reingest data/records/ocr_text
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.extract.normalize_doc import (
    NormalizedDoc, iter_corpus_files, normalize_text_blob,
)
from syllabus_classifier.extract.ocr_backlog import is_low_content


def build_manifest() -> int:
    norm_dir = resolve_path(load_config("data.yaml")["paths"]["normalized_dir"])
    raw_dir = resolve_path(load_config("data.yaml")["paths"]["raw_dir"])
    id2path = dict(iter_corpus_files(str(raw_dir))) if raw_dir.exists() else {}

    reasons = Counter()
    manifest = []
    for fp in sorted(norm_dir.glob("*.json")):
        doc = NormalizedDoc.from_dict(json.loads(fp.read_text(encoding="utf-8")))
        q = doc.extraction_quality
        text = doc.full_text
        reason = None
        if q in ("needs_ocr", "failed"):
            reason = q
        elif q == "low":
            reason = "low"
        elif is_low_content(text, max(len(doc.pages), 1)):
            reason = "chrome_only"          # 품질 ok지만 실질 내용 없음 (B6-001형)
        if not reason:
            continue
        reasons[reason] += 1
        src = id2path.get(doc.doc_id)
        manifest.append({
            "doc_id": doc.doc_id,
            "reason": reason,
            "raw_chars": len(text.strip()),
            "source_path": str(src) if src else None,
        })

    out = resolve_path("data/records/ocr_manifest.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for m in manifest:
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")

    missing_src = sum(1 for m in manifest if not m["source_path"])
    print(f"OCR 백로그 총 {len(manifest)}건  {dict(reasons)}")
    print(f"  원본 경로 확인됨 {len(manifest) - missing_src} / 미확인 {missing_src}")
    print(f"  chrome-only 신규 탐지(품질 ok였던 것): {reasons['chrome_only']}건")
    print(f"\n매니페스트 -> {out}")
    print("실행: Colab에서 EasyOCR로 각 source_path를 OCR → <doc_id>.txt 저장 →")
    print("      python scripts/21_ocr_backlog.py --reingest <그 폴더>")
    return 0


def reingest(text_dir: str) -> int:
    tdir = Path(text_dir)
    if not tdir.exists():
        print(f"ERROR: {tdir} 없음")
        return 1
    norm_dir = resolve_path(load_config("data.yaml")["paths"]["normalized_dir"])
    done = 0
    for txt in sorted(tdir.glob("*.txt")):
        doc_id = txt.stem
        text = txt.read_text(encoding="utf-8").strip()
        if is_low_content(text, 1):
            print(f"  건너뜀(여전히 저내용): {doc_id[:60]}")
            continue
        doc = normalize_text_blob(doc_id, text)
        doc.source_format = "ocr"
        doc.extraction_quality = "ok"
        doc.notes = ["re-ingested from OCR text"]
        (norm_dir / f"{doc_id}.json").write_text(
            json.dumps(doc.to_dict(), ensure_ascii=False), encoding="utf-8")
        done += 1
    print(f"재수집 완료: {done}건 -> {norm_dir}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reingest", metavar="DIR", help="OCR 텍스트(<doc_id>.txt) 폴더")
    args = ap.parse_args()
    return reingest(args.reingest) if args.reingest else build_manifest()


if __name__ == "__main__":
    raise SystemExit(main())
