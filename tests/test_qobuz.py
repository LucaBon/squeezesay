"""Qobuz service binding: same engine, feed tag ``qobuz``, scheme ``qobuz://``.

The Qobuz plugin follows the same OPML app-feed pattern as TIDAL, so these
tests exercise the service-parameterized layer (``ServiceSpec``): commands go
out under the ``qobuz`` tag, ``qobuz://`` URLs are recognized, and category
aliases resolve per-service. The exact live names come from
``tools/probe_lms.py --service qobuz`` (see SERVICES["qobuz"] in lms.py).
"""

import pytest

from lms import SERVICES, LMSClient, find_uri, uri_kind


QOBUZ_RE = SERVICES["qobuz"].uri_re


# -- service registry & client binding --------------------------------------
def test_unknown_service_rejected(transport):
    with pytest.raises(ValueError):
        LMSClient("http://lms.local:9000", "aa:bb", transport=transport,
                  service="deezer")


def test_for_service_shares_transport_and_player(lms):
    q = lms.for_service("qobuz")
    assert q is not lms
    assert q.service.tag == "qobuz"
    assert q._transport is lms._transport
    assert q.player_id == lms.player_id
    assert q.base_url == lms.base_url


def test_for_service_same_service_returns_self(lms, qobuz):
    assert lms.for_service("tidal") is lms
    assert qobuz.for_service("qobuz") is qobuz


def test_for_service_unknown_rejected(lms):
    with pytest.raises(ValueError):
        lms.for_service("spotify")


def test_for_service_does_not_mutate_original(lms):
    lms.for_service("qobuz")
    assert lms.service.tag == "tidal"


# -- URI helpers over qobuz:// -----------------------------------------------
def test_uri_kind_qobuz_forms():
    assert uri_kind("qobuz://12345.flac") == "track"
    assert uri_kind("qobuz://album:0060254735180") == "album"
    assert uri_kind("qobuz://artist:36819") == "artist"
    assert uri_kind("qobuz://playlist:998877") == "playlist"
    assert uri_kind("http://example.com/x.mp3") is None


def test_find_uri_qobuz_nested():
    item = {"presetParams": {"favorites_url": "qobuz://424242.flac"}, "name": "X"}
    assert find_uri(item, QOBUZ_RE) == "qobuz://424242.flac"
    assert find_uri({"name": "no url here"}, QOBUZ_RE) is None


def test_qobuz_re_does_not_match_tidal():
    assert find_uri({"url": "tidal://42.flc"}, QOBUZ_RE) is None


# -- browse/search goes out under the qobuz tag ------------------------------
def test_search_node_id_uses_qobuz_tag(qobuz, transport, make_feed):
    transport.responses["qobuz"] = make_feed(search_node="9")
    assert qobuz.search_node_id() == "9"
    _player, cmd = transport.last_call()
    assert cmd[:2] == ["qobuz", "items"]


def test_search_tracks_extracts_qobuz_urls(qobuz, transport, make_feed):
    transport.responses["qobuz"] = make_feed(
        search_node="9",
        categories={"Tracks": "T"},
        items={"T": [
            {"isaudio": 1, "url": "qobuz://111.flac", "name": "Time"},
            # menu-mode shape: artist on the 2nd line of ``text``, URL nested
            {"isaudio": 1, "text": "Money\nPink Floyd",
             "presetParams": {"favorites_url": "qobuz://222.flac"}},
            {"isaudio": 0, "name": "not audio"},
        ]},
    )
    tracks = qobuz.search_tracks("pink floyd")
    assert tracks == [
        {"url": "qobuz://111.flac", "title": "Time"},
        {"url": "qobuz://222.flac", "title": "Money", "artist": "Pink Floyd"},
    ]


def test_category_alias_tracks_resolves_as_songs(qobuz, transport, make_feed):
    # The Qobuz plugin may label the songs category "Tracks": the per-service
    # alias table must still resolve the canonical "Songs".
    transport.responses["qobuz"] = make_feed(
        search_node="9", categories={"Tracks": "T"},
        items={"T": [{"isaudio": 1, "url": "qobuz://1.flac", "name": "A"}]},
    )
    assert qobuz.search_tracks("a")[0]["url"] == "qobuz://1.flac"


def test_play_browse_item_uses_qobuz_tag(qobuz, transport):
    transport.responses["qobuz"] = {}
    qobuz.play_browse_item("9_q.1.0")
    _player, cmd = transport.last_call()
    assert cmd == ["qobuz", "playlist", "play", "item_id:9_q.1.0"]


