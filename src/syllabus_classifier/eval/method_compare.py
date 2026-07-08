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

# fields whose ` ; ` segments are an unordered set — 연락처 included: the
# email/phone order is serialization convention, not meaning.
MULTI_SEGMENT_FIELDS = {"수업시간", "이벤트", "무기한과제", "주차별내용", "연락처"}
HIGH_RISK_FIELDS = {"수업시간", "이벤트"}


# 학기 표기는 계절 기준으로 동치 (reviewer policy memo B2-009: 한국/미국의 1·2학기가
# 계절상 반대이므로 계절 표기로 통일) — 1↔봄↔spring, 2↔가을↔fall 등을 같은 값으로 채점.
_TERM_CANON = {
    "1": "spring", "1학기": "spring", "봄": "spring", "봄학기": "spring", "spring": "spring",
    "2": "fall", "2학기": "fall", "가을": "fall", "가을학기": "fall", "fall": "fall", "autumn": "fall",
    "여름": "summer", "여름학기": "summer", "summer": "summer", "하계": "summer",
    "겨울": "winter", "겨울학기": "winter", "winter": "winter", "동계": "winter",
}


def values_match(field: str, pred, gold) -> bool:
    if field == "학기":
        p, g = _norm(pred), _norm(gold)
        return _TERM_CANON.get(p, p) == _TERM_CANON.get(g, g)
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


def parse_events(v) -> list[tuple]:
    """'제목 | 타입 | 날짜 | 날짜종류 ; ...' -> normalized 4-tuples (padded)."""
    out = []
    for seg in str(v or "").split(";"):
        seg = seg.strip()
        if not seg:
            continue
        parts = [_norm(p) for p in seg.split("|")]
        out.append(tuple((parts + ["", "", "", ""])[:4]))
    return out


def event_partial_stats(gold_cells: list[dict], preds: dict[str, dict],
                        docs: Optional[set] = None) -> dict:
    """Event-LEVEL diagnostics for 이벤트 (the '이벤트_정답수' idea): per method,
    how many gold events are fully matched, and which PARTS (title/type/date/
    date_kind) match after greedy best-alignment. Diagnostic only — winners are
    still chosen by the three field-level metrics."""
    res = {}
    for method, table in preds.items():
        g_total = p_total = exact = aligned = 0
        part_hits = [0, 0, 0, 0]
        for c in gold_cells:
            if c["field"] != "이벤트":
                continue
            if docs is not None and c["syllabus_id"] not in docs:
                continue
            G = parse_events(c["gold"])
            P = parse_events(table.get((c["syllabus_id"], "이벤트")))
            g_total += len(G)
            p_total += len(P)
            used: set = set()
            for g in G:
                best, best_score = None, 0
                for j, p in enumerate(P):
                    if j in used:
                        continue
                    score = sum(1 for a, b in zip(g, p) if a and a == b)
                    if score > best_score:
                        best_score, best = score, j
                if best is not None:
                    used.add(best)
                    aligned += 1
                    p = P[best]
                    for k in range(4):
                        if g[k] and g[k] == p[k]:
                            part_hits[k] += 1
                    if g == p:
                        exact += 1
        res[method] = {
            "gold_events": g_total, "pred_events": p_total, "aligned": aligned,
            "exact": exact, "title": part_hits[0], "type": part_hits[1],
            "date": part_hits[2], "date_kind": part_hits[3],
        }
    return res


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
