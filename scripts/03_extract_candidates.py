#!/usr/bin/env python3
"""Phase 3 (+ heuristic classify) — read normalized docs, extract every
date/time candidate, run the baseline classifier + validator, and report.

This is the "look at what actually comes out" pass (start-small principle):
it shows, per document, how many candidates were found and how they were
classified, and flags every candidate that landed in class_schedule so we can
eyeball precision before scaling up.

Usage:
  python scripts/01_normalize.py --sample 15
  python scripts/03_extract_candidates.py --show 6
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.extract import extract_candidates_from_doc
from syllabus_classifier.extract.normalize_doc import NormalizedDoc
from syllabus_classifier.model import HeuristicClassifier
from syllabus_classifier.validator import validate_candidate

CLF = HeuristicClassifier()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=5, help="how many docs to print detail for")
    ap.add_argument("--show-class", action="store_true", help="print every class_schedule candidate")
    args = ap.parse_args()

    cfg = load_config("data.yaml")
    norm_dir = resolve_path(cfg["paths"]["normalized_dir"])
    out_dir = resolve_path(cfg["paths"]["candidates_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(norm_dir.glob("*.json"))
    if not files:
        print(f"no normalized docs in {norm_dir}. Run scripts/01_normalize.py --sample N first.")
        return 1

    agg = Counter()
    total_cands = 0
    class_hits = []          # every class_schedule candidate, for eyeballing precision
    per_doc = []

    for fp in files:
        doc = NormalizedDoc.from_dict(json.loads(fp.read_text(encoding="utf-8")))
        cands = extract_candidates_from_doc(doc)
        rows = []
        dist = Counter()
        for c in cands:
            cls, rej = validate_candidate(c, CLF.predict(c))
            dist[cls.classified_as] += 1
            agg[cls.classified_as] += 1
            row = {
                "text": c.candidate_text,
                "label": cls.classified_as,
                "in_class": cls.include_in_class_schedule,
                "row_label": c.table_row_label,
                "date_kind": c.date_kind,
                "page": c.page,
            }
            rows.append(row)
            if cls.include_in_class_schedule:
                class_hits.append((doc.doc_id, row))
        total_cands += len(cands)
        per_doc.append((doc.doc_id, doc.extraction_quality, len(cands), dist))
        (out_dir / f"{doc.doc_id}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8"
        )

    # --- report ---
    print(f"=== {len(files)} docs | {total_cands} candidates | avg {total_cands/len(files):.1f}/doc ===\n")
    print("=== aggregate class distribution ===")
    for label, n in agg.most_common():
        print(f"  {label:26} {n:5}  ({100*n/max(total_cands,1):.1f}%)")

    print(f"\n=== per-doc (first {args.show}) ===")
    for doc_id, q, n, dist in per_doc[:args.show]:
        top = ", ".join(f"{k}:{v}" for k, v in dist.most_common(4))
        print(f"  [{q:9}] {n:3} cand | {doc_id[:44]:44} | {top}")

    print(f"\n=== class_schedule candidates: {len(class_hits)} (eyeball for false positives) ===")
    shown = class_hits if args.show_class else class_hits[:15]
    for doc_id, row in shown:
        print(f"  {doc_id[:34]:34} | p{row['page']} | row={str(row['row_label'])[:16]:16} | {row['text'][:30]}")
    if not args.show_class and len(class_hits) > 15:
        print(f"  ... (+{len(class_hits)-15} more; --show-class to see all)")

    print(f"\nwrote per-doc candidates -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
