"""Caché en disco muy simple (por día) para no saturar las fuentes gratuitas."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import pickle
from pathlib import Path

CACHE_DIR = Path(os.environ.get("DCFVAL_CACHE", Path.home() / ".cache" / "dcfval"))
ENABLED = os.environ.get("DCFVAL_NO_CACHE", "") == ""


def _path(key: str) -> Path:
    h = hashlib.sha1(key.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{dt.date.today().isoformat()}_{h}.pkl"


def get(key: str):
    if not ENABLED:
        return None
    p = _path(key)
    if p.exists():
        try:
            with p.open("rb") as f:
                return pickle.load(f)
        except Exception:
            return None
    return None


def put(key: str, value) -> None:
    if not ENABLED:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with _path(key).open("wb") as f:
            pickle.dump(value, f)
    except Exception:
        pass


def disable() -> None:
    global ENABLED
    ENABLED = False
