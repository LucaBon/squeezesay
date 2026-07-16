"""Tests for the blocklist store contract: the no-op fallback reads empty and
refuses writes (fail-open reads / fail-loud writes)."""

import pytest

from blocklist_store import BlocklistStoreError, NoOpBlocklistStore


def test_noop_store_reads_empty_and_refuses_writes():
    store = NoOpBlocklistStore()
    assert store.get() == []
    with pytest.raises(BlocklistStoreError):
        store.put(["x"])
