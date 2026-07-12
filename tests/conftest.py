"""Shared test fixtures.

Adds the ``lambda/`` directory to ``sys.path`` so tests can import ``lms`` and
``actions`` directly, and provides a scriptable fake transport that mimics the
LMS JSON-RPC server without any network access.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
LAMBDA_DIR = os.path.join(ROOT, "lambda")
LOCALVOICE_DIR = os.path.join(ROOT, "localvoice")
sys.path.insert(0, LAMBDA_DIR)
sys.path.insert(0, LOCALVOICE_DIR)

from lms import LMSClient, LMSError  # noqa: E402


class FakeTransport:
    """Records every call and returns canned results keyed by command name.

    Usage::

        t = FakeTransport()
        t.responses["search"] = {"tracks_loop": [...]}
        t.raise_on.add("pause")   # simulate a server error for one command
    """

    def __init__(self):
        self.calls = []  # list of (player_id, [cmd, arg, ...])
        self.responses = {}
        self.raise_on = set()

    def __call__(self, params):
        player, cmd = params[0], params[1]
        self.calls.append((player, list(cmd)))
        name = cmd[0]
        if name in self.raise_on:
            raise LMSError(f"simulated failure for {name}")
        result = self.responses.get(name, {})
        return result(cmd) if callable(result) else result

    # -- convenience assertions -------------------------------------------
    def last_call(self):
        return self.calls[-1]

    def commands(self):
        """All issued commands as lists, e.g. ['pause', '1']."""
        return [cmd for _player, cmd in self.calls]


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def make_tidal():
    """Factory for a fake TIDAL app-feed handler (3-level OPML navigation).

    Simulates the real plugin: home menu exposes a 'search' node; entering it
    with ``search:`` returns category nodes; entering a category id returns its
    items; and ``["tidal","playlist","play",...]`` is the container play action.

    Wire it up with::

        transport.responses["tidal"] = make_tidal(
            categories={"Songs": "S", "Artists": "A"},
            items={"S": [{"isaudio": 1, "url": "tidal://42.flc", "name": "Time"}]},
        )
    """

    def factory(search_node="7", categories=None, items=None):
        categories = categories or {}
        items = items or {}

        def handler(cmd):
            if len(cmd) > 1 and cmd[1] == "playlist":  # play_browse_item action
                return {}
            params = cmd[2:]
            item_id = None
            has_search = False
            for part in params:
                if part.startswith("item_id:"):
                    item_id = part[len("item_id:") :]
                elif part.startswith("search:"):
                    has_search = True
            if item_id is None:  # home menu -> search node
                return {"loop_loop": [{"id": search_node, "type": "search", "name": "Search"}]}
            if has_search:  # search node -> category list
                return {"loop_loop": [{"name": n, "id": i} for n, i in categories.items()]}
            return {"loop_loop": items.get(item_id, [])}  # category -> items

        return handler

    return factory


@pytest.fixture
def lms(transport):
    return LMSClient(
        base_url="http://lms.local:9000",
        player_id="aa:bb:cc:dd:ee:ff",
        transport=transport,
    )
