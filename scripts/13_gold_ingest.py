#!/usr/bin/env python3
"""v5 §3-2 — ingest the reviewed gold workbook and report the two numbers that
say whether this gold can be trusted:

  EDIT RATE    among confirmed non-blind cells: how often the human's final gold
               differs from the shown draft. ~0 is a WARNING (perfect draft, or
               rubber-stamping — suspect the latter).
  BLIND CHECK  among confirmed blind cells: agreement between human gold and the
               HIDDEN draft. If assisted agreement >> blind agreement, drafts are
               anchoring the reviewers (v5 Rule 4).

Also exports trusted gold (확정=Y only, Rule 1) to data/gold/gold.jsonl.

Usage:  python scripts/13_gold_ingest.py [--review data/gold/gold_review.xlsx]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _render(v) -> str:
    """Excel may hand back datetime/time objects; render them the way a reviewer
    typed them, not as '2026-03-06 00:00:00'."""
    import datetime as _dt

    if isinstance(v, _dt.datetime):
        return v.date().isoformat() if (v.hour, v.minute, v.second) == (0, 0, 0) else v.isoformat(sep=" ")
    if isinstance(v, _dt.time):
        return v.strftime("%H:%M")
    return str(v) if v is not None else ""


def _norm(s) -> str:
    s = re.sub(r"\s+", " ", _render(s)).strip().lower()
    return re.sub(r"\s*([;|~:])\s*", r"\1", s)


CONFIRM_MARKS = {"y", "yes", "true", "1", "o", "ㅇ", "○", "✓", "v", "예", "확정"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", default="data/gold/gold_review.xlsx")
    ap.add_argument("--drafts", default="data/gold/drafts.jsonl")
    ap.add_argument("--out", default="data/gold/gold.jsonl")
    args = ap.parse_args()

    import openpyxl

    drafts = {}
    for line in Path(args.drafts).read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        drafts[d["syllabus_id"]] = d

    wb = openpyxl.load_workbook(args.review, data_only=True)
    ws = wb["검수"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))

    confirmed = []
    stats = {"assisted": {"n": 0, "edited": 0, "agree": 0},
             "blind": {"n": 0, "agree": 0}}
    per_field = defaultdict(lambda: {"n": 0, "edited": 0})
    empty_confirmed = 0
    unrecognized = 0
    inconsistent = 0

    for sid, field, shown_draft, gold, ok, memo in (r[:6] for r in rows if r and r[0]):
        gold_s = _render(gold).strip()
        if _norm(ok) not in CONFIRM_MARKS:
            # visible-but-unrecognized review activity must not vanish silently
            if gold_s or _render(ok).strip():
                unrecognized += 1
            continue                                  # Rule 1: unconfirmed ≠ gold
        rec = drafts.get(sid, {})
        hidden = (rec.get("draft") or {}).get(field)
        shown = _render(shown_draft).strip()
        marker_blind = shown == "[BLIND]"
        is_blind = rec.get("blind", marker_blind)
        if rec and bool(rec.get("blind")) != marker_blind:
            inconsistent += 1
        confirmed.append({"syllabus_id": sid, "field": field,
                          "gold": gold_s or None, "blind": is_blind,
                          "memo": _render(memo).strip() or None})
        # assisted rows compare against what the reviewer actually SAW (workbook),
        # blind rows against the hidden draft (drafts.jsonl).
        ref = hidden if is_blind else shown
        if not gold_s and not _norm(ref):
            empty_confirmed += 1                      # both empty: exported, NOT scored
            continue
        agree = _norm(gold_s) == _norm(ref)
        if is_blind:
            stats["blind"]["n"] += 1
            stats["blind"]["agree"] += int(agree)
        else:
            stats["assisted"]["n"] += 1
            stats["assisted"]["agree"] += int(agree)
            stats["assisted"]["edited"] += int(not agree)
            per_field[field]["n"] += 1
            per_field[field]["edited"] += int(not agree)

    Path(args.out).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in confirmed), encoding="utf-8")

    a, b = stats["assisted"], stats["blind"]
    print(f"confirmed gold cells: {len(confirmed)}  ->  {args.out}")
    print(f"  (both-empty confirmed cells excluded from metrics: {empty_confirmed})")
    if unrecognized:
        print(f"  WARNING: {unrecognized} rows have review content but an unrecognized 확정 mark — not counted as gold!")
    if inconsistent:
        print(f"  WARNING: {inconsistent} rows where drafts.jsonl blind flag contradicts the [BLIND] marker")
    if a["n"]:
        print(f"\nEDIT RATE (assisted, n={a['n']}): {a['edited']/a['n']:.2%}"
              f"   (draft-agreement {a['agree']/a['n']:.2%})")
        print("  ~0% edit rate is a WARNING: perfect drafts or rubber-stamping — check the latter.")
    if b["n"]:
        print(f"BLIND CHECK (n={b['n']}): human-vs-hidden-draft agreement {b['agree']/b['n']:.2%}")
        if a["n"]:
            gap = a["agree"]/a["n"] - b["agree"]/b["n"]
            print(f"  anchoring gap (assisted - blind agreement): {gap:+.2%}"
                  "  — large positive gap = drafts are anchoring reviewers (v5 Rule 4).")
    if a["n"]:
        print("\nper-field edit rate (assisted):")
        for f, s in sorted(per_field.items(), key=lambda kv: -(kv[1]["edited"]/max(kv[1]["n"],1))):
            if s["n"]:
                print(f"  {f:10} {s['edited']}/{s['n']} ({s['edited']/s['n']:.0%})")
    if not confirmed:
        print("\nno confirmed cells yet — fill 정답 + 확정(Y) in the 검수 sheet first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
