#!/usr/bin/env python3
"""Batch-2 evaluation — OUR extractor (+event hybrid) against batch-2 gold on
the REAL normalized corpus docs (tables intact — the fair setting for
총주차/주차별내용/이벤트 that flattened batch-1 text under-measured).

Old methods (룰/LLM/하이브리드) have no outputs for corpus docs, so this scores
ours only. Numbers stay PROVISIONAL: n=36 docs and the batch-2 trust gate
carries an anchoring caution (+16.7pp after notation-fair comparison).

Usage:  python scripts/16_batch2_eval.py [--no-hybrid]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.eval.excel_harness import FIELDS, ours_fields_from_doc
from syllabus_classifier.eval.method_compare import (
    HIGH_RISK_FIELDS,
    compute_metrics,
    event_partial_stats,
)
from syllabus_classifier.extract.normalize_doc import NormalizedDoc


def load_docs() -> dict[str, NormalizedDoc]:
    """syllabus_id -> real NormalizedDoc via the drafts mapping."""
    out = {}
    for line in Path("data/gold/drafts_batch2.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        fp = Path("data/normalized") / f"{d['doc_id']}.json"
        if fp.exists():
            out[d["syllabus_id"]] = NormalizedDoc.from_dict(json.loads(fp.read_text(encoding="utf-8")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-hybrid", action="store_true")
    args = ap.parse_args()

    gold = [json.loads(l) for l in Path("data/gold/gold_batch2.jsonl").read_text(encoding="utf-8").splitlines()]
    docs = load_docs()
    print(f"batch-2: {len(docs)} docs, {len(gold)} confirmed gold cells")

    preds: dict[str, dict] = {"ours": {}}
    for sid, doc in docs.items():
        fields = ours_fields_from_doc(doc)
        for f in FIELDS:
            v = fields.get(f)
            preds["ours"][(sid, f)] = str(v) if v not in (None, "") else None

    if not args.no_hybrid:
        from syllabus_classifier.common.env import load_env_key
        from syllabus_classifier.extract.event_hybrid import (
            llm_read_events, merge_events, risk_gate, serialize_events,
        )
        from syllabus_classifier.extract.field_router import extract_subsystem

        cache_path = Path("data/gold/llm_events_cache_b2.jsonl")
        cache = {}
        if cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                d = json.loads(line)
                cache[d["syllabus_id"]] = d["events"]
        client = None
        preds["ours_hybrid"] = {}
        with open(cache_path, "a", encoding="utf-8") as fh:
            for sid, doc in docs.items():
                text = doc.full_text
                if sid not in cache:
                    if client is None:
                        if not load_env_key():
                            print("no OPENAI_API_KEY — hybrid skipped")
                            preds.pop("ours_hybrid")
                            break
                        from openai import OpenAI
                        client = OpenAI(timeout=60, max_retries=3)
                    try:
                        cache[sid] = llm_read_events(text, client)
                    except Exception as e:
                        print(f"  llm events failed for {sid}: {type(e).__name__}")
                        cache[sid] = []
                    fh.write(json.dumps({"syllabus_id": sid, "events": cache[sid]}, ensure_ascii=False) + "\n")
                    fh.flush()
                dated, undated = risk_gate(cache[sid], text)
                sub = extract_subsystem(doc)
                table_evs = [{**e, "kind": "exam"} for e in sub.get("schedule.exams", [])] + \
                            [{**e, "kind": "assignment"} for e in sub.get("schedule.assignments", [])]
                preds["ours_hybrid"][(sid, "이벤트")] = serialize_events(merge_events(table_evs, dated))
                preds["ours_hybrid"][(sid, "무기한과제")] = " ; ".join(undated) or None

    methods = list(preds)
    m = compute_metrics(gold, preds)
    print(f"\n{'field':10} {'risk':4} | " + " | ".join(f"{x:^24}" for x in methods))
    print(f"{'':10} {'':4} | " + " | ".join(f"{'cov/prec/fab (n_out)':^24}" for _ in methods))
    for f in FIELDS:
        per = m.get(f, {})
        cells = []
        for x in methods:
            s = per.get(x)
            if not s or s["n"] == 0:
                cells.append(f"{'—':^24}")
                continue
            def pct(v):
                return f"{v:4.0%}" if v is not None else "   -"
            cells.append(f"{pct(s['coverage'])}/{pct(s['precision_where_output'])}/{pct(s['fabrication'])} ({s['n_output']:>2})")
        risk = "HIGH" if f in HIGH_RISK_FIELDS else ""
        print(f"{f:10} {risk:4} | " + " | ".join(cells))

    ev = event_partial_stats(gold, preds)
    print(f"\n=== 이벤트 event-level (batch-2 gold) ===")
    print(f"{'method':12} {'gold':>5} {'pred':>5} {'exact':>6} | {'title':>5} {'type':>5} {'date':>5} {'kind':>5}")
    for x in methods:
        s = ev[x]
        print(f"{x:12} {s['gold_events']:>5} {s['pred_events']:>5} {s['exact']:>6} | "
              f"{s['title']:>5} {s['type']:>5} {s['date']:>5} {s['date_kind']:>5}")

    Path("data/gold/batch2_report.json").write_text(
        json.dumps({"metrics": m, "event_partial": ev}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nreport -> data/gold/batch2_report.json  (PROVISIONAL: n=36, gate caution +16.7pp)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
