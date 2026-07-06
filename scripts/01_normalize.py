#!/usr/bin/env python3
"""Phase 1 — normalize raw syllabi to text + tables + pages.

Usage:
  python scripts/01_normalize.py --sample 15      # stratified sample across schools
  python scripts/01_normalize.py                  # whole corpus (slow)

Writes one JSON per doc to data/normalized/ and prints a quality summary.
Extraction failures are logged, never dropped (spec Phase 1).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.extract.normalize_doc import iter_corpus_files, normalize_file


def stratified_sample(files, n, seed=42):
    """Pick ~n files spread across the top-level school folders."""
    by_school = defaultdict(list)
    for doc_id, path in files:
        by_school[doc_id.split("__", 1)[0]].append((doc_id, path))
    rng = random.Random(seed)
    per = max(1, -(-n // max(len(by_school), 1)))   # ceil(n / schools)
    picked = []
    for school, items in sorted(by_school.items()):
        picked.extend(rng.sample(items, min(per, len(items))))
    rng.shuffle(picked)
    return picked[:n] if n < len(picked) else picked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="stratified sample size (0 = all)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cfg = load_config("data.yaml")
    raw_dir = resolve_path(cfg["paths"]["raw_dir"])
    out_dir = resolve_path(cfg["paths"]["normalized_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    files = iter_corpus_files(str(raw_dir))
    print(f"corpus: {len(files)} files under {raw_dir}")
    if args.sample:
        files = stratified_sample(files, args.sample, args.seed)
        print(f"sampling {len(files)} docs (seed={args.seed})")

    quality = Counter()
    fmt = Counter()
    failures = []
    for doc_id, path in files:
        doc = normalize_file(str(path), doc_id)
        quality[doc.extraction_quality] += 1
        fmt[doc.source_format] += 1
        (out_dir / f"{doc_id}.json").write_text(
            json.dumps(doc.to_dict(), ensure_ascii=False), encoding="utf-8"
        )
        if doc.extraction_quality in ("failed", "needs_ocr"):
            failures.append((doc_id, doc.extraction_quality, "; ".join(doc.notes)))

    print("\n=== quality ===", dict(quality))
    print("=== format   ===", dict(fmt))
    if failures:
        print(f"\n=== {len(failures)} docs need attention (OCR / failed) ===")
        for doc_id, q, note in failures[:20]:
            print(f"  [{q}] {doc_id}  {note}")
    print(f"\nwrote {len(files)} normalized docs -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
