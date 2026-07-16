"""Kid-safe on the web app: JSON store, PIN + unlock window, router guard
plumbing, voice management intents, and the fail-safe policy (a revoked
license keeps ENFORCING an enabled blocklist; it only locks changes)."""

import json

import pytest

import actions
from blocklist_store import BlocklistStoreError, JsonBlocklistStore
from messages import set_lang
from pro.kidsafe import KidSafe, LOCKOUT_SECONDS, MAX_ATTEMPTS, UNLOCK_SECONDS
from router import Router


@pytest.fixture(autouse=True)
def _reset_lang():
    yield
    set_lang("it")  # never leak the language into other test modules


class FakeLicense:
    def __init__(self, pro=True):
        self.pro = pro

    def is_pro(self):
        return self.pro


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def ks(tmp_path, clock):
    return KidSafe(str(tmp_path), FakeLicense(pro=True), now=clock)


# -- JsonBlocklistStore ---------------------------------------------------------

def test_store_roundtrip_preserves_other_keys(tmp_path):
    path = str(tmp_path / "kidsafe.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"enabled": True, "pin": {"salt": "aa", "hash": "bb"}}, f)
    store = JsonBlocklistStore(path)
    assert store.get() == []
    store.put(["Song X", "  Some Singer "])
    assert store.get() == ["Song X", "Some Singer"]
    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    assert state["enabled"] is True  # untouched
    assert state["pin"]["salt"] == "aa"


def test_store_fails_open_on_corrupt_file(tmp_path):
    path = tmp_path / "kidsafe.json"
    path.write_text("{not json", encoding="utf-8")
    assert JsonBlocklistStore(str(path)).get() == []


def test_store_fails_loud_on_unwritable_path(tmp_path):
    store = JsonBlocklistStore(str(tmp_path / "no-such-dir" / "kidsafe.json"))
    with pytest.raises(BlocklistStoreError):
        store.put(["x"])


# -- PIN / unlock window ---------------------------------------------------------

def test_enable_first_run_sets_pin_and_unlocks(ks):
    assert ks.enable("1234", "phoneA") == {"ok": True}
    assert ks.enabled()
    assert ks.has_pin()
    assert ks.is_unlocked("phoneA")
    assert not ks.is_unlocked("phoneB")


def test_enable_rejects_short_pin(ks):
    assert ks.enable("12", "c")["error"] == "pin_too_short"
    assert not ks.enabled()


def test_enable_later_requires_the_pin(ks):
    ks.enable("1234", "a")
    ks.disable("a")
    assert ks.enable("9999", "a")["error"] == "wrong_pin"
    assert ks.enable("1234", "a")["ok"]


def test_unlock_expires(ks, clock):
    ks.enable("1234", "a")
    ks.lock("a")
    assert ks.unlock("a", "1234")
    clock.t += UNLOCK_SECONDS + 1
    assert not ks.is_unlocked("a")


def test_wrong_pin_backoff(ks, clock):
    ks.enable("1234", "a")
    for _ in range(MAX_ATTEMPTS):
        assert not ks.unlock("kid", "0000")
    # Even the RIGHT pin is refused during the lockout window.
    assert not ks.unlock("kid", "1234")
    clock.t += LOCKOUT_SECONDS + 1
    assert ks.unlock("kid", "1234")


def test_disable_requires_unlock(ks, clock):
    ks.enable("1234", "a")
    clock.t += UNLOCK_SECONDS + 1
    assert ks.disable("a")["error"] == "locked"
    ks.unlock("a", "1234")
    assert ks.disable("a")["ok"]
    assert not ks.enabled()


# -- fail-safe: revoked license --------------------------------------------------

def test_revoked_license_keeps_enforcing_but_locks_changes(tmp_path, clock):
    lic = FakeLicense(pro=True)
    ks = KidSafe(str(tmp_path), lic, now=clock)
    ks.enable("1234", "a")
    ks.edit_terms("add", "Bad Song", "a")
    lic.pro = False  # refund/revoke after setup
    # Enforcement continues for a locked client...
    guard = ks.guard_for("kid")
    assert guard is not None and guard.blocks("Bad Song")
    # ...but configuration is refused.
    ks.unlock("a", "1234")
    assert ks.edit_terms("add", "Other", "a")["error"] == "pro_required"
    assert ks.disable("a")["error"] == "pro_required"


# -- guard through the router -----------------------------------------------------

@pytest.fixture
def guarded_router(lms, tmp_path, clock):
    ks = KidSafe(str(tmp_path), FakeLicense(pro=True), now=clock)
    ks.enable("1234", "parent")
    ks.edit_terms("add", "Bad Song", "parent")
    router = Router(lms, kidsafe=ks, client_id="kid")
    return router, ks


def test_blocked_term_refused_for_locked_client_it(guarded_router, transport):
    router, _ks = guarded_router
    reply = router.handle("metti Bad Song")
    assert str(reply) == actions.msg("blocked")
    assert all(cmd[0] != "playlist" for cmd in transport.commands())


def test_blocked_term_refused_for_locked_client_en(guarded_router, transport):
    router, _ks = guarded_router
    reply = router.handle("play Bad Song", lang="en")
    assert "not suitable" in str(reply)
    assert all(cmd[0] != "playlist" for cmd in transport.commands())


def test_unlocked_client_plays_blocked_term(guarded_router, transport, make_tidal):
    router, ks = guarded_router
    ks.unlock("kid", "1234")
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://9.flc", "name": "Bad Song"}]},
    )
    router.handle("metti Bad Song", source="tidal")
    assert ["playlist", "play", "tidal://9.flc"] in transport.commands()


