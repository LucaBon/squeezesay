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

from typing import List


class BlocklistStoreError(Exception):
    """Raised when the blocklist store cannot be written."""


class NoOpBlocklistStore:
    """Used when no persistence is configured: reads empty, refuses writes.

    Keeps the feature static-only (config baseline still works) instead of
    crashing when persistence isn't set up.
    """

    def get(self) -> List[str]:
        return []

    def put(self, terms: List[str]) -> None:
        raise BlocklistStoreError("blocklist persistence is not configured")
