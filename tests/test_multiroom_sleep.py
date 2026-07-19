"""Multi-room targeting (Pro, ``localvoice/pro/multiroom.py``), sleep timer,
and mini-player volume.

Engine (AGPL): ``for_player`` / ``volume_set`` / ``sleep`` / volume in
``status_info`` — mechanisms only. The multi-room *feature* (room-phrase
extraction, fuzzy player matching, license gate) lives in the proprietary
``pro/multiroom.py`` and reaches the AGPL router/server as an injected object,
exactly like kid-safe.
Server: ``/players``, per-player ``/command`` · ``/player`` · ``/nowplaying``,
the mini-player ``volume`` action, and the Pro gate on all of it.
"""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import server as srv
from pro.multiroom import MultiRoom
from router import Router


class FakeLicense:
    """Just enough of LicenseManager for the multi-room Pro gate."""

    def __init__(self, pro=True):
        self.pro = pro

    def is_pro(self):
        return self.pro

    def status(self):
        return {"pro": self.pro}


PLAYERS = [
    {"playerid": "aa:aa", "name": "Salotto"},
    {"playerid": "bb:bb", "name": "Cucina"},
]


# -- engine: per-player client, volume, sleep ---------------------------------

def test_for_player_returns_retargeted_clone(lms):
    clone = lms.for_player("11:22:33:44:55:66")
    assert clone is not lms
    assert clone.player_id == "11:22:33:44:55:66"
    assert clone.base_url == lms.base_url
    assert lms.player_id == "aa:bb:cc:dd:ee:ff"  # the original is untouched


def test_for_player_same_or_empty_returns_self(lms):
    assert lms.for_player("aa:bb:cc:dd:ee:ff") is lms
    assert lms.for_player("") is lms
    assert lms.for_player(None) is lms


def test_for_player_commands_reach_that_player(lms, transport):
    lms.for_player("11:22").pause()
    assert transport.last_call() == ("11:22", ["pause", "1"])


def test_volume_set_clamps_to_0_100(lms, transport):
    lms.volume_set(140)
    assert transport.last_call()[1] == ["mixer", "volume", "100"]
    lms.volume_set(-3)
    assert transport.last_call()[1] == ["mixer", "volume", "0"]


def test_sleep_command_and_cancel(lms, transport):
    lms.sleep(1800)
    assert transport.last_call()[1] == ["sleep", "1800"]
    lms.sleep(0)
    assert transport.last_call()[1] == ["sleep", "0"]


def test_status_info_carries_volume(lms, transport):
    transport.responses["status"] = {
        "mode": "play", "mixer volume": 40,
        "playlist_loop": [{"title": "Time"}],
    }
    assert lms.status_info()["volume"] == 40


def test_status_info_muted_negative_volume_reads_zero(lms, transport):
    transport.responses["status"] = {
        "mode": "play", "mixer volume": -40,
        "playlist_loop": [{"title": "Time"}],
    }
    assert lms.status_info()["volume"] == 0


def test_status_info_missing_volume_is_none(lms, transport):
    transport.responses["status"] = {"mode": "stop"}
    assert lms.status_info()["volume"] is None


# -- router: sleep timer ------------------------------------------------------

@pytest.fixture
def router(lms):
    return Router(lms)


@pytest.mark.parametrize(
    "phrase, seconds",
    [
        ("spegni tra 30 minuti", "1800"),
        ("spegniti fra 10 minuti", "600"),
        ("stop tra trenta minuti", "1800"),
        ("spegni tra mezz'ora", "1800"),
        ("ferma la musica tra un'ora", "3600"),
    ],
)
def test_sleep_phrases_it(router, transport, phrase, seconds):
    router.handle(phrase)
    assert transport.last_call()[1] == ["sleep", seconds]


@pytest.mark.parametrize(
    "phrase, seconds",
    [
        ("stop in 30 minutes", "1800"),
        ("sleep in half an hour", "1800"),
        ("turn off in an hour", "3600"),
        ("switch off in twenty minutes", "1200"),
    ],
)
def test_sleep_phrases_en(router, transport, phrase, seconds):
    router.handle(phrase, lang="en")
    assert transport.last_call()[1] == ["sleep", seconds]


def test_sleep_reply_says_minutes(router, transport):
    assert router.handle("spegni tra 30 minuti") == "Va bene, spengo tra 30 minuti."


def test_sleep_cancel_it(router, transport):
    assert router.handle("annulla il timer") == "Timer di spegnimento annullato."
    assert transport.last_call()[1] == ["sleep", "0"]


def test_sleep_cancel_en(router, transport):
    assert router.handle("cancel the sleep timer", lang="en") == "Sleep timer cancelled."
    assert transport.last_call()[1] == ["sleep", "0"]


