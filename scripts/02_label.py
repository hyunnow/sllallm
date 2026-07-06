#!/usr/bin/env python3
"""Phase 2 — LLM-assisted labeling (draft) + human-review export.

Extracts candidates (with full context) from the normalized docs, samples a
batch (stratified across the heuristic labels, oversampling the risky
office-hours / class_schedule / ambiguous boundary), drafts a label for each
with OpenAI, and writes a review CSV where a human corrects only what's wrong.

Robustness (learned the hard way — the SDK's 10-min default timeout can hang):
  - per-request timeout (--timeout) so a stalled call fails fast,
  - concurrent batches (--workers) so 350+ calls finish in minutes,
  - INCREMENTAL checkpoint: every completed batch is appended to the review
    JSONL immediately, so a crash never loses finished work,
  - --resume skips candidates already in the checkpoint.

Usage:
  python scripts/01_normalize.py                       # normalize corpus
  python scripts/02_label.py --n 8000 --workers 6      # label everything
  python scripts/02_label.py --resume                  # continue after a stop

The OpenAI key is loaded from --env-file so it is never pasted or printed.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.common.config import load_config, resolve_path
from syllabus_classifier.common.env import DEFAULT_ENV, load_env_key
from syllabus_classifier.extract import extract_candidates_from_doc
from syllabus_classifier.extract.normalize_doc import NormalizedDoc
from syllabus_classifier.label import draft_labels_batch, export_for_review
from syllabus_classifier.model import HeuristicClassifier
from syllabus_classifier.validator import validate_candidate

RISKY = {"class_schedule", "instructor_office_hours", "ta_office_hours", "unknown"}


def cand_key(c) -> str:
    return f"{c.doc_id}|{c.page}|{c.char_start}|{c.candidate_text}"


def collect_candidates(norm_dir: Path):
    clf = HeuristicClassifier()
    out = []
    for fp in sorted(norm_dir.glob("*.json")):
        doc = NormalizedDoc.from_dict(json.loads(fp.read_text(encoding="utf-8")))
        for c in extract_candidates_from_doc(doc):
            cls, _ = validate_candidate(c, clf.predict(c))
            out.append((c, cls.classified_as))
    return out


def stratified_pick(items, n, seed=42):
    by_label = defaultdict(list)
    for c, lab in items:
        by_label[lab].append((c, lab))
    rng = random.Random(seed)
    for v in by_label.values():
        rng.shuffle(v)
    picked, order = [], list(by_label.keys())
    while len(picked) < n and any(by_label.values()):
        for lab in order:
            for _ in range(2 if lab in RISKY else 1):
                if by_label[lab] and len(picked) < n:
                    picked.append(by_label[lab].pop())
    return picked[:n]


def row_for(c, heur, d):
    return {
        "_key": cand_key(c),
        "doc_id": c.doc_id,
        "candidate_text": c.candidate_text,
        "section_title": c.section_title,
        "table_row_label": c.table_row_label,
        "nearby_text_before": c.nearby_text_before,
        "nearby_text_after": c.nearby_text_after,
        "date_kind": c.date_kind,
        "heuristic_label": heur,
        "predicted_label": d.get("classified_as"),
        "include_in_class_schedule": d.get("include_in_class_schedule"),
        "confidence": d.get("confidence"),
        "evidence": d.get("evidence"),
        "corrected_label": "",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--env-file", default=DEFAULT_ENV)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--resume", action="store_true", help="skip candidates already in the checkpoint")
    args = ap.parse_args()

    if not load_env_key(args.env_file):
        print(f"ERROR: OPENAI_API_KEY not found in env or {args.env_file}")
        return 1
    print("OpenAI key loaded (not shown).", flush=True)

    cfg = load_config("data.yaml")
    norm_dir = resolve_path(cfg["paths"]["normalized_dir"])
    out_dir = resolve_path(cfg["paths"]["candidates_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = out_dir / "label_review.jsonl"

    all_cands = collect_candidates(norm_dir)
    if not all_cands:
        print("no candidates. Run scripts/01_normalize.py first.")
        return 1
    picked = stratified_pick(all_cands, args.n, args.seed)

    done_keys, existing = set(), []
    if args.resume and ckpt.exists():
        for line in ckpt.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                existing.append(r)
                done_keys.add(r.get("_key"))
    else:
        ckpt.write_text("", encoding="utf-8")  # fresh run: truncate

    todo = [(c, h) for (c, h) in picked if cand_key(c) not in done_keys]
    chunks = [todo[i:i + args.batch] for i in range(0, len(todo), args.batch)]
    print(f"labeling {len(todo)} candidates in {len(chunks)} batches "
          f"(model={args.model}, workers={args.workers}, timeout={args.timeout}s); "
          f"{len(done_keys)} already done\n", flush=True)

    from openai import OpenAI
    client = OpenAI(timeout=args.timeout, max_retries=3)

    def do_chunk(chunk):
        cands = [c for c, _ in chunk]
        try:
            drafts = draft_labels_batch(cands, model=args.model, client=client, timeout=args.timeout)
        except Exception as e:
            print(f"  batch failed: {type(e).__name__}: {e}", flush=True)
            drafts = [{} for _ in cands]
        return [row_for(c, h, d) for (c, h), d in zip(chunk, drafts)]

    all_rows = list(existing)
    done_batches = 0
    with open(ckpt, "a", encoding="utf-8") as fh, \
         cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(do_chunk, ch) for ch in chunks]
        for fut in cf.as_completed(futs):
            rows = fut.result()
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            all_rows.extend(rows)
            done_batches += 1
            if done_batches % 5 == 0 or done_batches == len(chunks):
                print(f"  {done_batches}/{len(chunks)} batches "
                      f"({sum(1 for r in all_rows if r['predicted_label'])} labeled)", flush=True)

    # dedupe by key (keep last)
    by_key = {r["_key"]: r for r in all_rows}
    rows = list(by_key.values())
    export_for_review(rows, str(out_dir / "label_review.csv"), fmt="csv")
    ckpt.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    labeled = [r for r in rows if r["predicted_label"]]
    agree = sum(1 for r in rows if r["predicted_label"] == r["heuristic_label"])
    print(f"\n=== {len(rows)} rows | {len(labeled)} labeled | "
          f"agreement {agree}/{len(rows)} ({100*agree/max(len(rows),1):.0f}%) ===", flush=True)
    for lab, k in Counter(r["predicted_label"] for r in labeled).most_common():
        print(f"  {str(lab):26} {k}", flush=True)
    print(f"\nreview file -> {out_dir/'label_review.csv'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
