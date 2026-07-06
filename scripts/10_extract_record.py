#!/usr/bin/env python3
"""v4 skeleton pass — run normalized docs through the field router to FULL
syllabus records, and emit the method-harness rows (§4).

Usage:
  python scripts/10_extract_record.py --sample 8          # spec §8: 5-10 docs first
  python scripts/10_extract_record.py --sample 8 --show 2 # print N records
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.eval.method_harness import build_rows, save_csv, save_rows
from syllabus_classifier.extract.field_router import route_document
from syllabus_classifier.extract.normalize_doc import NormalizedDoc
from syllabus_classifier.merge import build_record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=8)
    ap.add_argument("--show", type=int, default=1)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cfg = load_config("data.yaml")
    norm_dir = resolve_path(cfg["paths"]["normalized_dir"])
    out_dir = resolve_path("data/records")
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(norm_dir.glob("*.json"))
    if not files:
        print("no normalized docs; run scripts/01_normalize.py first")
        return 1
    rng = random.Random(args.seed)
    if args.sample and args.sample < len(files):
        files = rng.sample(files, args.sample)

    all_rows, filled = [], Counter()
    records = []
    for fp in files:
        doc = NormalizedDoc.from_dict(json.loads(fp.read_text(encoding="utf-8")))
        outputs = route_document(doc)               # llm off until Phase 3
        record = build_record(doc, outputs)
        records.append(record)
        (out_dir / f"{doc.doc_id}.record.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        rows = build_rows(doc.doc_id, outputs)
        all_rows.extend(rows)
        for r in rows:
            if r["rule"] not in (None, "") or r["subsystem"] not in (None, ""):
                filled[r["field"]] += 1

    save_rows(all_rows, out_dir / "harness.jsonl")
    save_csv(all_rows, out_dir / "harness.csv")

    n = len(files)
    print(f"=== {n} docs -> full records + harness rows ({len(all_rows)}) ===\n")
    print(f"{'field':32} {'coverage':>9}")
    for field, k in sorted(filled.items(), key=lambda x: -x[1]):
        print(f"{field:32} {k:>5}/{n}")
    empty = [f for f in {r['field'] for r in all_rows} if filled[f] == 0]
    print(f"\nfields with no output yet (LLM/Phase-3 or absent in sample): {len(empty)}")

    for record in records[: args.show]:
        print("\n=== sample record:", record["meta"]["syllabus_id"][:60], "===")
        print(json.dumps(record, ensure_ascii=False, indent=2)[:2600])

    print(f"\nwrote records + harness -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
