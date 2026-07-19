"""Now-playing: the ``status_info()`` engine query and the web endpoints.

``/nowplaying`` must answer 200 with ``mode: unknown`` when the LMS is down
(the panel hides; no error spam), and ``/artwork`` is a server-side proxy —
the page is HTTPS while the LMS is HTTP, so a direct <img> would be blocked
as mixed content. The proxy derives the artwork URL from the player status
itself (no client-supplied URL = no open relay).
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import server as srv


# -- status_info() ------------------------------------------------------------

def test_status_info_local_track_uses_coverid(lms, transport):
    transport.responses["status"] = {
        "mode": "play", "time": 42.5,
        "playlist_loop": [{"title": "Time", "artist": "Pink Floyd",
                           "album": "The Dark Side of the Moon",
                           "coverid": "ab12cd", "duration": 421}],
    }
    info = lms.status_info()
    assert info["mode"] == "play"
    assert info["title"] == "Time"
    assert info["artist"] == "Pink Floyd"
    assert info["album"] == "The Dark Side of the Moon"
    assert info["elapsed"] == 42.5
    assert info["duration"] == 421
    assert info["artwork"] == "/music/ab12cd/cover.jpg"


def test_status_info_remote_track_keeps_absolute_artwork_url(lms, transport):
    transport.responses["status"] = {
        "mode": "play",
        "playlist_loop": [{"title": "Song", "artist": "X",
                           "artwork_url": "https://images.example/cover.jpg"}],
    }
    assert lms.status_info()["artwork"] == "https://images.example/cover.jpg"


def test_status_info_relative_artwork_url_gets_leading_slash(lms, transport):
    transport.responses["status"] = {
        "mode": "play",
        "playlist_loop": [{"title": "Song",
                           "artwork_url": "imageproxy/abc/image.jpg"}],
    }
    assert lms.status_info()["artwork"] == "/imageproxy/abc/image.jpg"


def test_status_info_track_without_cover_falls_back_to_current(lms, transport):
    transport.responses["status"] = {
        "mode": "pause",
        "playlist_loop": [{"title": "Song"}],
    }
    info = lms.status_info()
    assert info["mode"] == "pause"
    assert info["artwork"] == "/music/current/cover.jpg?player=aa:bb:cc:dd:ee:ff"


def test_status_info_empty_playlist(lms, transport):
    transport.responses["status"] = {"mode": "stop"}
    info = lms.status_info()
    assert info["mode"] == "stop"
    assert info["title"] is None
    assert info["artwork"] is None


# -- HTTP endpoints -----------------------------------------------------------

class FakeArtworkFetch:
    def __init__(self):
        self.urls = []

    def __call__(self, url, timeout=5.0):
        self.urls.append(url)
        return "image/png", b"PNGDATA"


@pytest.fixture
def http_server(lms):
    """The real handler on an ephemeral port, with an injectable artwork fetch."""
    fetch = FakeArtworkFetch()
    handler = srv.make_handler(lms, "http://lms.local:9000/material/",
                               ["tidal"], "tidal", artwork_fetch=fetch)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, fetch
    finally:
        httpd.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, dict(resp.headers), resp.read()


def test_nowplaying_endpoint(http_server, transport):
    base, _ = http_server
    transport.responses["status"] = {
        "mode": "play", "time": 10,
        "playlist_loop": [{"title": "Time", "artist": "Pink Floyd",
                           "coverid": "ab12cd", "duration": 421}],
    }
    status, _headers, body = _get(base + "/nowplaying")
    data = json.loads(body)
    assert status == 200
    assert data["title"] == "Time"
    # The client never sees the LMS URL: artwork points back at the proxy,
    # with a per-track cache-buster.
    assert data["artwork"].startswith("/artwork?v=")


def test_nowplaying_lms_down_answers_unknown_not_500(http_server, transport):
    base, _ = http_server
    transport.raise_on.add("status")
    status, _headers, body = _get(base + "/nowplaying")
    assert status == 200
    assert json.loads(body) == {"mode": "unknown"}


def test_artwork_proxies_lms_relative_path(http_server, transport):
    base, fetch = http_server
    transport.responses["status"] = {
        "mode": "play",
        "playlist_loop": [{"title": "Time", "coverid": "ab12cd"}],
    }
    status, headers, body = _get(base + "/artwork?v=1")
    assert status == 200
    assert body == b"PNGDATA"
    assert headers["Content-Type"] == "image/png"
    assert headers["Cache-Control"] == "no-store"
    assert fetch.urls == ["http://lms.local:9000/music/ab12cd/cover.jpg"]


def test_artwork_proxies_absolute_plugin_url(http_server, transport):
    base, fetch = http_server
    transport.responses["status"] = {
        "mode": "play",
        "playlist_loop": [{"title": "Song",
                           "artwork_url": "https://images.example/c.jpg"}],
    }
    _get(base + "/artwork")
    assert fetch.urls == ["https://images.example/c.jpg"]


def test_artwork_404_when_nothing_plays(http_server, transport):
    base, _ = http_server
    transport.responses["status"] = {"mode": "stop"}
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(base + "/artwork")
    assert exc.value.code == 404


# -- /player (mini-player transport) ------------------------------------------

def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


PLAYING = {
    "mode": "play", "time": 10,
    "playlist_loop": [{"title": "Time", "artist": "Pink Floyd",
                       "coverid": "ab12cd", "duration": 421}],
}


@pytest.mark.parametrize(
    "payload, expected_cmd",
    [
        ({"action": "pause"}, ["pause", "1"]),
        ({"action": "resume"}, ["pause", "0"]),
        ({"action": "next"}, ["playlist", "index", "+1"]),
        ({"action": "prev"}, ["playlist", "index", "-1"]),
        ({"action": "seek", "seconds": 93.7}, ["time", "93"]),
        ({"action": "seek", "seconds": -4}, ["time", "0"]),
    ],
)
def test_player_actions_reach_the_lms(http_server, transport, payload,
                                      expected_cmd):
    base, _ = http_server
    transport.responses["status"] = PLAYING
    status, data = _post(base + "/player", payload)
    assert status == 200
    assert data["ok"] is True
    assert expected_cmd in transport.commands()
    # The reply carries the fresh status so the UI syncs without re-polling,
    # artwork rewritten to the proxy like /nowplaying.
    assert data["title"] == "Time"
    assert data["artwork"].startswith("/artwork?v=")


def test_player_unknown_action_is_refused(http_server, transport):
    base, _ = http_server
    transport.responses["status"] = PLAYING
    status, data = _post(base + "/player", {"action": "explode"})
    assert status == 200
    assert data == {"ok": False, "error": "unknown_action"}
    assert transport.commands() == []  # nothing reached the LMS


def test_player_lms_down_answers_200_not_500(http_server, transport):
    base, _ = http_server
    transport.raise_on.add("pause")
    status, data = _post(base + "/player", {"action": "pause"})
    assert status == 200
    assert data["ok"] is False


def test_player_garbage_body_is_refused(http_server, transport):
    base, _ = http_server
    req = urllib.request.Request(
        base + "/player", data=b"not json",
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
    assert data["ok"] is False