def test_stop_without_duration_still_pauses(router, transport):
    router.handle("stop")
    assert transport.last_call()[1] == ["pause", "1"]


def test_play_title_with_duration_is_not_a_sleep(router, transport, make_tidal):
    # A play command stays a play even when it ends like a duration.
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://9.flc",
                      "name": "Meet Me in 10 Minutes"}]},
    )
    router.handle("play Meet Me in 10 minutes", lang="en", source="tidal")
    assert ["sleep", "600"] not in transport.commands()


# -- pro/multiroom: room targeting («in cucina») ------------------------------

def make_multiroom(pro=True, players=PLAYERS):
    """A MultiRoom over a static player list; pro=None means no license
    infrastructure at all (always gated)."""
    return MultiRoom(FakeLicense(pro) if pro is not None else None,
                     lambda: players)


@pytest.fixture
def room_router(lms):
    return Router(lms, multiroom=make_multiroom(pro=True))


def test_room_suffix_targets_that_player(room_router, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://42.flc", "name": "Time"}]},
    )
    reply = room_router.handle("metti Time in cucina", source="tidal")
    assert str(reply) == "Riproduco Time da TIDAL in Cucina."
    assert ("bb:bb", ["playlist", "play", "tidal://42.flc"]) in transport.calls


def test_room_prefix_targets_that_player(room_router, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://42.flc", "name": "Time"}]},
    )
    room_router.handle("in cucina metti Time", source="tidal")
    assert ("bb:bb", ["playlist", "play", "tidal://42.flc"]) in transport.calls


def test_room_transport_command(room_router, transport):
    reply = room_router.handle("pausa in salotto")
    assert ("aa:aa", ["pause", "1"]) in transport.calls
    assert str(reply) == "In pausa in Salotto."


def test_room_english_with_article(lms, transport):
    kitchen = Router(lms, multiroom=make_multiroom(
        players=[{"playerid": "kk:kk", "name": "Kitchen"},
                 {"playerid": "ll:ll", "name": "Living Room"}]))
    kitchen.handle("pause in the kitchen", lang="en")
    assert ("kk:kk", ["pause", "1"]) in transport.calls


def test_title_containing_in_is_not_hijacked(room_router, transport, make_tidal):
    # "America" names no player: the phrase stays a title on the default player.
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://7.flc",
                      "name": "Breakfast in America"}]},
    )
    room_router.handle("metti Breakfast in America", source="tidal")
    assert ["playlist", "play", "tidal://7.flc"] in transport.commands()
    assert all(player == "aa:bb:cc:dd:ee:ff" for player, _cmd in transport.calls)


def test_room_list_then_pick_stays_in_the_room(room_router, transport):
    transport.responses["artists"] = {"artists_loop": [{"id": 1, "artist": "Yes"}]}
    transport.responses["albums"] = {
        "albums_loop": [{"id": 10, "album": "Fragile"}, {"id": 11, "album": "90125"}]
    }
    room_router.handle("quali album ho di Yes in cucina")
    reply = room_router.handle("metti la 2")
    assert ("bb:bb", ["playlistcontrol", "cmd:load", "album_id:11"]) in transport.calls
    assert str(reply) == "Riproduco 90125 dalla tua musica in Cucina."


def test_fresh_list_without_room_forgets_the_room(room_router, transport):
    transport.responses["artists"] = {"artists_loop": [{"id": 1, "artist": "Yes"}]}
    transport.responses["albums"] = {
        "albums_loop": [{"id": 10, "album": "Fragile"}, {"id": 11, "album": "90125"}]
    }
    room_router.handle("quali album ho di Yes in cucina")
    room_router.handle("quali album ho di Yes")  # re-opened without a room
    room_router.handle("metti la 1")
    picks = [c for c in transport.calls if c[1][:2] == ["playlistcontrol", "cmd:load"]]
    assert picks[-1][0] == "aa:bb:cc:dd:ee:ff"


def test_room_targeting_is_pro_gated(lms, transport):
    # No license infrastructure: a room-targeted command gets the Pro pitch
    # and nothing reaches the LMS.
    free = Router(lms, multiroom=make_multiroom(pro=None))
    reply = free.handle("metti Time in cucina")
    assert reply == ("Questa è una funzione Pro: si attiva dalle "
                     "impostazioni della pagina.")
    assert transport.calls == []


def test_room_targeting_gated_on_revoked_license(lms, transport):
    revoked = Router(lms, multiroom=make_multiroom(pro=False))
    reply = revoked.handle("pausa in cucina")
    assert "Pro" in str(reply)
    assert transport.calls == []