def test_unlock_expiry_relocks_the_router(guarded_router, transport, clock):
    router, ks = guarded_router
    ks.unlock("kid", "1234")
    clock.t += UNLOCK_SECONDS + 1
    reply = router.handle("metti Bad Song")
    assert str(reply) == actions.msg("blocked")


def test_router_without_kidsafe_unchanged(lms, transport, make_tidal):
    # The default (kidsafe=None) keeps the old behavior byte-for-byte.
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://1.flc", "name": "Bad Song"}]},
    )
    Router(lms).handle("metti Bad Song", source="tidal")
    assert ["playlist", "play", "tidal://1.flc"] in transport.commands()


# -- voice management intents ------------------------------------------------------

def test_voice_block_requires_pro(lms, tmp_path, clock):
    ks = KidSafe(str(tmp_path), FakeLicense(pro=False), now=clock)
    router = Router(lms, kidsafe=ks, client_id="a")
    assert "Pro" in str(router.handle("blocca Bad Song"))


def test_voice_block_requires_unlock(guarded_router):
    router, _ks = guarded_router  # client "kid" is locked
    assert str(router.handle("blocca Altro")) == actions.msg("not_owner")


def test_voice_block_add_remove_list(guarded_router):
    router, ks = guarded_router
    ks.unlock("kid", "1234")
    assert "Altro" in str(router.handle("blocca Altro"))
    assert "Altro" in ks.terms()
    listing = str(router.handle("quali brani sono bloccati"))
    assert "Bad Song" in listing and "Altro" in listing
    assert "Altro" in str(router.handle("sblocca Altro"))
    assert "Altro" not in ks.terms()


def test_voice_block_en(guarded_router):
    router, ks = guarded_router
    ks.unlock("kid", "1234")
    assert "Thing" in str(router.handle("block Thing", lang="en"))
    listing = str(router.handle("what songs are blocked", lang="en"))
    assert "Thing" in listing
    assert "Thing" in str(router.handle("unblock Thing", lang="en"))


def test_block_titles_still_play(guarded_router, transport, make_tidal):
    # "metti Block Rockin' Beats" contains "block*" words but is a play.
    router, ks = guarded_router
    ks.unlock("kid", "1234")
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://7.flc",
                      "name": "Block Rockin' Beats"}]},
    )
    router.handle("metti Block Rockin' Beats", source="tidal")
    assert ["playlist", "play", "tidal://7.flc"] in transport.commands()
    router.handle("play Block Rockin' Beats", source="tidal", lang="en")
    assert transport.commands().count(["playlist", "play", "tidal://7.flc"]) == 2


# -- HTTP endpoints -----------------------------------------------------------------

def test_kidsafe_http_flow(lms, tmp_path, clock):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    import server as srv

    ks = KidSafe(str(tmp_path), FakeLicense(pro=True), now=clock)
    handler = srv.make_handler(lms, "http://lms.local:9000/material/",
                               ["tidal"], "tidal", kidsafe=ks)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def get(path):
        with urllib.request.urlopen(base + path, timeout=5) as r:
            return json.loads(r.read())

    def post(payload):
        req = urllib.request.Request(
            base + "/kidsafe", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    try:
        state = get("/kidsafe?client=parent")
        assert state == {"pro": True, "enabled": False, "haspin": False,
                         "locked": True}
        assert post({"client": "parent", "action": "enable",
                     "pin": "1234"})["enabled"] is True
        added = post({"client": "parent", "action": "add", "term": "Bad Song"})
        assert added["ok"] and added["terms"] == ["Bad Song"]
        # A locked client never sees the terms.
        assert "terms" not in get("/kidsafe?client=kid")
        # Wrong pin -> still locked.
        wrong = post({"client": "kid", "action": "unlock", "pin": "0000"})
        assert wrong["ok"] is False and wrong["locked"] is True
        ok = post({"client": "kid", "action": "unlock", "pin": "1234"})
        assert ok["ok"] is True and ok["terms"] == ["Bad Song"]
        # And the genuine server-side enforcement: a hand-crafted /command
        # with a blocked term is refused for a locked client.
        req = urllib.request.Request(
            base + "/command",
            data=json.dumps({"text": "metti Bad Song",
                             "client": "other-kid"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            reply = json.loads(r.read())
        assert reply["ok"] is False
        assert reply["speech"] == actions.msg("blocked")
    finally:
        httpd.shutdown()
