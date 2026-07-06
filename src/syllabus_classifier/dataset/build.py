"""Build the candidate-level training dataset (Phase 4).

Matches Phase 2 canonical labels to Phase 3 extracted candidates, producing
"(candidate + context) -> gold label" rows in data/candidates/. Also reports
the class distribution (spec Phase 4) so severe imbalance surfaces early.

STATUS: skeleton. The matching logic depends on the canonical JSON format,
which is finalized once real syllabi and Phase 2 labeling land. Wired here so
the pipeline shape is visible and scripts import cleanly.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def match_candidates_to_labels(canonical: dict, candidates: list[Any]) -> list[dict]:
    """Align extracted candidates with the document's gold labels.

    ASSUMPTION: canonical JSON follows master spec v2 §6. Implementation lands
    with real data in Phase 4.
    """
    raise NotImplementedError(
        "Phase 4: implement candidate<->canonical matching once real canonical "
        "JSON exists (see master spec v2 §6)."
    )


def class_distribution(rows: list[dict], label_key: str = "label") -> dict[str, int]:
    """Report label counts — call this and log it (spec Phase 4)."""
    return dict(Counter(r[label_key] for r in rows))
