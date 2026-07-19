"""Tests for the LMS JSON-RPC client: command construction, TIDAL 3-level OPML
navigation/parsing, and error handling. Uses a fake transport (no network)."""

import json

import pytest

from lms import LMSClient, LMSError, find_tidal_uri, uri_kind


# -- construction ---------------------------------------------------------
def test_requires_base_url_and_player():
    with pytest.raises(ValueError):
        LMSClient(base_url="", player_id="x")
    with pytest.raises(ValueError):
        LMSClient(base_url="http://x", player_id="")


def test_base_url_is_normalised(transport):
    client = LMSClient("http://lms.local:9000/", "player", transport=transport)
    assert client.base_url == "http://lms.local:9000"


# -- command scoping ------------------------------------------------------
def test_command_uses_player_scope(lms, transport):
    lms.command("pause", "1")
    player, cmd = transport.last_call()
    assert player == "aa:bb:cc:dd:ee:ff"
    assert cmd == ["pause", "1"]


def test_server_command_uses_dash_scope(lms, transport):
    lms.server_command("players", "0", "100")
    player, cmd = transport.last_call()
    assert player == "-"
    assert cmd == ["players", "0", "100"]


def test_args_are_stringified(lms, transport):
    lms.command("mixer", "volume", 5)  # int must be sent as string
    _player, cmd = transport.last_call()
    assert cmd == ["mixer", "volume", "5"]
    assert all(isinstance(part, str) for part in cmd)


# -- TIDAL URI helpers ----------------------------------------------------
@pytest.mark.parametrize(
    "value, expected",
    [
        ("tidal://55391466.flc", "tidal://55391466.flc"),  # real track form
        ("tidal://album:44073064", "tidal://album:44073064"),
        ("wimp://album:44073064.tdl", "wimp://album:44073064.tdl"),
        ("http://example.com/not-tidal", None),
        ("", None),
    ],
)
def test_find_tidal_uri_in_string(value, expected):
    assert find_tidal_uri(value) == expected


def test_find_tidal_uri_nested():
    item = {"title": "x", "meta": {"deep": ["nope", "tidal://999.flc"]}}
    assert find_tidal_uri(item) == "tidal://999.flc"


@pytest.mark.parametrize(
    "uri, kind",
    [
        ("tidal://55391466.flc", "track"),  # track form has no 'kind:' prefix
        ("tidal://album:1", "album"),
        ("tidal://artist:1", "artist"),
        ("wimp://playlist:1", "playlist"),
        ("http://x", None),
    ],
)
def test_uri_kind(uri, kind):
    assert uri_kind(uri) == kind


# -- players --------------------------------------------------------------
def test_get_players_parses_loop(lms, transport):
    transport.responses["players"] = {
        "players_loop": [{"playerid": "aa:bb", "name": "Daphile"}]
    }
    assert lms.get_players() == [{"playerid": "aa:bb", "name": "Daphile"}]


def test_get_players_handles_missing_loop(lms, transport):
    transport.responses["players"] = {"count": 0}
    assert lms.get_players() == []


