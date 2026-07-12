"""Tests for the DynamoDB-backed blocklist store, using an in-memory fake
DynamoDB resource so no AWS or boto3 is needed. Verifies round-tripping, the
fail-open read policy, and the fail-loud write policy."""

import pytest

from blocklist_store import (
    BlocklistStore,
    BlocklistStoreError,
    NoOpBlocklistStore,
)


class FakeTable:
    def __init__(self, store, fail=False):
        self._store = store  # dict: key -> item
        self.fail = fail

    def get_item(self, Key):
        if self.fail:
            raise RuntimeError("simulated DynamoDB outage")
        item = self._store.get(Key["id"])
        return {"Item": item} if item is not None else {}

    def put_item(self, Item):
        if self.fail:
            raise RuntimeError("simulated DynamoDB outage")
        self._store[Item["id"]] = Item


class FakeResource:
    def __init__(self, fail=False):
        self.data = {}
        self.fail = fail

    def Table(self, name):
        return FakeTable(self.data, fail=self.fail)


def _store(resource):
    return BlocklistStore("tbl", resource=resource)


def test_get_empty_when_missing():
    assert _store(FakeResource()).get() == []


def test_put_then_get_roundtrip():
    store = _store(FakeResource())
    store.put(["Song X", "Some Singer"])
    assert store.get() == ["Song X", "Some Singer"]


def test_put_strips_and_drops_blanks():
    store = _store(FakeResource())
    store.put(["  Song X ", "", "   "])
    assert store.get() == ["Song X"]


def test_get_fails_open_on_error():
    # A storage outage must never break playback -> read returns [].
    assert _store(FakeResource(fail=True)).get() == []


def test_put_fails_loud_on_error():
    with pytest.raises(BlocklistStoreError):
        _store(FakeResource(fail=True)).put(["x"])


def test_requires_table_name():
    with pytest.raises(ValueError):
        BlocklistStore("", resource=FakeResource())


def test_noop_store_reads_empty_and_refuses_writes():
    store = NoOpBlocklistStore()
    assert store.get() == []
    with pytest.raises(BlocklistStoreError):
        store.put(["x"])
