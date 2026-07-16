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
