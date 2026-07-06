#!/usr/bin/env python3
"""Phase 7 — train the encoder classifier (run on Colab with a GPU).

  pip install -e ".[train]"
  python scripts/04_build_dataset.py && python scripts/06_split.py
  python scripts/07_train.py --encoder klue/roberta-base

Reads data/splits/, trains with class-weighted / focal loss, applies the
conservative class_schedule threshold, and reports metrics on the REAL HOLDOUT.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.seed import set_seed
from syllabus_classifier.model.train import train


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="train.yaml")
    ap.add_argument("--out", default=None)
    ap.add_argument("--train-file", default=None,
                    help="override train split (e.g. data/splits/train_aug.jsonl); val/test stay real")
    ap.add_argument("--encoder", default=None, help="override the encoder in train.yaml")
    args = ap.parse_args()
    set_seed(42)
    train(config_name=args.config, out_dir=args.out, train_file=args.train_file, encoder=args.encoder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
