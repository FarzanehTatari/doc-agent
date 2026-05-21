"""Tiny JSON-backed key/value store for session state.

Intended for short-lived bookkeeping: last-used model, cache hints, anything you
want available across runs but not worth a real database. NOT for secrets — the
file is plain text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SessionStore:
    """Key/value store persisted as JSON."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: dict[str, Any] = {}
        if self.path.exists():
            self.load()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def delete(self, key: str) -> bool:
        if key in self._data:
            del self._data[key]
            return True
        return False

    def keys(self) -> list[str]:
        return list(self._data.keys())

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def clear(self) -> None:
        self._data = {}

    def load(self) -> int:
        if not self.path.exists():
            return 0
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            self._data = {}
            return 0
        self._data = json.loads(raw)
        return len(self._data)

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        return self.path

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data
