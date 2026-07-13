"""YAML config loading.

Runtime KBs (period_timetables, academic_calendars, school_dictionary,
label_dictionary) ship inside the package (``syllabus_classifier/config/``) so
they resolve after a plain ``pip install`` with no repo checkout. Training- and
script-only configs (train.yaml, data.yaml, noise.yaml, field_methods.yaml) stay
at the repo root ``config/`` and resolve via the repo-root walk-up.

``load_config(name)`` searches, in order:
  1. ``$SYLLABUS_CLASSIFIER_CONFIG_DIR`` (explicit override, e.g. a host app)
  2. the packaged ``syllabus_classifier/config/`` (importlib.resources)
  3. the repo-root ``config/`` (dev checkout / scripts / Colab)
returning the first location that has the file.
"""
from __future__ import annotations

import functools
import importlib.resources as _resources
import os
from pathlib import Path
from typing import Any, Iterator

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
    """Repo-root config dir (dev checkout). Training/script configs live here."""
    return repo_root() / "config"


def _packaged_config_dir() -> "Path | None":
    """The config dir bundled inside the installed package, if resolvable."""
    try:
        d = _resources.files("syllabus_classifier") / "config"
        p = Path(str(d))
        return p if p.is_dir() else None
    except (ModuleNotFoundError, AttributeError, TypeError):
        return None


def _config_search_dirs() -> Iterator[Path]:
    env = os.environ.get("SYLLABUS_CLASSIFIER_CONFIG_DIR")
    if env:
        yield Path(env)
    pkg = _packaged_config_dir()
    if pkg is not None:
        yield pkg
    yield config_dir()


@functools.lru_cache(maxsize=None)
def load_config(name: str) -> dict[str, Any]:
    """Load config/<name> (e.g. 'train.yaml'). Cached; call load_config.cache_clear() to reload."""
    for d in _config_search_dirs():
        path = d / name
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    searched = " | ".join(str(d) for d in _config_search_dirs())
    raise FileNotFoundError(f"config '{name}' not found (searched: {searched})")


def load_yaml(path: "str | Path") -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_path(rel: str) -> Path:
    """Resolve a repo-relative path (as stored in data.yaml) to an absolute Path."""
    p = Path(rel)
    return p if p.is_absolute() else repo_root() / p
