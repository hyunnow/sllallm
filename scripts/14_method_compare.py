#!/usr/bin/env python3
"""Phase 3 (v5 §4) — method comparison on TRUSTED gold.

Joins the confirmed gold (data/gold/gold.jsonl) with four methods' outputs on
the same 37 syllabi — the Excel's stored 룰/LLM/하이브리드 plus OUR rule+subsystem
— and reports the three metrics per field × method, with risk-weighted
PROVISIONAL winners picked on dev docs and honest numbers from holdout docs.

Per v5 §4-3 nothing here overwrites config/field_methods.yaml: N is small, the
winners are provisional and carry their sample sizes.

Usage:  python scripts/14_method_compare.py [--xlsx ParserTest.xlsx]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.eval.excel_harness import FIELDS, load_rows, ours_for_excel_fields
from syllabus_classifier.eval.method_compare import (
    HIGH_RISK_FIELDS,
    compute_metrics,
    pick_winner,
    split_docs,
)


def fmt(v, pct=True):
    if v is None:
        return "   -"
    return f"{v:4.0%}" if pct else str(v)


def print_table(title: str, metrics: dict, methods: list[str]) -> None:
    print(f"\n=== {title} ===")
    print(f"{'field':10} {'risk':4} | " + " | ".join(f"{m:^24}" for m in methods))
    print(f"{'':10} {'':4} | " + " | ".join(f"{'cov/prec/fab (n_out)':^24}" for _ in methods))
    for field in FIELDS:
        per = metrics.get(field, {})
        risk = "HIGH" if field in HIGH_RISK_FIELDS else ""
        cells = []
        for m in methods:
            s = per.get(m)
            if not s or s["n"] == 0:
                cells.append(f"{'—':^24}")
                continue
            cells.append(f"{fmt(s['coverage'])}/{fmt(s['precision_where_output'])}/{fmt(s['fabrication'])} ({s['n_output']:>2})")
        print(f"{field:10} {risk:4} | " + " | ".join(cells))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default="ParserTest.xlsx")
    ap.add_argument("--gold", default="data/gold/gold.jsonl")
    ap.add_argument("--dev-ratio", type=float, default=0.6)
    args = ap.parse_args()

    gold_cells = [json.loads(l) for l in Path(args.gold).read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in load_rows(args.xlsx) if r["source_text"]]

    preds: dict[str, dict] = {m: {} for m in ("rule", "llm", "hybrid", "ours")}
    for r in rows:
        sid = r["syllabus_id"]
        for f in FIELDS:
            for m in ("rule", "llm", "hybrid"):
                preds[m][(sid, f)] = r["fields"][f][m]
        ours = ours_for_excel_fields(r["source_text"], sid)
        for f in FIELDS:
            v = ours.get(f)
            preds["ours"][(sid, f)] = str(v) if v not in (None, "") else None

    doc_ids = [r["syllabus_id"] for r in rows]
    dev, holdout = split_docs(doc_ids, args.dev_ratio)
    print(f"docs: {len(doc_ids)} (dev {len(dev)} / holdout {len(holdout)}) | "
          f"confirmed gold cells: {len(gold_cells)}")

    methods = ["rule", "llm", "hybrid", "ours"]
    m_dev = compute_metrics(gold_cells, preds, dev)
    m_hold = compute_metrics(gold_cells, preds, holdout)

    print_table("DEV (winner selection only)", m_dev, methods)
    winners = {}
    for field in FIELDS:
        w = pick_winner(field, m_dev.get(field, {})) if m_dev.get(field) else None
        if w:
            winners[field] = {"provisional_winner": w, "dev_n": m_dev[field][w]["n"],
                              "dev_n_output": m_dev[field][w]["n_output"]}
    print_table("HOLDOUT (honest numbers — small n, wide error bars)", m_hold, methods)

    print("\n=== PROVISIONAL winners (dev-picked; NOT written to field_methods.yaml — n too small) ===")
    for field, w in winners.items():
        hold = m_hold.get(field, {}).get(w["provisional_winner"])
        hold_s = (f"holdout cov {fmt(hold['coverage'])} prec {fmt(hold['precision_where_output'])} "
                  f"fab {fmt(hold['fabrication'])} (n={hold['n']})") if hold and hold["n"] else "no holdout cells"
        risk = " [HIGH-RISK: fabrication-first]" if field in HIGH_RISK_FIELDS else ""
        print(f"  {field:10} -> {w['provisional_winner']:6} (dev n={w['dev_n']}, out={w['dev_n_output']}){risk} | {hold_s}")

    report = {"dev": m_dev, "holdout": m_hold, "winners": winners,
              "n_docs": len(doc_ids), "n_gold_cells": len(gold_cells)}
    out = Path("data/gold/method_report.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
