"""Leakage-proof group split (Phase 6 / spec §6, §7).

ABSOLUTE RULE: every candidate and every augmentation derived from the same
source document (same doc_id) must land in the SAME split. Splitting at the
candidate level would put a document's train rows next to its own test rows and
inflate performance. So we split by group (doc_id), never by row.
"""
from __future__ import annotations

import random
from typing import Any, Callable, Iterable


def group_split(
    items: list[Any],
    get_group: Callable[[Any], Any],
    *,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    seed: int = 42,
) -> dict[str, list[Any]]:
    """Split `items` into train/val/test by group id.

    The split is computed over the set of distinct groups, then items are routed
    to the split of their group. Deterministic given `seed`.
    """
    total = train_ratio + val_ratio + test_ratio
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"ratios must sum to 1.0, got {total}")

    groups = sorted({get_group(it) for it in items}, key=lambda g: str(g))
    rng = random.Random(seed)
    rng.shuffle(groups)

    n = len(groups)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)
    train_g = set(groups[:n_train])
    val_g = set(groups[n_train:n_train + n_val])
    test_g = set(groups[n_train + n_val:])

    out: dict[str, list[Any]] = {"train": [], "val": [], "test": []}
    for it in items:
        g = get_group(it)
        if g in train_g:
            out["train"].append(it)
        elif g in val_g:
            out["val"].append(it)
        else:
            out["test"].append(it)
    return out


def assert_no_group_leakage(splits: dict[str, list[Any]], get_group: Callable[[Any], Any]) -> None:
    """Raise if any group appears in more than one split. Call after splitting."""
    seen: dict[Any, str] = {}
    for split_name, items in splits.items():
        for it in items:
            g = get_group(it)
            if g in seen and seen[g] != split_name:
                raise AssertionError(
                    f"leakage: group {g!r} in both {seen[g]!r} and {split_name!r}"
                )
            seen[g] = split_name
