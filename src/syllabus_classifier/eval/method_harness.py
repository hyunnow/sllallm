"""Method-comparison harness (v4 §4) — the Excel, reproduced in code.

One row per (doc × field): the outputs of every method side by side, plus a
gold column (initially "라벨대기"). Once gold is filled, per-method correctness
flags and the field × method win-rate table are computed automatically; the
winner per field is then frozen into config/field_methods.yaml.

NOTE: the exact column layout will be reconciled against the user's original
Excel once it lands in the repo folder.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from ..record.schema import HARNESS_FIELDS

GOLD_PENDING = "라벨대기"
METHODS = ("rule", "rule_llm", "llm", "subsystem")


def build_rows(doc_id: str, outputs: dict[str, dict]) -> list[dict]:
    """Harness rows for one document from the field router's per-method outputs."""
    rows = []
    for field in HARNESS_FIELDS:
        row = {"doc_id": doc_id, "field": field, "eval": HARNESS_FIELDS[field]["eval"]}
        for m in METHODS:
            row[m] = _display(outputs.get(m, {}).get(field))
        row["gold"] = GOLD_PENDING
        rows.append(row)
    return rows


def _display(v: Any) -> Any:
    """Keep scalar values as-is; compact lists/dicts for the comparison table."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return json.dumps(v, ensure_ascii=False)


# --- scoring (used once gold is filled) -----------------------------------------


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def is_correct(pred: Any, gold: Any, eval_kind: str) -> Optional[bool]:
    """None = not scorable (no gold yet, or method not run)."""
    if gold in (None, "", GOLD_PENDING):
        return None
    if pred in (None, ""):
        # an intentionally-empty gold ("<null>") counts a null pred as correct
        return gold == "<null>"
    if eval_kind == "exact":
        return _norm_text(pred) == _norm_text(gold)
    if eval_kind == "fuzzy":
        p, g = _norm_text(pred), _norm_text(gold)
        return p == g or p in g or g in p
    # risk fields are scored by the risk metrics (hallucination 0), not equality;
    # here we still allow exact-match bookkeeping.
    return _norm_text(pred) == _norm_text(gold)


def score(rows: list[dict]) -> dict:
    """Field × method win-rate table over all gold-filled rows (§4)."""
    table: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {"n": 0, "ok": 0}))
    for row in rows:
        for m in METHODS:
            verdict = is_correct(row.get(m), row.get("gold"), row.get("eval", "exact"))
            if verdict is None:
                continue
            cell = table[row["field"]][m]
            cell["n"] += 1
            cell["ok"] += int(verdict)
    out = {}
    for field, per_method in table.items():
        stats = {m: {"n": v["n"], "win_rate": (v["ok"] / v["n"]) if v["n"] else None}
                 for m, v in per_method.items()}
        scored = {m: s for m, s in stats.items() if s["win_rate"] is not None}
        winner = max(scored, key=lambda m: scored[m]["win_rate"]) if scored else None
        out[field] = {"methods": stats, "winner": winner}
    return out


def save_rows(rows: list[dict], path: "str | Path") -> None:
    Path(path).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def save_csv(rows: list[dict], path: "str | Path") -> None:
    import csv

    fields = ["doc_id", "field", "eval", *METHODS, "gold"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
