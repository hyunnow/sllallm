"""Shared .env loading (used by labeling and gold-draft scripts)."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV = "/Users/hyunwoo/Documents/gwatop/gwatop-backend/.env"


def load_env_key(env_file: str = DEFAULT_ENV, var: str = "OPENAI_API_KEY") -> bool:
    """Load one key from a .env file into the environment (never printed)."""
    if os.environ.get(var):
        return True
    p = Path(env_file)
    if not p.exists():
        return False
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{var}="):
            os.environ[var] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return True
    return False
