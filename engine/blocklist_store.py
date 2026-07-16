"""Persistent, voice-editable kid-safe blocklist, backed by DynamoDB.

The owner can add/remove blocked songs or singers by voice; the terms must
survive across Lambda invocations, so they live in a single shared DynamoDB item
(one row for the whole household) rather than in static config.

Design mirrors :class:`lms.LMSClient`: the AWS resource is **injectable**, so the
whole store is unit-testable without any network or ``boto3`` install (tests pass
a small in-memory fake). On real AWS (Alexa-hosted or own Lambda) ``boto3`` is
already present in the runtime, so there is no extra bundled dependency.

Failure policy:
* **Reads fail open** — any error returns an empty list, so a storage hiccup
  degrades to the config baseline and never blocks music playback.
* **Writes fail loud** — they raise :class:`BlocklistStoreError` so the voice
  command can tell the user the change wasn't saved.
"""

from __future__ import annotations

from typing import Any, List, Optional

DEFAULT_KEY = "kidsafe_blocklist"


class BlocklistStoreError(Exception):
    """Raised when the blocklist store cannot be written."""


class BlocklistStore:
    """DynamoDB-backed list of blocked terms stored under a single fixed key.

    The Alexa-hosted table uses a string partition key named ``id``; the item
    shape is ``{"id": "<key>", "terms": ["...", ...]}``.
    """

    def __init__(
        self,
        table_name: str,
        key: str = DEFAULT_KEY,
        region: Optional[str] = None,
        resource: Optional[Any] = None,
    ) -> None:
        if not table_name:
            raise ValueError("table_name is required")
        self.table_name = table_name
        self.key = key
        self.region = region
        self._resource = resource
        self._table = None

    def _get_table(self):
        if self._table is None:
            resource = self._resource
            if resource is None:
                import boto3  # lazy: only needed on real AWS

                # On Alexa-hosted the table may live in a specific region
                # (DYNAMODB_PERSISTENCE_REGION); honor it when given.
                resource = (
                    boto3.resource("dynamodb", region_name=self.region)
                    if self.region
                    else boto3.resource("dynamodb")
                )
            self._table = resource.Table(self.table_name)
        return self._table

    def get(self) -> List[str]:
        """Return the stored terms, or ``[]`` on any error (fail open)."""
        try:
            resp = self._get_table().get_item(Key={"id": self.key})
        except Exception:  # pragma: no cover - defensive: never break playback
            return []
        item = (resp or {}).get("Item") or {}
        terms = item.get("terms") or []
        return [str(t).strip() for t in terms if str(t).strip()]

    def put(self, terms: List[str]) -> None:
        """Overwrite the stored terms. Raises on failure so callers can report it."""
        clean = [str(t).strip() for t in (terms or []) if str(t).strip()]
        try:
            self._get_table().put_item(Item={"id": self.key, "terms": clean})
        except Exception as exc:
            raise BlocklistStoreError(f"blocklist write failed: {exc}") from exc


class NoOpBlocklistStore:
    """Used when no table is configured: reads empty, refuses writes.

    Keeps the feature static-only (config baseline still works) instead of
    crashing when persistence isn't set up.
    """

    def get(self) -> List[str]:
        return []

    def put(self, terms: List[str]) -> None:
        raise BlocklistStoreError("blocklist persistence is not configured")
