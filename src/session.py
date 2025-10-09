from __future__ import annotations
import json, os
from typing import Any, Dict, Optional

STATE_FILE = "/var/lib/das/state.json"
CREDS_DIR = "/var/lib/das/creds"

os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
os.makedirs(CREDS_DIR, exist_ok=True)

# ---- state helpers ----

def _state_load() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _state_save(data: Dict[str, Any]):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)

def state_set(key: str, payload: Dict[str, Any]):
    data = _state_load()
    data[key] = payload
    _state_save(data)

def state_get(key: str) -> Optional[Dict[str, Any]]:
    return _state_load().get(key)

# ---- credentials helpers ----

def creds_path(key: str) -> str:
    safe = "".join(c for c in key if c.isalnum() or c in ("-", "_"))[:100]
    return os.path.join(CREDS_DIR, f"{safe}.json")

def creds_save(key: str, creds_json: str):
    with open(creds_path(key), "w", encoding="utf-8") as f:
        f.write(creds_json)

def creds_load(key: str) -> Optional[str]:
    p = creds_path(key)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return f.read()
