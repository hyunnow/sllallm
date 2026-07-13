#!/usr/bin/env python3
"""승자 확정 (v5 §4-3) — 동결된 gold(배치 2~7, 233 docs) 위에서 필드별 승자를
dev에서 고르고, 최종 숫자는 holdout에서만 보고한다.

규율:
  - 문서 단위 60/40 dev/holdout, 배치별 층화, 고정 seed 42 (train-on-test 금지).
  - 승자 선정은 pick_winner의 위험 가중 규칙 (§4-2: HIGH-risk는 조작 최소 우선).
  - 민감도 검사: 주의 딱지 배치(2: +16.7pp, 7: +14.8pp)를 빼고 다시 골라도
    승자가 같아야 확정 — 뒤집히면 그 필드는 '잠정' 유지.

Usage:  python scripts/17_winner_report.py
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from syllabus_classifier.eval.excel_harness import FIELDS, ours_fields_from_doc
from syllabus_classifier.eval.method_compare import (
    HIGH_RISK_FIELDS,
    compute_metrics,
    pick_winner,
)
from syllabus_classifier.extract.event_hybrid import (
    merge_events, risk_gate, serialize_events, suppress_scheduled,
)
from syllabus_classifier.extract.field_router import extract_subsystem
from syllabus_classifier.extract.normalize_doc import NormalizedDoc

BATCHES = (2, 3, 4, 5, 6, 7)
CAUTION = {2, 7}          # blind 격차 주의 딱지 배치 — 민감도 검사에서 제외해 본다
HYBRID_FIELDS = ("이벤트", "무기한과제")


def load_batch(n: int):
    gold = [json.loads(l) for l in Path(f"data/gold/gold_batch{n}.jsonl").read_text(encoding="utf-8").splitlines()]
    docs, cache = {}, {}
    for line in Path(f"data/gold/drafts_batch{n}.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        fp = Path("data/normalized") / f"{d['doc_id']}.json"
        if fp.exists():
            docs[d["syllabus_id"]] = NormalizedDoc.from_dict(json.loads(fp.read_text(encoding="utf-8")))
    cp = Path(f"data/gold/llm_events_cache_b{n}.jsonl")
    if cp.exists():
        for line in cp.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            cache[d["syllabus_id"]] = d["events"]
    return gold, docs, cache


def main() -> int:
    all_gold: list[dict] = []
    preds: dict[str, dict] = {"ours": {}, "ours_hybrid": {}}
    batch_of: dict[str, int] = {}

    for n in BATCHES:
        gold, docs, cache = load_batch(n)
        all_gold.extend(gold)
        for sid, doc in docs.items():
            batch_of[sid] = n
            fields = ours_fields_from_doc(doc)
            for f in FIELDS:
                v = fields.get(f)
                preds["ours"][(sid, f)] = str(v) if v not in (None, "") else None
            if sid in cache:
                text = doc.full_text
                dated, undated = risk_gate(cache[sid], text)
                sub = extract_subsystem(doc)
                table_evs = [{**e, "kind": "exam"} for e in sub.get("schedule.exams", [])] + \
                            [{**e, "kind": "assignment"} for e in sub.get("schedule.assignments", [])]
                merged = merge_events(table_evs, dated)
                undated = suppress_scheduled(undated, merged, sub.get("schedule.weekly_plan") or [])
                preds["ours_hybrid"][(sid, "이벤트")] = serialize_events(merged)
                preds["ours_hybrid"][(sid, "무기한과제")] = " ; ".join(undated) or None

    # 문서 단위 dev/holdout — 배치별 층화, seed 고정 (§4-3)
    dev, holdout = set(), set()
    for n in BATCHES:
        sids = sorted(s for s, b in batch_of.items() if b == n)
        rng = random.Random(42)
        rng.shuffle(sids)
        k = round(len(sids) * 0.6)
        dev.update(sids[:k])
        holdout.update(sids[k:])
    print(f"docs: {len(batch_of)} (dev {len(dev)} / holdout {len(holdout)}), "
          f"confirmed gold cells: {len(all_gold)}")

    m_dev = compute_metrics(all_gold, preds, docs=dev)
    m_hold = compute_metrics(all_gold, preds, docs=holdout)
    dev_no_caution = {s for s in dev if batch_of[s] not in CAUTION}
    m_dev_nc = compute_metrics(all_gold, preds, docs=dev_no_caution)

    winners: dict[str, dict] = {}
    print(f"\n{'field':10} {'risk':4} {'승자(dev)':12} {'민감도':6} | holdout cov/prec/fab (n_out/n)")
    for f in FIELDS:
        per_dev = {m: s for m, s in (m_dev.get(f) or {}).items()}
        w = pick_winner(f, per_dev) if per_dev else None
        w_nc = pick_winner(f, m_dev_nc.get(f) or {}) if m_dev_nc.get(f) else None
        stable = (w == w_nc)
        s = (m_hold.get(f) or {}).get(w) if w else None
        risk = "HIGH" if f in HIGH_RISK_FIELDS else ""
        def pct(v):
            return f"{v:4.0%}" if v is not None else "   -"
        cell = (f"{pct(s['coverage'])}/{pct(s['precision_where_output'])}/{pct(s['fabrication'])}"
                f" ({s['n_output']:>3}/{s['n']:>3})") if s and s["n"] else "—"
        print(f"{f:10} {risk:4} {str(w):12} {'안정' if stable else '뒤집힘!':6} | {cell}")
        winners[f] = {
            "winner_dev": w,
            "stable_without_caution_batches": stable,
            "status": "확정" if (w and stable) else "잠정",
            "holdout": {k: s[k] for k in ("n", "n_output", "coverage",
                                          "precision_where_output", "fabrication")} if s else None,
        }

    out = {
        "declared": "2026-07-13",
        "basis": {"batches": list(BATCHES), "caution_batches": sorted(CAUTION),
                  "split": "per-batch 60/40, seed 42", "docs": len(batch_of)},
        "winners": winners,
    }
    Path("data/gold/field_winners.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nwinners -> data/gold/field_winners.json")
    flips = [f for f, w in winners.items() if w["winner_dev"] and not w["stable_without_caution_batches"]]
    if flips:
        print(f"민감도 뒤집힘(잠정 유지): {flips}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
