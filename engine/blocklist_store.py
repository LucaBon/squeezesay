"""Persistent, voice-editable kid-safe blocklist.

The parent can add/remove blocked songs or singers by voice; the terms must
survive restarts, so they live in a small persistent store shared by the whole
household. The concrete backend is injectable (the web app plugs in a local
JSON-file store); this module defines the contract and the no-op fallback.

Failure policy:
* **Reads fail open** — any error returns an empty list, so a storage hiccup
  degrades to the config baseline and never blocks music playback.
* **Writes fail loud** — they raise :class:`BlocklistStoreError` so the voice
  command can tell the user the change wasn't saved.
"""

from __future__ import annotations

import json
import os
from typing import List


class BlocklistStoreError(Exception):
    """Raised when the blocklist store cannot be written."""


class JsonBlocklistStore:
    """Terms persisted in a local JSON file, under the ``terms`` key.

    The file may carry other state alongside (the web kid-safe feature keeps
    its PIN and enabled flag there): reads and writes touch only ``terms``,
    preserving everything else. Writes are atomic (tmp + ``os.replace``).
    """

    def __init__(self, path: str) -> None:
        if not path:
            raise ValueError("path is required")
        self.path = path

    def _read_state(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self) -> List[str]:
        """Return the stored terms, or ``[]`` on any error (fail open)."""
        terms = self._read_state().get("terms") or []
        return [str(t).strip() for t in terms if str(t).strip()]

    def put(self, terms: List[str]) -> None:
        """Overwrite the stored terms. Raises on failure so callers can report it."""
        clean = [str(t).strip() for t in (terms or []) if str(t).strip()]
        state = self._read_state()
        state["terms"] = clean
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError as exc:
            raise BlocklistStoreError(f"blocklist write failed: {exc}") from exc


class NoOpBlocklistStore:
    """Used when no persistence is configured: reads empty, refuses writes.

    Keeps the feature static-only (config baseline still works) instead of
    crashing when persistence isn't set up.
    """

    def get(self) -> List[str]:
        return []

    def put(self, terms: List[str]) -> None:
        raise BlocklistStoreError("blocklist persistence is not configured")
