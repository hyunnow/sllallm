"""Bridge to the user's original comparison Excel (ParserTest.xlsx, v4 §4).

The Excel IS the method harness: 1 syllabus = 1 row; 13 fields × 4 versions
(정답 gold / 룰 rule / LLM llm / 하이브리드 hybrid) + auto OK flags + 오류유형 +
원문텍스트(ML input). This module loads it, RE-SCORES independently (exact
match per the 읽어보기 rules: blank gold or blank prediction is excluded), and
reports per-field win rates.

CAVEAT that must never be forgotten when reading these numbers: gold was
PRE-FILLED with the hybrid outputs (readme: "정답(하이브리드 값 프리필)") and every
row is still 상태=라벨대기 — until a human reviews, accuracy vs gold is biased
toward hybrid. Coverage (how often a method outputs anything) is unbiased.

The Excel stays git-ignored (local only).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Optional

FIELDS = ["과목명", "교수", "연락처", "학점", "강의실", "총주차", "수업시간",
          "이벤트", "무기한과제", "주차별내용", "대학", "학년도", "학기"]
METHODS = {"rule": "룰", "llm": "LLM", "hybrid": "하이브리드"}
GOLD_PENDING_STATUS = "파싱완료(라벨대기)"


def load_rows(path: "str | Path" = "ParserTest.xlsx") -> list[dict]:
    """One dict per filled syllabus row: meta + per-field {gold,rule,llm,hybrid}."""
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb["데이터셋"]
    raw = list(ws.iter_rows(values_only=True))
    header = raw[0]
    idx = {h: i for i, h in enumerate(header)}
    id_col = idx.get("syllabus_id", 0)   # header-keyed, not positional
    body = [r for r in raw[1:] if r and r[id_col]]

    def cell(row, col) -> Optional[str]:
        i = idx.get(col)
        if i is None:
            return None
        v = row[i]
        s = str(v).strip() if v is not None else ""
        return s or None

    out = []
    for r in body:
        rec = {
            "syllabus_id": cell(r, "syllabus_id"),
            "source_file": cell(r, "파일명"),
            "school": cell(r, "대학"),
            "status": cell(r, "상태"),
            "error_type": cell(r, "오류유형"),
            "source_text": cell(r, "원문텍스트(ML입력)"),
            "fields": {},
        }
        for f in FIELDS:
            rec["fields"][f] = {
                "gold": cell(r, f"정답_{f}"),
                "rule": cell(r, f"룰_{f}"),
                "llm": cell(r, f"LLM_{f}"),
                "hybrid": cell(r, f"하이브리드_{f}"),
            }
        out.append(rec)
    return out


def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip().lower()
    return re.sub(r"\s*([;|~:])\s*", r"\1", s)   # spacing around separators is not a difference


def exact_ok(pred: Optional[str], gold: Optional[str]) -> Optional[bool]:
    """Readme rule: blank gold OR blank prediction -> excluded (None)."""
    if not gold or not pred:
        return None
    return _norm(pred) == _norm(gold)


def score_rows(rows: list[dict]) -> dict:
    """Per-field: coverage per method + accuracy-vs-gold (with the prefill caveat)."""
    n = len(rows)
    table = {}
    for f in FIELDS:
        stats = {}
        for m in METHODS:
            preds = [r["fields"][f][m] for r in rows]
            golds = [r["fields"][f]["gold"] for r in rows]
            cov = sum(1 for p in preds if p)
            verdicts = [exact_ok(p, g) for p, g in zip(preds, golds)]
            scored = [v for v in verdicts if v is not None]
            stats[m] = {
                "coverage": cov,
                "n_scored": len(scored),
                "acc": (sum(scored) / len(scored)) if scored else None,
            }
        gold_cov = sum(1 for r in rows if r["fields"][f]["gold"])
        # how often gold literally equals hybrid — the prefill-bias indicator
        same = [exact_ok(r["fields"][f]["hybrid"], r["fields"][f]["gold"]) for r in rows]
        same = [v for v in same if v is not None]
        table[f] = {
            "n_docs": n,
            "gold_filled": gold_cov,
            "gold_equals_hybrid_rate": (sum(same) / len(same)) if same else None,
            "methods": stats,
        }
    return table


def print_summary(table: dict) -> None:
    print(f"{'field':10} {'gold':>4} | {'rule cov/acc':>14} | {'llm cov/acc':>14} | {'hybrid cov/acc':>15} | g==hyb")
    for f, t in table.items():
        def fmt(m):
            s = t["methods"][m]
            acc = f"{s['acc']:.2f}" if s["acc"] is not None else "  - "
            return f"{s['coverage']:>4}/{acc}"
        geq = t["gold_equals_hybrid_rate"]
        geq_s = f"{geq:.2f}" if geq is not None else "-"
        print(f"{f:10} {t['gold_filled']:>4} | {fmt('rule'):>14} | {fmt('llm'):>14} | {fmt('hybrid'):>15} | {geq_s}")
