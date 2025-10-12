from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

_CATEGORY_RULES_CACHE: Dict[str, Dict[str, Any]] | None = None


def _default_rules_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "category_rules.json"


def load_category_profiles() -> Dict[str, Dict[str, Any]]:
    """Load category profiles from JSON configuration if available."""

    global _CATEGORY_RULES_CACHE
    if _CATEGORY_RULES_CACHE is not None:
        return _CATEGORY_RULES_CACHE

    env_path = os.getenv("CATEGORY_RULES_PATH")
    candidate_paths = []
    if env_path:
        candidate_paths.append(Path(env_path))
    candidate_paths.append(_default_rules_path())

    for path in candidate_paths:
        try:
            if path.is_file():
                with open(path, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    if isinstance(data, dict):
                        _CATEGORY_RULES_CACHE = data
                        return _CATEGORY_RULES_CACHE
        except Exception:
            continue

    _CATEGORY_RULES_CACHE = {}
    return _CATEGORY_RULES_CACHE