# -- TIDAL 3-level navigation ---------------------------------------------
def test_search_node_id(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(search_node="7")
    assert lms.search_node_id() == "7"
    # queried the home menu (no item_id)
    _player, cmd = transport.last_call()
    assert cmd[:2] == ["tidal", "items"]
    assert not any(p.startswith("item_id:") for p in cmd)


def test_search_node_id_none_when_absent(lms, transport):
    transport.responses["tidal"] = {"loop_loop": [{"id": "0", "type": "link", "name": "Home"}]}
    assert lms.search_node_id() is None


def test_search_categories(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        search_node="7", categories={"Songs": "7_q.4", "Artists": "7_q.2"}
    )
    cats = lms.search_categories("pink floyd")
    assert cats == {"Songs": "7_q.4", "Artists": "7_q.2"}


def test_search_tracks_returns_playable_urls(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={
            "S": [
                {"type": "audio", "isaudio": 1, "url": "tidal://111.flc", "name": "Time"},
                {"type": "audio", "isaudio": 1, "url": "tidal://222.flc", "name": "Money"},
                {"type": "link", "isaudio": 0, "name": "not audio"},  # skipped
            ]
        },
    )
    assert lms.search_tracks("pink floyd") == [
        {"url": "tidal://111.flc", "title": "Time"},
        {"url": "tidal://222.flc", "title": "Money"},
    ]


def test_search_tracks_empty_when_no_songs_category(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(categories={"Artists": "A"}, items={})
    assert lms.search_tracks("x") == []


def test_find_playlist(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Playlists": "P"},
        items={"P": [{"type": "playlist", "id": "P0", "name": "Essentials", "isaudio": 1}]},
    )
    assert lms.find_playlist("pink floyd") == {"id": "P0", "title": "Essentials"}


def test_find_album(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Albums": "AL"},
        items={"AL": [{"type": "playlist", "id": "ALB", "name": "The Wall"}]},
    )
    assert lms.find_album("the wall") == {"id": "ALB", "title": "The Wall"}


def test_album_tracks(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Albums": "AL"},
        items={
            "AL": [{"type": "playlist", "id": "ALB", "name": "The Wall"}],
            "ALB": [
                {"isaudio": 1, "url": "tidal://1.flc", "name": "Mother"},
                {"isaudio": 1, "url": "tidal://2.flc", "name": "Comfortably Numb"},
            ],
        },
    )
    res = lms.album_tracks("the wall")
    assert res["album"] == {"id": "ALB", "title": "The Wall"}
    assert res["tracks"] == [
        {"url": "tidal://1.flc", "title": "Mother"},
        {"url": "tidal://2.flc", "title": "Comfortably Numb"},
    ]


def test_album_tracks_not_found(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(categories={"Songs": "S"}, items={})
    assert lms.album_tracks("x") == {"album": None, "tracks": []}


def test_find_artist(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Artists": "A"},
        items={"A": [{"type": "outline", "id": "A0", "name": "Pink Floyd", "hasitems": 1}]},
    )
    assert lms.find_artist("pink floyd") == {"id": "A0", "title": "Pink Floyd"}


def test_find_artist_none_when_category_missing(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(categories={"Songs": "S"}, items={})
    assert lms.find_artist("x") is None


def test_artist_top_tracks(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Artists": "A"},
        items={
            "A": [{"type": "outline", "id": "AR", "name": "Pink Floyd"}],
            "AR": [{"name": "Top Tracks", "id": "TT"}, {"name": "Albums", "id": "AL"}],
            "TT": [
                {"isaudio": 1, "url": "tidal://1.flc", "name": "Song A"},
                {"isaudio": 1, "url": "tidal://2.flc", "name": "Song B"},
            ],
        },
    )
    result = lms.artist_top_tracks("pink floyd")
    assert result["artist"] == {"id": "AR", "title": "Pink Floyd"}
    assert result["tracks"] == [
        {"url": "tidal://1.flc", "title": "Song A"},
        {"url": "tidal://2.flc", "title": "Song B"},
    ]


def test_artist_top_tracks_falls_back_to_artist_mix(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Artists": "A"},
        items={
            "A": [{"type": "outline", "id": "AR", "name": "X"}],
            "AR": [{"name": "Artist Mix", "id": "MIX"}],  # no 'Top Tracks'
            "MIX": [{"isaudio": 1, "url": "tidal://9.flc", "name": "Mix Song"}],
        },
    )
    assert lms.artist_top_tracks("x")["tracks"] == [
        {"url": "tidal://9.flc", "title": "Mix Song"}
    ]


def test_artist_top_tracks_no_artist(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(categories={"Songs": "S"}, items={})
    assert lms.artist_top_tracks("x") == {"artist": None, "tracks": []}


def test_play_tracks_first_plays_rest_added(lms, transport):
    lms.play_tracks(["tidal://1.flc", "tidal://2.flc", "tidal://3.flc"])
    cmds = transport.commands()
    assert cmds == [
        ["playlist", "play", "tidal://1.flc"],
        ["playlist", "add", "tidal://2.flc"],
        ["playlist", "add", "tidal://3.flc"],
    ]


def test_play_tracks_empty_is_noop(lms, transport):
    lms.play_tracks([])
    assert transport.calls == []


# -- playback / controls --------------------------------------------------
def test_play_url(lms, transport):
    lms.play_url("tidal://12345.flc")
    assert transport.last_call()[1] == ["playlist", "play", "tidal://12345.flc"]


def test_play_browse_item(lms, transport):
    lms.play_browse_item("7_q.1.0")
    assert transport.last_call()[1] == ["tidal", "playlist", "play", "item_id:7_q.1.0"]


@pytest.mark.parametrize(
    "call, expected",
    [
        (lambda c: c.pause(), ["pause", "1"]),
        (lambda c: c.resume(), ["pause", "0"]),
        (lambda c: c.next_track(), ["playlist", "index", "+1"]),
        (lambda c: c.previous_track(), ["playlist", "index", "-1"]),
        (lambda c: c.volume(5), ["mixer", "volume", "+5"]),
        (lambda c: c.volume(-5), ["mixer", "volume", "-5"]),
        (lambda c: c.seek(93.7), ["time", "93"]),
        (lambda c: c.seek(-4), ["time", "0"]),  # clamped, never negative
    ],
)
def test_command_shapes(lms, transport, call, expected):
    call(lms)
    assert transport.last_call()[1] == expected


# -- local library --------------------------------------------------------
def test_find_local_artist(lms, transport):
    transport.responses["artists"] = {"artists_loop": [{"id": 1158, "artist": "Aerosmith"}]}
    assert lms.find_local_artist("aerosmith") == {"id": 1158, "title": "Aerosmith"}
    _p, cmd = transport.last_call()
    assert cmd == ["artists", "0", "10", "search:aerosmith"]


def test_find_local_artist_none(lms, transport):
    transport.responses["artists"] = {"count": 0}
    assert lms.find_local_artist("nope") is None


def test_find_local_album(lms, transport):
    transport.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125", "artist": "Yes"}]
    }
    assert lms.find_local_album("90125") == {"id": 345, "title": "90125", "artist": "Yes"}


def test_find_local_track(lms, transport):
    transport.responses["titles"] = {
        "titles_loop": [{"id": 3439, "title": "Owner Of A Lonely Heart"}]
    }
    assert lms.find_local_track("owner") == {"id": 3439, "title": "Owner Of A Lonely Heart"}


def test_local_albums_by_artist(lms, transport):
    transport.responses["artists"] = {"artists_loop": [{"id": 1, "artist": "Yes"}]}
    transport.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125"}, {"id": 9, "album": "Fragile"}]
    }
    res = lms.local_albums_by_artist("yes")
    assert res["artist"] == {"id": 1, "title": "Yes"}
    assert res["albums"] == [{"id": 345, "title": "90125"}, {"id": 9, "title": "Fragile"}]


def test_local_albums_by_artist_unknown(lms, transport):
    transport.responses["artists"] = {"count": 0}
    assert lms.local_albums_by_artist("x") == {"artist": None, "albums": []}


@pytest.mark.parametrize(
    "call, expected",
    [
        (lambda c: c.play_local_artist(1158), ["playlistcontrol", "cmd:load", "artist_id:1158"]),
        (lambda c: c.play_local_album(345), ["playlistcontrol", "cmd:load", "album_id:345"]),
        (lambda c: c.play_local_track(3439), ["playlistcontrol", "cmd:load", "track_id:3439"]),
    ],
)
def test_local_play_shapes(lms, transport, call, expected):
    call(lms)
    assert transport.last_call()[1] == expected


# -- now playing ----------------------------------------------------------
def test_now_playing_info_parses(lms, transport):
    transport.responses["status"] = {
        "playlist_loop": [{"title": "Time", "artist": "Pink Floyd"}]
    }
    assert lms.now_playing_info() == {"title": "Time", "artist": "Pink Floyd"}


def test_now_playing_info_none_when_stopped(lms, transport):
    transport.responses["status"] = {"mode": "stop"}
    assert lms.now_playing_info() is None


def test_search_tracks_reads_artist_from_menu_text(lms, transport, make_tidal):
    # Menu mode carries 'Title\nArtist' in `text` and the URL in favorites_url.
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={
            "S": [
                {
                    "type": "audio",
                    "text": "Comfortably Numb\nPink Floyd",
                    "presetParams": {"favorites_url": "tidal://55391466.flc"},
                }
            ]
        },
    )
    assert lms.search_tracks("comfortably numb") == [
        {"url": "tidal://55391466.flc", "title": "Comfortably Numb", "artist": "Pink Floyd"}
    ]


# -- error handling -------------------------------------------------------
def test_transport_error_propagates_as_lmserror(lms, transport):
    transport.raise_on.add("pause")
    with pytest.raises(LMSError):
        lms.pause()


def test_non_dict_result_raises(transport):
    def bad_transport(_params):
        return ["not", "a", "dict"]

    client = LMSClient("http://x", "p", transport=bad_transport)
    with pytest.raises(LMSError):
        client.command("status")


# -- http transport (mocked urlopen) --------------------------------------
def test_http_transport_builds_request_and_parses(monkeypatch):
    captured = {}

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode("utf-8"))
        captured["auth"] = req.get_header("Authorization")
        captured["timeout"] = timeout
        return FakeResp(json.dumps({"result": {"ok": True}}).encode("utf-8"))

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    client = LMSClient(
        "http://lms.local:9000", "aa:bb", username="user", password="pass", timeout=3.0
    )
    result = client.command("status", "-", "1")

    assert result == {"ok": True}
    assert captured["url"] == "http://lms.local:9000/jsonrpc.js"
    assert captured["data"]["method"] == "slim.request"
    assert captured["data"]["params"] == ["aa:bb", ["status", "-", "1"]]
    assert captured["auth"].startswith("Basic ")
    assert captured["timeout"] == 3.0


def test_http_transport_network_error_becomes_lmserror(monkeypatch):
    import urllib.error
    import urllib.request

    def boom(_req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    client = LMSClient("http://lms.local:9000", "aa:bb")
    with pytest.raises(LMSError):
        client.command("status")


def test_http_transport_missing_result_becomes_lmserror(monkeypatch):
    class FakeResp:
        def read(self):
            return json.dumps({"error": "nope"}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp())
    client = LMSClient("http://lms.local:9000", "aa:bb")
    with pytest.raises(LMSError):
        client.command("status")