def test_artist_top_tracks_uses_qobuz_children(qobuz, transport, make_feed):
    transport.responses["qobuz"] = make_feed(
        search_node="9",
        categories={"Artists": "AR"},
        items={
            "AR": [{"id": "AR.0", "name": "Pink Floyd"}],
            "AR.0": [{"id": "AR.0.T", "name": "Top Tracks"}],
            "AR.0.T": [{"isaudio": 1, "url": "qobuz://5.flac", "name": "Time"}],
        },
    )
    res = qobuz.artist_top_tracks("pink floyd")
    assert res["artist"]["title"] == "Pink Floyd"
    assert res["tracks"] == [{"url": "qobuz://5.flac", "title": "Time"}]


# -- installed services detection --------------------------------------------
@pytest.mark.parametrize("loop_key", ["appss_loop", "apps_loop"])
def test_installed_services_both_loop_spellings(lms, transport, loop_key):
    transport.responses["apps"] = {loop_key: [
        {"cmd": "tidal", "name": "TIDAL"},
        {"cmd": "qobuz", "name": "Qobuz"},
        {"cmd": "spotty", "name": "Spotify"},
    ]}
    assert lms.installed_services() == ["tidal", "qobuz"]


def test_installed_services_empty_on_no_apps(lms, transport):
    transport.responses["apps"] = {}
    assert lms.installed_services() == []


# -- behaviour verified live against plugin-Qobuz 3.7.0 (2026-07-14) ---------
def test_nested_search_node_is_found(qobuz, transport):
    # Qobuz home has no type=="search" node; it sits under a "Search" link.
    def handler(cmd):
        params = cmd[2:]
        item_id = next((p[8:] for p in params if p.startswith("item_id:")), None)
        if item_id is None:
            return {"loop_loop": [
                {"id": "0", "name": "Search", "type": "link", "hasitems": 1},
                {"id": "1", "name": "My Favorites", "hasitems": 1},
            ]}
        if item_id == "0":
            return {"loop_loop": [
                {"id": "0.0", "name": "New search", "type": "search", "hasitems": 1},
            ]}
        return {"loop_loop": []}

    transport.responses["qobuz"] = handler
    assert qobuz.search_node_id() == "0.0"


def test_tidal_home_without_search_stays_none(lms, transport):
    # TIDAL has no search_parents: a home menu without a search node -> None,
    # without drilling into random links.
    transport.responses["tidal"] = {"loop_loop": [
        {"id": "0", "name": "Search", "type": "link", "hasitems": 1},
    ]}
    assert lms.search_node_id() is None


def test_search_tracks_strips_hires_and_artist_album_line(qobuz, transport, make_feed):
    transport.responses["qobuz"] = make_feed(
        search_node="9",
        categories={"Songs": "S"},
        items={"S": [{
            "isaudio": 1,
            "text": "Comfortably Numb (Hi-Res)\nPink Floyd - The Wall (Remastered 2011 Version)",
            "presetParams": {"favorites_url": "qobuz://47683849.flac"},
        }]},
    )
    tracks = qobuz.search_tracks("comfortably numb")
    assert tracks == [{"url": "qobuz://47683849.flac",
                       "title": "Comfortably Numb", "artist": "Pink Floyd"}]


def test_qobuz_albums_resolve_from_releases_category(qobuz, transport, make_feed):
    # The Qobuz plugin labels the album category "Releases" (verified live).
    transport.responses["qobuz"] = make_feed(
        search_node="9",
        categories={"Releases": "R"},
        items={"R": [{"type": "playlist", "id": "ALB", "name": "The Wall"}]},
    )
    assert qobuz.album_candidates("the wall") == [{"id": "ALB", "title": "The Wall"}]


def test_qobuz_artist_drills_songs_child(qobuz, transport, make_feed):
    # Qobuz artist children are Releases/Songs/Biography/...: "Songs" is the
    # playable one (verified live; no "Top Tracks" like TIDAL).
    transport.responses["qobuz"] = make_feed(
        search_node="9",
        categories={"Artists": "AR"},
        items={
            "AR": [{"id": "AR.0", "name": "Pink Floyd"}],
            "AR.0": [{"id": "AR.0.R", "name": "Releases"},
                     {"id": "AR.0.S", "name": "Songs"},
                     {"id": "AR.0.B", "name": "Biography"}],
            "AR.0.S": [{"isaudio": 1, "url": "qobuz://5.flac", "name": "Time"}],
        },
    )
    res = qobuz.artist_top_tracks("pink floyd")
    assert res["tracks"] == [{"url": "qobuz://5.flac", "title": "Time"}]


def test_tidal_titles_not_stripped(lms, transport, make_feed):
    # No title_noise_re on TIDAL: a real "(Hi-Res)"-looking suffix survives.
    transport.responses["tidal"] = make_feed(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://1.flc", "name": "Song (Hi-Res)"}]},
    )
    assert lms.search_tracks("song")[0]["title"] == "Song (Hi-Res)"
