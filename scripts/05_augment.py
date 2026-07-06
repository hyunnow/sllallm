#!/usr/bin/env python3
"""Phase 5 — surface augmentation of the TRAIN split only (spec §5, §6).

For each training example, generate N surface-noised variants (OCR confusion,
label-synonym swap, time-format swap, char drop/insert) with the label UNCHANGED.
This teaches robustness to messy extraction without the model memorizing surface
forms.

CRITICAL: only train.jsonl is read. val/test are never augmented — augmenting
them would leak and inflate performance (spec §6, §7).

Usage:
  python scripts/06_split.py
  python scripts/05_augment.py            # -> data/splits/train_aug.jsonl
  python scripts/07_train.py --train-file data/splits/train_aug.jsonl
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.dataset.build import compose_input
from syllabus_classifier.noise.augment import augment_text

TEXT_FIELDS = ["candidate_text", "section_title", "table_row_label", "nearby_text_before", "nearby_text_after"]


def augment_row(row: dict, cfg: dict, rng: random.Random) -> dict:
    new = dict(row)
    for f in TEXT_FIELDS:
        if row.get(f):
            new[f] = augment_text(row[f], cfg, rng)
    new["input_text"] = compose_input(new)   # label, doc_id, include_* unchanged
    new["source"] = "aug"
    new["aug"] = True
    return new


def main() -> int:
    cfg_data = load_config("data.yaml")
    cfg_noise = load_config("noise.yaml")
    splits_dir = resolve_path(cfg_data["paths"]["splits_dir"])
    train_path = splits_dir / "train.jsonl"
    if not train_path.exists():
        print(f"no {train_path}. Run scripts/06_split.py first.")
        return 1

    rng = random.Random(cfg_noise.get("seed", 42))
    n_variants = cfg_noise.get("surface", {}).get("variants_per_candidate", 3)
    train = [json.loads(l) for l in train_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    out = []
    for row in train:
        row = {**row, "aug": False}          # keep the original
        out.append(row)
        for _ in range(n_variants):
            out.append(augment_row(row, cfg_noise, rng))

    # --- safety checks (spec §6, §7) ---
    train_docs = {r["doc_id"] for r in train}
    aug_docs = {r["doc_id"] for r in out}
    assert aug_docs <= train_docs, "augmentation introduced doc_ids not in train (leakage!)"
    # label preserved: per output row, label must equal its parent's label — since we
    # copy 'label' and never touch it, verify the multiset scales exactly.
    base = Counter(r["label"] for r in train)
    aug = Counter(r["label"] for r in out)
    for lab in base:
        assert aug[lab] == base[lab] * (n_variants + 1), f"label {lab} count off — augmentation changed a label"

    out_path = splits_dir / "train_aug.jsonl"
    out_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out), encoding="utf-8")

    print(f"=== train augmentation ({n_variants} variants/example, label-preserving) ===")
    print(f"  original train : {len(train)}")
    print(f"  augmented total: {len(out)}  ({len(out)/max(len(train),1):.1f}x)")
    print(f"  docs unchanged : {len(aug_docs)} (all ⊆ train; val/test untouched)")
    print("  per-class (orig -> aug):")
    for lab, k in base.most_common():
        print(f"    {lab:26} {k:5} -> {aug[lab]:5}")
    print(f"\n[OK] labels preserved, no leakage. wrote -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
