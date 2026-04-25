"""In-memory datastore. Loads JSON seed files on startup.

Swap this module for Postgres/Redis when moving to production — every router
goes through `store.get(collection)` so the call-sites won't change.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_DATA_DIR = Path(os.environ.get("TERP_DATA_DIR", Path(__file__).parent.parent / "data"))
_lock = threading.RLock()
_db: dict[str, Any] = {}


def _load() -> None:
    global _db
    with _lock:
        if _db:
            return
        for path in _DATA_DIR.glob("*.json"):
            with open(path) as f:
                _db[path.stem] = json.load(f)


def get(collection: str) -> Any:
    _load()
    return _db.get(collection, [])


def find(collection: str, **filters: Any) -> list[dict]:
    items = get(collection)
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if all(it.get(k) == v for k, v in filters.items()):
            out.append(it)
    return out


def find_one(collection: str, id_: str, id_field: str = "id") -> dict | None:
    for it in get(collection):
        if it.get(id_field) == id_:
            return it
    return None


def append(collection: str, item: dict) -> dict:
    _load()
    with _lock:
        _db.setdefault(collection, []).append(item)
    return item


def update_one(collection: str, id_: str, patch: dict, id_field: str = "id") -> dict | None:
    _load()
    with _lock:
        for it in _db.get(collection, []):
            if it.get(id_field) == id_:
                it.update(patch)
                return it
    return None
