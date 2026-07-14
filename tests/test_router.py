"""Tests for the local Italian intent router (localvoice/router.py). It reuses the
same actions/lms engine, so here we check that Italian phrases map to the right
action + LMS command, via the fake transport."""

import pytest

from router import Router


@pytest.fixture
def router(lms):
    return Router(lms)


# -- transport & info -----------------------------------------------------
@pytest.mark.parametrize(
    "phrase, expected_cmd",
    [
        ("pausa", ["pause", "1"]),
        ("metti in pausa", ["pause", "1"]),
        ("riprendi", ["pause", "0"]),
        ("prossima canzone", ["playlist", "index", "+1"]),
        ("vai avanti", ["playlist", "index", "+1"]),
        ("torna indietro", ["playlist", "index", "-1"]),
        ("alza il volume", ["mixer", "volume", "+5"]),
        ("abbassa il volume", ["mixer", "volume", "-5"]),
    ],
)
def test_transport_phrases(router, transport, phrase, expected_cmd):
    router.handle(phrase)
    assert transport.last_call()[1] == expected_cmd


def test_now_playing_phrase(router, transport):
    transport.responses["status"] = {"playlist_loop": [{"title": "Time", "artist": "PF"}]}
    assert router.handle("cosa sta suonando") == "Sta suonando Time di PF."


def test_play_title_containing_transport_word(router, transport, make_tidal):
    # A play command whose title contains a transport word ("Don't Stop Me Now"
    # -> "stop") must be played, not mistaken for a pause.
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://5.flc",
                      "name": "Don't Stop Me Now"}]},
    )
    router.handle("metti Don't stop me now dei Queen", source="tidal")
    assert ["playlist", "play", "tidal://5.flc"] in transport.commands()
    assert ["pause", "1"] not in transport.commands()


# -- TIDAL playback -------------------------------------------------------
def test_play_song(router, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://42.flc", "name": "Time"}]},
    )
    assert router.handle("riproduci Time") == "Riproduco Time."
    assert ["playlist", "play", "tidal://42.flc"] in transport.commands()


def test_play_song_from_album(router, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Albums": "AL"},
        items={
            "AL": [{"type": "playlist", "id": "ALB", "name": "The Wall"}],
            "ALB": [{"isaudio": 1, "url": "tidal://2.flc", "name": "Comfortably Numb"}],
        },
    )
    msg = router.handle("metti Comfortably Numb dall'album The Wall")
    assert "dall'album The Wall" in msg
    assert ["playlist", "play", "tidal://2.flc"] in transport.commands()


def test_play_album(router, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Albums": "AL"},
        items={"AL": [{"type": "playlist", "id": "ALB", "name": "The Wall"}]},
    )
    assert router.handle("metti l'album The Wall") == "Riproduco l'album The Wall."
    assert ["tidal", "playlist", "play", "item_id:ALB"] in transport.commands()


def test_play_artist(router, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Artists": "A"},
        items={
            "A": [{"type": "outline", "id": "AR", "name": "Pink Floyd"}],
            "AR": [{"name": "Top Tracks", "id": "TT"}],
            "TT": [{"isaudio": 1, "url": "tidal://1.flc", "name": "Time"}],
        },
    )
    assert router.handle("metti la musica di Pink Floyd") == "Riproduco la musica di Pink Floyd."
    assert ["playlist", "play", "tidal://1.flc"] in transport.commands()


# -- local library --------------------------------------------------------
def test_local_play_prefix(router, transport):
    transport.responses["albums"] = {"count": 0}
    transport.responses["artists"] = {"artists_loop": [{"id": 1158, "artist": "Aerosmith"}]}
    assert router.handle("dalla mia musica metti Aerosmith") == (
        "Riproduco Aerosmith dalla tua musica."
    )
    assert ["playlistcontrol", "cmd:load", "artist_id:1158"] in transport.commands()


def test_local_play_suffix(router, transport):
    transport.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125", "artist": "Yes"}]
    }
    assert router.handle("metti 90125 dal disco") == "Riproduco l'album 90125 dalla tua musica."
    assert ["playlistcontrol", "cmd:load", "album_id:345"] in transport.commands()


# -- conversational: list then choose -------------------------------------
def test_list_local_albums_then_choose(router, transport):
    transport.responses["artists"] = {"artists_loop": [{"id": 1, "artist": "Yes"}]}
    transport.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125"}, {"id": 9, "album": "Fragile"}]
    }
    listing = router.handle("quali album ho di Yes")
    assert "1: 90125" in listing
    assert router.candidates is not None
    # follow-up choice uses the remembered list
    assert router.handle("metti la 2") == "Riproduco Fragile."
    assert ["playlistcontrol", "cmd:load", "album_id:9"] in transport.commands()


