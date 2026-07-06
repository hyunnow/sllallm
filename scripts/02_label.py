#!/usr/bin/env python3
"""Phase 2 — LLM-assisted labeling (draft) + human-review export.

Extracts candidates (with full context) from the normalized docs, samples a
batch (stratified across the heuristic labels, oversampling the risky
office-hours / class_schedule / ambiguous boundary), drafts a label for each
with OpenAI, and writes a review CSV where a human corrects only what's wrong.

Also reports LLM-vs-heuristic agreement — disagreements are exactly where the
labels are worth a human's attention.

Usage:
  python scripts/01_normalize.py --sample 100          # produce normalized docs
  python scripts/02_label.py --n 150 --batch 15        # draft labels for 150 candidates

The OpenAI key is loaded from --env-file (default: the gwatop backend .env) so
it never has to be pasted or printed.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.extract import extract_candidates_from_doc
from syllabus_classifier.extract.normalize_doc import NormalizedDoc
from syllabus_classifier.label import draft_labels_batch, export_for_review
from syllabus_classifier.model import HeuristicClassifier
from syllabus_classifier.validator import validate_candidate

DEFAULT_ENV = "/Users/hyunwoo/Documents/gwatop/gwatop-backend/.env"
# oversample the labels where a mistake is most costly / most informative
RISKY = {"class_schedule", "instructor_office_hours", "ta_office_hours", "unknown"}


def load_env_key(env_file: str, var: str = "OPENAI_API_KEY") -> bool:
    if os.environ.get(var):
        return True
    p = Path(env_file)
    if not p.exists():
        return False
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{var}="):
            os.environ[var] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return True
    return False


def collect_candidates(norm_dir: Path):
    """Return (candidate, heuristic_label) for all candidates in normalized docs."""
    clf = HeuristicClassifier()
    out = []
    for fp in sorted(norm_dir.glob("*.json")):
        doc = NormalizedDoc.from_dict(json.loads(fp.read_text(encoding="utf-8")))
        for c in extract_candidates_from_doc(doc):
            cls, _ = validate_candidate(c, clf.predict(c))
            out.append((c, cls.classified_as))
    return out


def stratified_pick(items, n, seed=42):
    """Pick n candidates spread across heuristic labels, oversampling RISKY ones."""
    by_label = defaultdict(list)
    for c, lab in items:
        by_label[lab].append((c, lab))
    rng = random.Random(seed)
    for v in by_label.values():
        rng.shuffle(v)
    picked, i = [], 0
    # round-robin, giving risky labels a double turn
    order = list(by_label.keys())
    while len(picked) < n and any(by_label.values()):
        for lab in order:
            take = 2 if lab in RISKY else 1
            for _ in range(take):
                if by_label[lab] and len(picked) < n:
                    picked.append(by_label[lab].pop())
    return picked[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150, help="candidates to label")
    ap.add_argument("--batch", type=int, default=15, help="candidates per API call")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--env-file", default=DEFAULT_ENV)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if not load_env_key(args.env_file):
        print(f"ERROR: OPENAI_API_KEY not found in env or {args.env_file}")
        return 1
    print("OpenAI key loaded (not shown).")

    cfg = load_config("data.yaml")
    norm_dir = resolve_path(cfg["paths"]["normalized_dir"])
    out_dir = resolve_path(cfg["paths"]["candidates_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    all_cands = collect_candidates(norm_dir)
    if not all_cands:
        print(f"no candidates. Run scripts/01_normalize.py --sample N first.")
        return 1
    picked = stratified_pick(all_cands, args.n, args.seed)
    print(f"labeling {len(picked)} of {len(all_cands)} candidates "
          f"(model={args.model}, batch={args.batch})\n")

    from openai import OpenAI
    client = OpenAI()

    rows = []
    agree = 0
    conf = Counter()  # (heuristic, llm) pairs
    for start in range(0, len(picked), args.batch):
        chunk = picked[start:start + args.batch]
        cands = [c for c, _ in chunk]
        try:
            drafts = draft_labels_batch(cands, model=args.model, client=client)
        except Exception as e:
            print(f"  batch {start//args.batch} failed: {type(e).__name__}: {e}")
            drafts = [{} for _ in cands]
        for (c, heur), d in zip(chunk, drafts):
            llm_label = d.get("classified_as")
            if llm_label == heur:
                agree += 1
            conf[(heur, llm_label)] += 1
            rows.append({
                "doc_id": c.doc_id,
                "candidate_text": c.candidate_text,
                "section_title": c.section_title,
                "table_row_label": c.table_row_label,
                "nearby_text_before": c.nearby_text_before,
                "nearby_text_after": c.nearby_text_after,
                "heuristic_label": heur,
                "predicted_label": llm_label,
                "include_in_class_schedule": d.get("include_in_class_schedule"),
                "confidence": d.get("confidence"),
                "evidence": d.get("evidence"),
                "corrected_label": "",  # human fills only when wrong
            })
        print(f"  labeled {min(start+args.batch, len(picked))}/{len(picked)}")

    review_csv = out_dir / "label_review.csv"
    export_for_review(rows, str(review_csv), fmt="csv")
    (out_dir / "label_review.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8"
    )

    labeled = [r for r in rows if r["predicted_label"]]
    print(f"\n=== LLM label distribution ===")
    for lab, k in Counter(r["predicted_label"] for r in labeled).most_common():
        print(f"  {str(lab):26} {k}")
    print(f"\nLLM vs heuristic agreement: {agree}/{len(rows)} ({100*agree/max(len(rows),1):.0f}%)")
    print("=== top disagreements (heuristic -> llm : count) ===")
    for (h, l), k in conf.most_common():
        if h != l:
            print(f"  {h:24} -> {str(l):24} {k}")
    print(f"\nreview file (correct only what's wrong) -> {review_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