def test_no_multiroom_module_means_no_room_parsing(lms, transport, make_tidal):
    # Without the pro module injected, the router owns zero room logic: the
    # phrase is just a (failing) search, never a Pro pitch.
    transport.responses["tidal"] = make_tidal(categories={}, items={})
    plain = Router(lms)
    reply = plain.handle("metti Time in cucina", source="tidal")
    assert "Pro" not in str(reply)


# -- server: /players, per-player endpoints, volume ---------------------------

class FakeArtworkFetch:
    def __call__(self, url, timeout=5.0):
        return "image/png", b"PNGDATA"


def _serve(lms, license_mgr):
    multiroom = MultiRoom(license_mgr, lms.get_players)
    handler = srv.make_handler(lms, "http://lms.local:9000/material/",
                               ["tidal"], "tidal",
                               artwork_fetch=FakeArtworkFetch(),
                               license_mgr=license_mgr, multiroom=multiroom)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


@pytest.fixture
def http_server(lms):
    """The handler with an active Pro license (multi-room unlocked)."""
    httpd, base = _serve(lms, FakeLicense(pro=True))
    try:
        yield base
    finally:
        httpd.shutdown()


@pytest.fixture
def http_server_free(lms):
    """The handler with no license: multi-room must be inert."""
    httpd, base = _serve(lms, None)
    try:
        yield base
    finally:
        httpd.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def test_players_endpoint(http_server, transport):
    transport.responses["players"] = {"players_loop": PLAYERS}
    status, data = _get(http_server + "/players")
    assert status == 200
    assert data == {
        "ok": True, "pro": True, "current": "aa:bb:cc:dd:ee:ff",
        "players": [{"id": "aa:aa", "name": "Salotto"},
                    {"id": "bb:bb", "name": "Cucina"}],
    }


def test_players_endpoint_lms_down_is_not_500(http_server, transport):
    transport.raise_on.add("players")
    status, data = _get(http_server + "/players")
    assert status == 200
    assert data == {"ok": False, "players": []}


PLAYING = {
    "mode": "play", "time": 10, "mixer volume": 40,
    "playlist_loop": [{"title": "Time", "artist": "Pink Floyd",
                       "coverid": "ab12cd", "duration": 421}],
}


def test_nowplaying_honours_player_param(http_server, transport):
    transport.responses["status"] = PLAYING
    status, data = _get(http_server + "/nowplaying?player=bb%3Abb")
    assert status == 200
    assert data["volume"] == 40
    # The status query ran against the requested player, and the artwork URL
    # keeps pointing the proxy at it.
    assert ("bb:bb", ["status", "-", "1", "tags:aAlKcdJ"]) in transport.calls
    assert "player=bb%3Abb" in data["artwork"]


def test_player_volume_action(http_server, transport):
    transport.responses["status"] = PLAYING
    status, data = _post(http_server + "/player",
                         {"action": "volume", "value": 55, "player": "bb:bb"})
    assert status == 200
    assert data["ok"] is True
    assert ("bb:bb", ["mixer", "volume", "55"]) in transport.calls


def test_command_routes_to_the_selected_player(http_server, transport):
    status, data = _post(http_server + "/command",
                         {"text": "pausa", "client": "c1", "player": "bb:bb"})
    assert status == 200
    assert data["speech"] == "In pausa."
    assert ("bb:bb", ["pause", "1"]) in transport.calls


# -- server: the multi-room Pro gate ------------------------------------------

def test_free_tier_player_param_is_ignored(http_server_free, transport):
    transport.responses["status"] = PLAYING
    _post(http_server_free + "/player", {"action": "pause", "player": "bb:bb"})
    assert ("aa:bb:cc:dd:ee:ff", ["pause", "1"]) in transport.calls
    assert all(player != "bb:bb" for player, _cmd in transport.calls)


def test_free_tier_command_player_is_ignored(http_server_free, transport):
    _post(http_server_free + "/command",
          {"text": "pausa", "client": "c1", "player": "bb:bb"})
    assert ("aa:bb:cc:dd:ee:ff", ["pause", "1"]) in transport.calls
    assert all(player != "bb:bb" for player, _cmd in transport.calls)


def test_free_tier_voice_room_gets_the_pro_pitch(http_server_free, transport):
    transport.responses["players"] = {"players_loop": PLAYERS}
    status, data = _post(http_server_free + "/command",
                         {"text": "metti Time in cucina", "client": "c1"})
    assert status == 200
    assert "Pro" in data["speech"]
    assert all(cmd[0] != "playlist" for _p, cmd in transport.calls)


def test_free_tier_players_endpoint_reports_pro_false(http_server_free, transport):
    transport.responses["players"] = {"players_loop": PLAYERS}
    _status, data = _get(http_server_free + "/players")
    assert data["ok"] is True
    assert data["pro"] is False