def _santana_list(router, transport):
    """List Santana's albums and return; a fresh whole-library album search would
    hit a DIFFERENT id (999) so tests can prove the candidate path was used."""
    def albums(cmd):
        if any(str(p).startswith("artist_id:") for p in cmd):  # the read-out list
            return {"albums_loop": [
                {"id": 10, "album": "Abraxas"},
                {"id": 11, "album": "Moonflower"},
                {"id": 12, "album": "Supernatural"},
            ]}
        return {"albums_loop": [{"id": 999, "album": "Supernatural", "artist": "Other"}]}

    transport.responses["artists"] = {"artists_loop": [{"id": 1, "artist": "Santana"}]}
    transport.responses["albums"] = albums
    listing = router.handle("quali album ho di Santana")
    assert "3: Supernatural" in listing and router.candidates is not None


def test_list_local_albums_then_choose_by_name(router, transport):
    _santana_list(router, transport)
    assert router.handle("metti Supernatural") == "Riproduco Supernatural."
    assert ["playlistcontrol", "cmd:load", "album_id:12"] in transport.commands()
    assert ["playlistcontrol", "cmd:load", "album_id:999"] not in transport.commands()


def test_name_choice_bare_title(router, transport):
    _santana_list(router, transport)
    assert router.handle("Supernatural") == "Riproduco Supernatural."
    assert ["playlistcontrol", "cmd:load", "album_id:12"] in transport.commands()


@pytest.mark.parametrize("phrase", ["tre", "three", "metti la tre", "3", "numero tre"])
def test_choose_by_number_word(router, transport, phrase):
    _santana_list(router, transport)
    assert router.handle(phrase) == "Riproduco Supernatural."
    assert ["playlistcontrol", "cmd:load", "album_id:12"] in transport.commands()


def test_choose_by_number_word_out_of_range(router, transport):
    _santana_list(router, transport)
    assert router.handle("cinque") == "Scegli un numero da 1 a 3."


def test_name_choice_falls_through_for_unlisted(router, transport, make_tidal):
    _santana_list(router, transport)
    transport.responses["tidal"] = make_tidal(
        categories={"Albums": "AL"},
        items={"AL": [{"type": "playlist", "id": "ALB", "name": "The Wall"}]},
    )
    # An unlisted album name is not a candidate -> choose_by_name returns None ->
    # routing continues to the normal album branch (TIDAL by default).
    assert router.handle("metti l'album The Wall") == "Riproduco l'album The Wall."
    assert ["tidal", "playlist", "play", "item_id:ALB"] in transport.commands()


def test_name_choice_does_not_override_explicit_source(router, transport):
    _santana_list(router, transport)
    # Explicit "dalla mia musica" must win over the open list: a fresh local
    # search is issued (search:Supernatural), not a direct candidate play.
    router.handle("dalla mia musica metti Supernatural")
    assert any(
        cmd[0] == "albums" and any(str(p).startswith("search:") for p in cmd)
        for cmd in transport.commands()
    )


def test_relist_overwrites_candidates(router, transport):
    _santana_list(router, transport)
    first = router.candidates
    transport.responses["artists"] = {"artists_loop": [{"id": 2, "artist": "Yes"}]}
    transport.responses["albums"] = {"albums_loop": [{"id": 20, "album": "Fragile"}]}
    router.handle("quali album ho di Yes")
    assert router.candidates is not None and router.candidates != first
    assert router.candidates[0]["title"] == "Fragile"


# -- source selector (TIDAL vs local) -------------------------------------
def test_source_local_generic_play(router, transport):
    transport.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125", "artist": "Yes"}]
    }
    assert router.handle("riproduci 90125", source="local") == (
        "Riproduco l'album 90125 dalla tua musica."
    )
    assert ["playlistcontrol", "cmd:load", "album_id:345"] in transport.commands()


def test_source_local_artist(router, transport):
    transport.responses["albums"] = {"count": 0}
    transport.responses["artists"] = {"artists_loop": [{"id": 1158, "artist": "Aerosmith"}]}
    assert router.handle("metti la musica di Aerosmith", source="local") == (
        "Riproduco Aerosmith dalla tua musica."
    )
    assert ["playlistcontrol", "cmd:load", "artist_id:1158"] in transport.commands()


def test_explicit_tidal_overrides_local_source(router, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://9.flc", "name": "Time"}]},
    )
    assert router.handle("da tidal riproduci Time", source="local") == "Riproduco Time."
    assert ["playlist", "play", "tidal://9.flc"] in transport.commands()


