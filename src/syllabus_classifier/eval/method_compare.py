"""Method comparison on trusted gold (v5 §4).

Three metrics per field × method — never coverage alone:
  coverage               did the method output anything (over confirmed cells)
  precision_where_output when it output, was it right
  fabrication            it output a value where gold confirms the source has none

Winner selection is RISK-WEIGHTED (v5 §4-2): for high-risk fields (수업시간,
이벤트 — wrong dates/times are catastrophic) the winner minimizes fabrication
then error; for standard fields it balances coverage and precision. And the
N=37 discipline (v5 §4-3): winners are picked on the DEV docs and are
PROVISIONAL; the honest numbers are reported from the HOLDOUT docs only.

Value equality: normalized exact match; the ` ; `-serialized fields (수업시간,
이벤트, 무기한과제, 주차별내용) compare as unordered SETS of normalized segments,
so ordering differences don't count as errors.
"""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Optional

from .excel_harness import _norm

MULTI_SEGMENT_FIELDS = {"수업시간", "이벤트", "무기한과제", "주차별내용"}
HIGH_RISK_FIELDS = {"수업시간", "이벤트"}


def values_match(field: str, pred, gold) -> bool:
    if field in MULTI_SEGMENT_FIELDS:
        p = {s.strip() for s in _norm(pred).split(";") if s.strip()}
        g = {s.strip() for s in _norm(gold).split(";") if s.strip()}
        return p == g
    return _norm(pred) == _norm(gold)


def split_docs(doc_ids: list[str], dev_ratio: float = 0.6, seed: int = 42) -> tuple[set, set]:
    ids = sorted(set(doc_ids))
    rng = random.Random(seed)
    rng.shuffle(ids)
    n_dev = round(len(ids) * dev_ratio)
    return set(ids[:n_dev]), set(ids[n_dev:])


def compute_metrics(
    gold_cells: list[dict],          # {"syllabus_id","field","gold"(str|None)}
    preds: dict[str, dict],          # method -> {(sid, field): value|None}
    docs: Optional[set] = None,
) -> dict:
    """{field: {method: {n, coverage, precision_where_output, fabrication,
    n_output, n_correct, n_fabricated}}} over confirmed gold cells (optionally
    restricted to `docs`)."""
    out: dict = defaultdict(dict)
    by_field: dict[str, list[dict]] = defaultdict(list)
    for c in gold_cells:
        if docs is None or c["syllabus_id"] in docs:
            by_field[c["field"]].append(c)

    for field, cells in by_field.items():
        for method, table in preds.items():
            n = len(cells)
            n_out = n_correct = n_fab = 0
            for c in cells:
                pred = table.get((c["syllabus_id"], field))
                if pred in (None, ""):
                    continue
                n_out += 1
                if c["gold"] in (None, ""):
                    n_fab += 1                       # gold-confirmed absent, method invented
                elif values_match(field, pred, c["gold"]):
                    n_correct += 1
            out[field][method] = {
                "n": n,
                "n_output": n_out,
                "n_correct": n_correct,
                "n_fabricated": n_fab,
                "coverage": n_out / n if n else None,
                "precision_where_output": n_correct / n_out if n_out else None,
                "fabrication": n_fab / n_out if n_out else None,
            }
    return dict(out)


def pick_winner(field: str, per_method: dict) -> Optional[str]:
    """Risk-weighted provisional winner. Methods with zero output are skipped."""
    candidates = {m: s for m, s in per_method.items() if s["n_output"] > 0}
    if not candidates:
        return None
    if field in HIGH_RISK_FIELDS:
        # v5 §4-2: '틀릴 바엔 비운다' — fabrication asc, error asc, coverage desc
        def key(m):
            s = candidates[m]
            return (s["fabrication"], 1 - (s["precision_where_output"] or 0), -(s["coverage"] or 0))
    else:
        def key(m):
            s = candidates[m]
            cov, prec = s["coverage"] or 0.0, s["precision_where_output"] or 0.0
            hm = (2 * cov * prec / (cov + prec)) if (cov + prec) else 0.0
            return (-hm, -prec)
    return min(candidates, key=key)
