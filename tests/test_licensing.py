"""Tests for the Pro license manager (localvoice/licensing.py).

The contract that matters commercially: activation caches locally and works
offline forever; the weekly revalidation downgrades ONLY on a definitive
``valid: false`` from Lemon Squeezy — never on network trouble; ``is_pro()``
never touches the network.
"""

import json
import urllib.request

import pytest

import appdata
from licensing import LicenseManager


class FakePost:
    """Scriptable http_post: queue outcomes per URL suffix."""

    def __init__(self):
        self.calls = []
        self.outcome = (200, {})

    def __call__(self, url, fields):
        self.calls.append((url, dict(fields)))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture
def post():
    return FakePost()


def mgr(tmp_path, post, now=lambda: 1_000_000, environ=None):
    return LicenseManager(str(tmp_path), api_base="https://ls.test/licenses",
                          http_post=post, now=now, environ=environ or {})


# -- activation ----------------------------------------------------------------

def test_activate_happy_path_writes_cache(tmp_path, post):
    post.outcome = (200, {"activated": True, "instance": {"id": "inst-1"}})
    m = mgr(tmp_path, post)
    assert m.activate("KEY-1234-ABCD") == {"ok": True}
    assert m.is_pro()
    cache = appdata.read_json(str(tmp_path / "license.json"))
    assert cache["key"] == "KEY-1234-ABCD"
    assert cache["instance_id"] == "inst-1"
    assert cache["revoked"] is False
    url, fields = post.calls[0]
    assert url.endswith("/activate")
    assert fields["license_key"] == "KEY-1234-ABCD"
    assert fields["instance_name"]  # hostname, whatever it is


def test_activate_invalid_key(tmp_path, post):
    post.outcome = (400, {"activated": False, "error": "license_key not found"})
    m = mgr(tmp_path, post)
    result = m.activate("WRONG")
    assert result["ok"] is False
    assert result["error"] == "invalid"
    assert "not found" in result["detail"]
    assert not m.is_pro()
    assert not (tmp_path / "license.json").exists()  # no partial state


def test_activate_network_down_leaves_no_state(tmp_path, post):
    post.outcome = OSError("dns failure")
    m = mgr(tmp_path, post)
    result = m.activate("KEY")
    assert result == {"ok": False, "error": "network", "detail": "dns failure"}
    assert not (tmp_path / "license.json").exists()


def test_activate_empty_key_rejected_without_network(tmp_path, post):
    m = mgr(tmp_path, post)
    assert m.activate("  ")["error"] == "invalid"
    assert post.calls == []


# -- is_pro / status ------------------------------------------------------------

def test_is_pro_env_bypass(tmp_path, post):
    env = {f"{appdata.PRIMARY_PREFIX}_PRO": "1"}
    assert mgr(tmp_path, post, environ=env).is_pro()
    assert post.calls == []  # pure local check


def test_status_masks_key(tmp_path, post):
    post.outcome = (200, {"activated": True, "instance": {"id": "i"}})
    m = mgr(tmp_path, post)
    m.activate("KEY-1234-ABCD")
    st = m.status()
    assert st["pro"] is True
    assert st["key"] == "****ABCD"
    assert "KEY-1234" not in json.dumps(st)


def test_status_unlicensed(tmp_path, post):
    st = mgr(tmp_path, post).status()
    assert st == {"pro": False, "key": None, "instance": None,
                  "activated_at": None, "revoked": False}


# -- revalidation ---------------------------------------------------------------

def _activated(tmp_path, post, at=1_000_000):
    post.outcome = (200, {"activated": True, "instance": {"id": "i-1"}})
    m = mgr(tmp_path, post, now=lambda: at)
    m.activate("KEY-1234-ABCD")
    post.calls.clear()
    return m


def test_revalidate_skipped_when_fresh(tmp_path, post):
    m = _activated(tmp_path, post)
    m.now = lambda: 1_000_000 + 3600  # an hour later
    assert m.revalidate_async() is None
    assert post.calls == []


def test_revalidate_network_error_keeps_pro(tmp_path, post):
    m = _activated(tmp_path, post)
    m.now = lambda: 1_000_000 + 8 * 24 * 3600  # stale
    post.outcome = OSError("offline")
    thread = m.revalidate_async()
    thread.join(5)
    assert m.is_pro()  # offline never bricks


def test_revalidate_definitive_invalid_revokes(tmp_path, post):
    m = _activated(tmp_path, post)
    m.now = lambda: 1_000_000 + 8 * 24 * 3600
    post.outcome = (400, {"valid": False, "error": "license_key disabled"})
    thread = m.revalidate_async()
    thread.join(5)
    assert not m.is_pro()
    assert m.status()["revoked"] is True
    url, fields = post.calls[0]
    assert url.endswith("/validate")
    assert fields["instance_id"] == "i-1"


def test_revalidate_valid_refreshes_timestamp(tmp_path, post):
    m = _activated(tmp_path, post)
    later = 1_000_000 + 8 * 24 * 3600
    m.now = lambda: later
    post.outcome = (200, {"valid": True})
    m.revalidate_async().join(5)
    cache = appdata.read_json(str(tmp_path / "license.json"))
    assert cache["last_validated"] == later
    # A fresh timestamp means the next startup doesn't re-check.
    assert m.revalidate_async() is None


def test_revalidate_opt_out(tmp_path, post):
    m = _activated(tmp_path, post)
    m.now = lambda: 1_000_000 + 30 * 24 * 3600
    m.environ = {f"{appdata.PRIMARY_PREFIX}_NO_REVALIDATE": "1"}
    assert m.revalidate_async() is None
    assert post.calls == []


# -- HTTP endpoints --------------------------------------------------------------

def test_license_endpoints(tmp_path, post, lms):
    import threading
    from http.server import ThreadingHTTPServer

    import server as srv

    post.outcome = (200, {"activated": True, "instance": {"id": "i"}})
    m = mgr(tmp_path, post)
    handler = srv.make_handler(lms, "http://lms.local:9000/material/",
                               ["tidal"], "tidal", license_mgr=m)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/license", timeout=5) as r:
            assert json.loads(r.read())["pro"] is False
        req = urllib.request.Request(
            base + "/license",
            data=json.dumps({"key": "KEY-1234-ABCD"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read())
        assert body["ok"] is True
        assert body["pro"] is True
        assert body["key"] == "****ABCD"
        with urllib.request.urlopen(base + "/license", timeout=5) as r:
            assert json.loads(r.read())["pro"] is True
    finally:
        httpd.shutdown()