def test_auto_source_prefers_local(router, transport):
    # source="auto" (web-app default): a confident local hit wins without TIDAL.
    transport.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125", "artist": "Yes"}]
    }
    assert router.handle("riproduci 90125", source="auto") == (
        "Riproduco l'album 90125 dalla tua musica."
    )
    assert ["playlistcontrol", "cmd:load", "album_id:345"] in transport.commands()
    assert not any(cmd[0] == "tidal" for cmd in transport.commands())


def test_auto_source_falls_back_to_tidal(router, transport, make_tidal):
    for name in ("albums", "artists", "titles"):
        transport.responses[name] = {"count": 0}  # nothing local
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://9.flc", "name": "Time"}]},
    )
    assert router.handle("riproduci Time", source="auto") == "Riproduco Time."
    assert ["playlist", "play", "tidal://9.flc"] in transport.commands()


def test_auto_source_skips_weak_local_and_uses_tidal(router, transport, make_tidal):
    # "love" matches nothing well locally -> must fall through to TIDAL, not play
    # the loose local row (the reported "Hotel California" bug).
    transport.responses["albums"] = {
        "albums_loop": [{"id": 1, "album": "Hotel California", "artist": "Eagles"}]
    }
    transport.responses["artists"] = {"count": 0}
    transport.responses["titles"] = {"count": 0}
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://7.flc", "name": "Love"}]},
    )
    assert router.handle("riproduci love", source="auto") == "Riproduco Love."
    assert ["playlist", "play", "tidal://7.flc"] in transport.commands()
    assert not any(c[:2] == ["playlistcontrol", "cmd:load"] for c in transport.commands())


def test_explicit_local_overrides_tidal_source(router, transport):
    transport.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125", "artist": "Yes"}]
    }
    assert router.handle("dalla mia musica metti 90125", source="tidal") == (
        "Riproduco l'album 90125 dalla tua musica."
    )


# -- artist grammar variants ("musica degli/dei/... X") -------------------
@pytest.mark.parametrize(
    "phrase",
    [
        "riproduci la musica degli Audioslave",
        "riproduci musica degli Audioslave",
        "metti la musica dei Pink Floyd",
        "metti le canzoni di Pink Floyd",
    ],
)
def test_artist_grammar_variants(router, transport, make_tidal, phrase):
    transport.responses["tidal"] = make_tidal(
        categories={"Artists": "A"},
        items={
            "A": [{"type": "outline", "id": "AR", "name": "X"}],
            "AR": [{"name": "Top Tracks", "id": "TT"}],
            "TT": [{"isaudio": 1, "url": "tidal://1.flc", "name": "Song"}],
        },
    )
    assert router.handle(phrase).startswith("Riproduco la musica di ")
    assert ["playlist", "play", "tidal://1.flc"] in transport.commands()


# -- multi-alternative ASR (handle_many) ----------------------------------
def test_handle_many_falls_through_to_a_hit(router, transport):
    # Local library: the mangled first alternative finds nothing, the second one
    # (the real name) matches, so that's the one kept.
    def artists(cmd):
        term = next((p.split("search:", 1)[1] for p in cmd if str(p).startswith("search:")), "")
        if "Aerosmith" in term:
            return {"artists_loop": [{"id": 1, "artist": "Aerosmith"}]}
        return {"count": 0}

    transport.responses["artists"] = artists
    transport.responses["albums"] = {"count": 0}
    transport.responses["titles"] = {"count": 0}
    result = router.handle_many(["riproduci Erosmith", "riproduci Aerosmith"], source="local")
    assert result["speech"] == "Riproduco Aerosmith dalla tua musica."
    assert result["used"] == "riproduci Aerosmith"
    assert result["ok"] is True


def test_handle_many_keeps_primary_when_all_miss(router, transport):
    transport.responses["albums"] = {"count": 0}
    transport.responses["artists"] = {"count": 0}
    transport.responses["titles"] = {"count": 0}
    result = router.handle_many(["riproduci xyz", "riproduci qwe"], source="local")
    assert result["used"] == "riproduci xyz"
    assert result["speech"].startswith("Non ho trovato")
    assert result["ok"] is False


def test_handle_many_empty(router):
    assert router.handle_many([]) == {
        "speech": "Non ho sentito niente.", "used": "", "ok": False,
        "terms": [], "choices": []
    }


def test_handle_many_exposes_tappable_choices(router, transport):
    # A list command opens a numbered list -> the reply carries tappable choices
    # (n + label, matching the spoken read-out) so the web app can render buttons.
    transport.responses["artists"] = {"artists_loop": [{"id": 1, "artist": "Yes"}]}
    transport.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125"}, {"id": 9, "album": "Fragile"}]
    }
    res = router.handle_many(["quali album ho di Yes"], source="local")
    assert res["choices"] == [
        {"n": 1, "label": "90125"},
        {"n": 2, "label": "Fragile"},
    ]
    # a bare pick afterwards doesn't re-open a list -> that reply has no buttons.
    res2 = router.handle_many(["metti la 2"], source="local")
    assert res2["speech"] == "Riproduco Fragile."
    assert res2["choices"] == []


