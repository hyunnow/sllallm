#!/usr/bin/env python3
"""Phase 6 — leakage-proof train/val/test split by document id.

Every candidate from the same syllabus goes to the SAME split (group split on
doc_id), so no document's rows straddle train and test. The test set is the real
holdout — performance is judged only here (spec Phase 6, §7).

Usage:
  python scripts/04_build_dataset.py
  python scripts/06_split.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.dataset.split import assert_no_group_leakage, group_split


def main() -> int:
    cfg = load_config("data.yaml")
    cand_dir = resolve_path(cfg["paths"]["candidates_dir"])
    splits_dir = resolve_path(cfg["paths"]["splits_dir"])
    splits_dir.mkdir(parents=True, exist_ok=True)

    ds_path = cand_dir / "dataset.jsonl"
    if not ds_path.exists():
        print(f"no {ds_path}. Run scripts/04_build_dataset.py first.")
        return 1
    rows = [json.loads(l) for l in ds_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    sc = cfg["split"]
    splits = group_split(
        rows, lambda r: r["doc_id"],
        train_ratio=sc["train_ratio"], val_ratio=sc["val_ratio"],
        test_ratio=sc["test_ratio"], seed=sc["seed"],
    )
    assert_no_group_leakage(splits, lambda r: r["doc_id"])

    print("=== split (group = doc_id, no leakage verified) ===")
    for name in ("train", "val", "test"):
        part = splits[name]
        (splits_dir / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in part), encoding="utf-8"
        )
        docs = len({r["doc_id"] for r in part})
        cls = sum(1 for r in part if r["label"] == "class_schedule")
        top = ", ".join(f"{k}:{v}" for k, v in Counter(r["label"] for r in part).most_common(3))
        print(f"  {name:5} | {len(part):5} rows | {docs:4} docs | class_schedule={cls:4} | {top}")

    print(f"\n  test = REAL HOLDOUT (no augmentation yet) — judge performance here only.")
    print(f"wrote splits -> {splits_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
