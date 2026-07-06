"""YAML config loading, anchored at the repo root so paths are stable
regardless of the current working directory (Colab, scripts, tests)."""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml


@functools.lru_cache(maxsize=1)
def repo_root() -> Path:
    """Walk up from this file until we find the repo marker (pyproject.toml)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    # Fallback: src/syllabus_classifier/common/config.py -> repo root is parents[3]
    return here.parents[3]


def config_dir() -> Path:
    return repo_root() / "config"


@functools.lru_cache(maxsize=None)
def load_config(name: str) -> dict[str, Any]:
    """Load config/<name> (e.g. 'train.yaml'). Cached; call load_config.cache_clear() to reload."""
    path = config_dir() / name
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_yaml(path: "str | Path") -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_path(rel: str) -> Path:
    """Resolve a repo-relative path (as stored in data.yaml) to an absolute Path."""
    p = Path(rel)
    return p if p.is_absolute() else repo_root() / p