def test_handle_many_plain_play_has_no_choices(router, transport, make_tidal):
    # An unambiguous play is not a list -> no tappable choices.
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://1.flc", "name": "Time"}]},
    )
    res = router.handle_many(["riproduci Time"], source="tidal")
    assert res["ok"] is True
    assert res["choices"] == []


def test_handle_many_passes_terms(router, transport, make_tidal):
    # The foreign name(s) travel to the client so it can read them in-language.
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://1.flc", "name": "Time"}]},
    )
    res = router.handle_many(["riproduci Time"], source="tidal")
    assert res["terms"] == ["Time"]


def test_local_did_you_mean_remembers_for_follow_up(router, transport):
    transport.responses["albums"] = {"count": 0}
    transport.responses["artists"] = {"count": 0}
    transport.responses["titles"] = {
        "titles_loop": [
            {"id": 1, "title": "Love", "artist": "Kendrick Lamar"},
            {"id": 2, "title": "Love", "artist": "Nat King Cole"},
        ]
    }
    msg = router.handle("dalla mia musica metti love")
    assert "1: Love di Kendrick Lamar" in msg and router.candidates is not None
    assert router.handle("metti la 2") == "Riproduco Love."
    assert ["playlistcontrol", "cmd:load", "track_id:2"] in transport.commands()


def test_choose_without_list(router):
    assert "Prima chiedimi un elenco" in router.handle("metti la 2")


def test_unrecognised(router):
    assert "Non ho capito" in router.handle("che tempo fa domani")


def test_empty(router):
    assert router.handle("   ") == "Non ho sentito niente."


# -- Qobuz as a second streaming service -----------------------------------
def test_source_qobuz_generic_play(router, transport, make_feed):
    transport.responses["qobuz"] = make_feed(
        categories={"Tracks": "T"},
        items={"T": [{"isaudio": 1, "url": "qobuz://9.flac", "name": "Time"}]},
    )
    assert router.handle("riproduci Time", source="qobuz") == "Riproduco Time."
    assert ["playlist", "play", "qobuz://9.flac"] in transport.commands()
    assert not any(cmd[0] == "tidal" for cmd in transport.commands())


def test_explicit_qobuz_overrides_local_source(router, transport, make_feed):
    transport.responses["qobuz"] = make_feed(
        categories={"Tracks": "T"},
        items={"T": [{"isaudio": 1, "url": "qobuz://9.flac", "name": "Time"}]},
    )
    assert router.handle("da qobuz riproduci Time", source="local") == "Riproduco Time."
    assert ["playlist", "play", "qobuz://9.flac"] in transport.commands()


def test_explicit_tidal_wins_over_qobuz_source(router, transport, make_feed):
    transport.responses["tidal"] = make_feed(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://9.flc", "name": "Time"}]},
    )
    assert router.handle("da tidal riproduci Time", source="qobuz") == "Riproduco Time."
    assert ["playlist", "play", "tidal://9.flc"] in transport.commands()
    assert not any(cmd[0] == "qobuz" for cmd in transport.commands())


def test_auto_source_falls_back_to_default_service_qobuz(lms, transport, make_feed):
    from router import Router

    qrouter = Router(lms, default_service="qobuz")
    for name in ("albums", "artists", "titles"):
        transport.responses[name] = {"count": 0}  # nothing local
    transport.responses["qobuz"] = make_feed(
        categories={"Tracks": "T"},
        items={"T": [{"isaudio": 1, "url": "qobuz://9.flac", "name": "Time"}]},
    )
    assert qrouter.handle("riproduci Time", source="auto") == "Riproduco Time."
    assert ["playlist", "play", "qobuz://9.flac"] in transport.commands()
    assert not any(cmd[0] == "tidal" for cmd in transport.commands())


def test_playlist_follows_qobuz_source(router, transport, make_feed):
    transport.responses["qobuz"] = make_feed(
        categories={"Playlists": "P"},
        items={"P": [{"type": "playlist", "id": "PL", "name": "Chill"}]},
    )
    router.handle("metti la playlist Chill", source="qobuz")
    assert ["qobuz", "playlist", "play", "item_id:PL"] in transport.commands()


def test_unknown_source_uses_default_service(router, transport, make_feed):
    # A stray/unknown selector value must not crash: it streams from the default.
    transport.responses["tidal"] = make_feed(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://9.flc", "name": "Time"}]},
    )
    assert router.handle("riproduci Time", source="deezer") == "Riproduco Time."
    assert ["playlist", "play", "tidal://9.flc"] in transport.commands()
