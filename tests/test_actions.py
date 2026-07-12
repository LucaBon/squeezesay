"""Tests for the voice-action business logic (actions.py), end-to-end through the
LMS client with a fake transport that simulates the real TIDAL 3-level navigation.
Covers happy paths, empty results, missing slots, and server errors (which must
degrade to a friendly Italian message)."""

import pytest

import actions
from actions import ERR_UNREACHABLE, parse_song_query


# -- parse_song_query -----------------------------------------------------
@pytest.mark.parametrize(
    "text, title, artist, album",
    [
        ("Comfortably Numb", "Comfortably Numb", None, None),
        ("Comfortably Numb Pink Floyd", "Comfortably Numb Pink Floyd", None, None),
        ("Comfortably Numb dei Pink Floyd", "Comfortably Numb", "Pink Floyd", None),
        ("Time di Hans Zimmer", "Time", "Hans Zimmer", None),
        ("Yesterday by The Beatles", "Yesterday", "The Beatles", None),
        ("Time dall'album Dark Side of the Moon", "Time", None, "Dark Side of the Moon"),
        ("Time dall album The Wall", "Time", None, "The Wall"),
        ("Money from album Dark Side", "Money", None, "Dark Side"),
        ("la canzone Love", "Love", None, None),
        ("", None, None, None),
    ],
)
def test_parse_song_query(text, title, artist, album):
    assert parse_song_query(text) == {"title": title, "artist": artist, "album": album}


# -- play_song ------------------------------------------------------------
def test_play_song_plays_first_track(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://42.flc", "name": "Time"}]},
    )
    msg = actions.play_song(lms, "time")
    assert msg == "Riproduco Time."
    assert ["playlist", "play", "tidal://42.flc"] in transport.commands()


def test_play_song_no_results(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(categories={"Songs": "S"}, items={"S": []})
    assert actions.play_song(lms, "brano inesistente") == (
        "Non ho trovato nessun brano per brano inesistente."
    )
    assert not any(c[:2] == ["playlist", "play"] for c in transport.commands())


@pytest.mark.parametrize("query", ["", "   ", None])
def test_play_song_missing_query(lms, transport, query):
    assert actions.play_song(lms, query) == "Non ho capito il titolo. Puoi ripetere?"
    assert transport.calls == []  # never touched the server


def test_play_song_server_error_is_friendly(lms, transport):
    transport.raise_on.add("tidal")
    assert actions.play_song(lms, "time") == ERR_UNREACHABLE


def test_play_song_falls_back_to_query_when_title_missing(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"}, items={"S": [{"isaudio": 1, "url": "tidal://7.flc"}]}
    )
    assert actions.play_song(lms, "misterioso") == "Riproduco misterioso."


# -- play_song "titolo dall'album X" (compound) ---------------------------
def _albums(album_tracks):
    return {
        "AL": [{"type": "playlist", "id": "ALB", "name": "The Wall"}],
        "ALB": album_tracks,
    }


def test_play_song_from_album(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Albums": "AL"},
        items=_albums(
            [
                {"isaudio": 1, "url": "tidal://1.flc", "name": "Mother"},
                {"isaudio": 1, "url": "tidal://2.flc", "name": "Comfortably Numb"},
            ]
        ),
    )
    msg = actions.play_song(lms, "Comfortably Numb dall'album The Wall")
    assert msg == "Riproduco Comfortably Numb dall'album The Wall."
    assert ["playlist", "play", "tidal://2.flc"] in transport.commands()


def test_play_song_from_album_title_missing_plays_whole_album(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Albums": "AL"},
        items=_albums([{"isaudio": 1, "url": "tidal://1.flc", "name": "Mother"}]),
    )
    msg = actions.play_song(lms, "Inesistente dall'album The Wall")
    assert "riproduco l'album" in msg.lower()
    assert ["tidal", "playlist", "play", "item_id:ALB"] in transport.commands()


def test_play_song_album_not_found(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(categories={"Songs": "S"}, items={})
    assert actions.play_song(lms, "X dall'album Y") == "Non ho trovato l'album Y."


# -- play_album -----------------------------------------------------------
def test_play_album(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Albums": "AL"},
        items={"AL": [{"type": "playlist", "id": "ALB", "name": "The Wall"}]},
    )
    assert actions.play_album(lms, "the wall") == "Riproduco l'album The Wall."
    assert ["tidal", "playlist", "play", "item_id:ALB"] in transport.commands()


def test_play_album_not_found(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(categories={"Songs": "S"}, items={})
    assert actions.play_album(lms, "x") == "Non ho trovato l'album x."


# -- conversational: list -> choose ---------------------------------------
def _artist_tracks():
    return {
        "A": [{"type": "outline", "id": "AR", "name": "Pink Floyd"}],
        "AR": [{"name": "Top Tracks", "id": "TT"}],
        "TT": [
            {"isaudio": 1, "url": "tidal://1.flc", "name": "Time"},
            {"isaudio": 1, "url": "tidal://2.flc", "name": "Money"},
        ],
    }


def test_top_tracks_list(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Artists": "A"}, items=_artist_tracks()
    )
    res = actions.top_tracks_list(lms, "pink floyd")
    assert res["candidates"] == [
        {"title": "Time", "url": "tidal://1.flc"},
        {"title": "Money", "url": "tidal://2.flc"},
    ]
    assert "1: Time" in res["speech"] and "2: Money" in res["speech"]


def test_top_tracks_list_missing_artist(lms, transport):
    assert actions.top_tracks_list(lms, None)["candidates"] == []
    assert transport.calls == []


def test_choose_from_plays_selected(lms, transport):
    candidates = [
        {"title": "Time", "url": "tidal://1.flc"},
        {"title": "Money", "url": "tidal://2.flc"},
    ]
    assert actions.choose_from(lms, candidates, 2) == "Riproduco Money."
    assert ["playlist", "play", "tidal://2.flc"] in transport.commands()


def test_choose_from_out_of_range(lms, transport):
    candidates = [{"title": "Time", "url": "tidal://1.flc"}]
    assert actions.choose_from(lms, candidates, 5) == "Scegli un numero da 1 a 1."
    assert transport.calls == []


def test_choose_from_no_previous_list(lms, transport):
    assert "Prima chiedimi un elenco" in actions.choose_from(lms, None, 1)
    assert transport.calls == []


# -- choose_by_name (pick a listed candidate by its title) ----------------
_LOCAL_ALBUM_CANDS = [
    {"title": "90125", "action": "play_album_id", "arg": 345},
    {"title": "Fragile", "action": "play_album_id", "arg": 9},
]


def test_choose_by_name_plays_selected(lms, transport):
    assert actions.choose_by_name(lms, _LOCAL_ALBUM_CANDS, "Fragile") == "Riproduco Fragile."
    assert ["playlistcontrol", "cmd:load", "album_id:9"] in transport.commands()


def test_choose_by_name_extra_words(lms, transport):
    assert actions.choose_by_name(lms, _LOCAL_ALBUM_CANDS, "l'album Fragile") == "Riproduco Fragile."
    assert ["playlistcontrol", "cmd:load", "album_id:9"] in transport.commands()


def test_choose_by_name_accent_insensitive(lms, transport):
    candidates = [{"title": "Café Blue", "action": "play_album_id", "arg": 7}]
    assert actions.choose_by_name(lms, candidates, "cafe blue") == "Riproduco Café Blue."
    assert ["playlistcontrol", "cmd:load", "album_id:7"] in transport.commands()


def test_choose_by_name_tidal_url_candidate(lms, transport):
    candidates = [{"title": "Time", "url": "tidal://1.flc"}]
    assert actions.choose_by_name(lms, candidates, "Time") == "Riproduco Time."
    assert ["playlist", "play", "tidal://1.flc"] in transport.commands()


def test_choose_by_name_no_match_returns_none(lms, transport):
    assert actions.choose_by_name(lms, _LOCAL_ALBUM_CANDS, "Dark Side") is None
    assert transport.calls == []


def test_choose_by_name_empty_candidates(lms, transport):
    assert actions.choose_by_name(lms, None, "Fragile") is None
    assert actions.choose_by_name(lms, [], "Fragile") is None
    assert transport.calls == []


def test_choose_by_name_empty_name(lms, transport):
    assert actions.choose_by_name(lms, _LOCAL_ALBUM_CANDS, "   ") is None
    assert transport.calls == []


def test_choose_by_name_blocked_candidate(lms, transport):
    candidates = [{"title": "Brano Cattivo", "url": "tidal://1.flc"}]
    guard = actions.Guard(restricted=True, blocklist=["brano cattivo"])
    assert actions.choose_by_name(lms, candidates, "Brano Cattivo", guard=guard) == actions.BLOCKED_SPEECH
    assert transport.calls == []


def test_choose_by_name_unreachable(lms, transport):
    transport.raise_on.add("playlistcontrol")
    assert actions.choose_by_name(lms, _LOCAL_ALBUM_CANDS, "Fragile") == actions.ERR_UNREACHABLE


# -- play_artist ----------------------------------------------------------
def test_play_artist_happy(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Artists": "A"},
        items={
            "A": [{"type": "outline", "id": "AR", "name": "Pink Floyd"}],
            "AR": [{"name": "Top Tracks", "id": "TT"}],
            "TT": [
                {"isaudio": 1, "url": "tidal://1.flc", "name": "A"},
                {"isaudio": 1, "url": "tidal://2.flc", "name": "B"},
            ],
        },
    )
    assert actions.play_artist(lms, "pink floyd") == "Riproduco la musica di pink floyd."
    cmds = transport.commands()
    assert ["playlist", "play", "tidal://1.flc"] in cmds
    assert ["playlist", "add", "tidal://2.flc"] in cmds


def test_play_artist_not_found(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(categories={"Songs": "S"}, items={})
    assert actions.play_artist(lms, "sconosciuto") == "Non ho trovato l'artista sconosciuto."


def test_play_artist_found_but_not_playable(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Artists": "A"},
        items={
            "A": [{"type": "outline", "id": "AR", "name": "X"}],
            "AR": [{"name": "Biography", "id": "BIO"}],  # no playable child
        },
    )
    assert actions.play_artist(lms, "x") == "Non riesco a riprodurre l'artista x."


def test_play_artist_missing_slot(lms, transport):
    assert actions.play_artist(lms, None) == "Non ho capito l'artista. Puoi ripetere?"
    assert transport.calls == []


# -- play_playlist --------------------------------------------------------
def test_play_playlist_happy(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Playlists": "P"},
        items={"P": [{"type": "playlist", "id": "P0", "name": "Jazz Vibes"}]},
    )
    assert actions.play_playlist(lms, "jazz") == "Riproduco la playlist jazz."
    assert ["tidal", "playlist", "play", "item_id:P0"] in transport.commands()


def test_play_playlist_not_found(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(categories={"Songs": "S"}, items={})
    assert actions.play_playlist(lms, "assente") == "Non ho trovato la playlist assente."


# -- local library --------------------------------------------------------
def test_play_local_album(lms, transport):
    transport.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125", "artist": "Yes"}]
    }
    assert actions.play_local(lms, "90125") == "Riproduco l'album 90125 dalla tua musica."
    assert ["playlistcontrol", "cmd:load", "album_id:345"] in transport.commands()


def test_play_local_artist(lms, transport):
    transport.responses["albums"] = {"count": 0}
    transport.responses["artists"] = {"artists_loop": [{"id": 1158, "artist": "Aerosmith"}]}
    assert actions.play_local(lms, "aerosmith") == "Riproduco Aerosmith dalla tua musica."
    assert ["playlistcontrol", "cmd:load", "artist_id:1158"] in transport.commands()


def test_play_local_track(lms, transport):
    transport.responses["albums"] = {"count": 0}
    transport.responses["artists"] = {"count": 0}
    transport.responses["titles"] = {
        "titles_loop": [{"id": 3439, "title": "Owner Of A Lonely Heart"}]
    }
    assert actions.play_local(lms, "owner of a lonely heart") == (
        "Riproduco Owner Of A Lonely Heart dalla tua musica."
    )
    assert ["playlistcontrol", "cmd:load", "track_id:3439"] in transport.commands()


def test_play_local_not_found(lms, transport):
    for name in ("albums", "artists", "titles"):
        transport.responses[name] = {"count": 0}
    assert actions.play_local(lms, "boh") == "Non ho trovato boh nella tua musica."


def test_play_local_missing_query(lms, transport):
    assert actions.play_local(lms, "   ") == "Non ho capito cosa mettere. Puoi ripetere?"
    assert transport.calls == []


def test_local_albums_list_and_choose(lms, transport):
    transport.responses["artists"] = {"artists_loop": [{"id": 1, "artist": "Yes"}]}
    transport.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125"}, {"id": 9, "album": "Fragile"}]
    }
    res = actions.local_albums_list(lms, "yes")
    assert res["candidates"] == [
        {"title": "90125", "action": "play_album_id", "arg": 345},
        {"title": "Fragile", "action": "play_album_id", "arg": 9},
    ]
    assert "1: 90125" in res["speech"]
    # choosing #2 plays that album by id (generalised choose_from dispatch)
    assert actions.choose_from(lms, res["candidates"], 2) == "Riproduco Fragile."
    assert ["playlistcontrol", "cmd:load", "album_id:9"] in transport.commands()


def test_local_albums_list_unknown_artist(lms, transport):
    transport.responses["artists"] = {"count": 0}
    assert actions.local_albums_list(lms, "x")["candidates"] == []


# -- transport controls ---------------------------------------------------
def test_pause_resume_next_previous(lms, transport):
    assert actions.pause(lms) == "In pausa."
    assert actions.resume(lms) == "Riprendo la riproduzione."
    assert actions.next_track(lms) == "Brano successivo."
    assert actions.previous_track(lms) == "Brano precedente."
    assert transport.commands() == [
        ["pause", "1"],
        ["pause", "0"],
        ["playlist", "index", "+1"],
        ["playlist", "index", "-1"],
    ]


def test_pause_server_error(lms, transport):
    transport.raise_on.add("pause")
    assert actions.pause(lms) == ERR_UNREACHABLE


# -- volume ---------------------------------------------------------------
def test_volume_up(lms, transport):
    assert actions.change_volume(lms, "up") == "Volume alzato."
    assert transport.last_call()[1] == ["mixer", "volume", "+5"]


def test_volume_down(lms, transport):
    assert actions.change_volume(lms, "down") == "Volume abbassato."
    assert transport.last_call()[1] == ["mixer", "volume", "-5"]


def test_volume_invalid_direction_raises(lms):
    with pytest.raises(ValueError):
        actions.change_volume(lms, "sideways")


# -- now playing ----------------------------------------------------------
def test_now_playing_with_artist(lms, transport):
    transport.responses["status"] = {
        "playlist_loop": [{"title": "Time", "artist": "Pink Floyd"}]
    }
    assert actions.now_playing(lms) == "Sta suonando Time di Pink Floyd."


def test_now_playing_without_artist(lms, transport):
    transport.responses["status"] = {"playlist_loop": [{"title": "Radio 1"}]}
    assert actions.now_playing(lms) == "Sta suonando Radio 1."


def test_now_playing_nothing(lms, transport):
    transport.responses["status"] = {"mode": "stop"}
    assert actions.now_playing(lms) == "Al momento non sta suonando niente."


def test_now_playing_server_error(lms, transport):
    transport.raise_on.add("status")
    assert actions.now_playing(lms) == ERR_UNREACHABLE


# -- kid-safe blocklist: matching primitives ------------------------------
def test_normalize_strips_accents_and_case():
    assert actions._normalize("Andrà TUTTO") == "andra tutto"


def test_parse_blocklist_splits_dedupes_keeps_display_form():
    assert actions.parse_blocklist("Song X, Some Singer\nsong x, ") == [
        "Song X",
        "Some Singer",
    ]


@pytest.mark.parametrize("raw", ["", None, "  ,  \n "])
def test_parse_blocklist_empty(raw):
    assert actions.parse_blocklist(raw) == []


def test_is_blocked_word_boundary_no_false_positive():
    # a blocked "ass" must NOT match inside "bass"
    assert actions.is_blocked("bassista", ["ass"]) is False
    assert actions.is_blocked("che ass pazzesco", ["ass"]) is True


def test_is_blocked_accent_insensitive_multiword():
    assert actions.is_blocked("La Canzone Proibita", ["canzone proibita"]) is True
    assert actions.is_blocked("perche", ["perché"]) is True


# -- Guard ----------------------------------------------------------------
def test_guard_transparent_when_not_restricted():
    g = actions.Guard(restricted=False, blocklist=["x"])
    assert g.blocks("x") is False


def test_guard_blocks_only_listed_terms_when_restricted():
    g = actions.Guard(restricted=True, blocklist=["cattivo"])
    assert g.blocks("brano cattivo") is True
    assert g.blocks("brano buono") is False


# -- guarded playback -----------------------------------------------------
BLOCK = actions.BLOCKED_SPEECH


def _restricted(blocklist):
    return actions.Guard(restricted=True, blocklist=blocklist)


def test_play_song_blocked_before_search(lms, transport):
    msg = actions.play_song(lms, "canzone vietata", guard=_restricted(["canzone vietata"]))
    assert msg == BLOCK
    assert transport.calls == []  # never even hit LMS


def test_play_song_blocked_by_resolved_title(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://9.flc", "name": "Brutto Brano"}]},
    )
    msg = actions.play_song(lms, "qualcosa", guard=_restricted(["brutto brano"]))
    assert msg == BLOCK
    assert not any(c[:2] == ["playlist", "play"] for c in transport.commands())


def test_play_song_allowed_when_term_not_listed(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://42.flc", "name": "Time"}]},
    )
    msg = actions.play_song(lms, "time", guard=_restricted(["altro"]))
    assert msg == "Riproduco Time."


def test_play_artist_blocked(lms, transport):
    msg = actions.play_artist(lms, "Cantante Vietato", guard=_restricted(["cantante vietato"]))
    assert msg == BLOCK
    assert transport.calls == []


def test_play_album_blocked(lms, transport):
    assert actions.play_album(lms, "Album X", guard=_restricted(["album x"])) == BLOCK


def test_play_playlist_blocked(lms, transport):
    assert actions.play_playlist(lms, "Lista X", guard=_restricted(["lista x"])) == BLOCK


def test_play_local_blocked(lms, transport):
    assert actions.play_local(lms, "Roba X", guard=_restricted(["roba x"])) == BLOCK
    assert transport.calls == []


def test_choose_from_blocked_candidate(lms, transport):
    candidates = [{"title": "Brano Cattivo", "url": "tidal://1.flc"}]
    assert actions.choose_from(lms, candidates, 1, guard=_restricted(["brano cattivo"])) == BLOCK
    assert transport.calls == []


def test_top_tracks_list_filters_blocked_candidates(lms, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Artists": "A"}, items=_artist_tracks()
    )
    res = actions.top_tracks_list(lms, "pink floyd", guard=_restricted(["money"]))
    titles = [c["title"] for c in res["candidates"]]
    assert titles == ["Time"]  # "Money" dropped from the read-aloud list


# -- voice-editable blocklist (owner only) --------------------------------
class MemStore:
    """In-memory stand-in for BlocklistStore (get/put), no AWS."""

    def __init__(self, terms=None):
        self.terms = list(terms or [])

    def get(self):
        return list(self.terms)

    def put(self, terms):
        self.terms = list(terms)


def test_add_block_owner_persists():
    store = MemStore()
    assert actions.add_block(store, "Cattiva Canzone", is_owner=True) == (
        "Ok, ho bloccato Cattiva Canzone."
    )
    assert store.get() == ["Cattiva Canzone"]


def test_add_block_idempotent_accent_insensitive():
    store = MemStore(["Perché"])
    assert "già" in actions.add_block(store, "perche", is_owner=True)
    assert store.get() == ["Perché"]  # unchanged


def test_add_block_non_owner_refused_and_no_write():
    store = MemStore()
    assert actions.add_block(store, "X", is_owner=False) == actions.NOT_OWNER_SPEECH
    assert store.get() == []


def test_add_block_empty_term():
    store = MemStore()
    assert "Non ho capito" in actions.add_block(store, "  ", is_owner=True)
    assert store.get() == []


def test_remove_block_owner():
    store = MemStore(["Uno", "Due"])
    assert actions.remove_block(store, "uno", is_owner=True) == "Ok, ho sbloccato uno."
    assert store.get() == ["Due"]


def test_remove_block_not_present():
    store = MemStore(["Uno"])
    assert "non è nella lista" in actions.remove_block(store, "tre", is_owner=True)
    assert store.get() == ["Uno"]


def test_remove_block_non_owner_refused():
    store = MemStore(["Uno"])
    assert actions.remove_block(store, "uno", is_owner=False) == actions.NOT_OWNER_SPEECH
    assert store.get() == ["Uno"]


def test_list_blocks_owner():
    store = MemStore(["Uno", "Due"])
    assert actions.list_blocks(store, is_owner=True) == "Brani bloccati: Uno, Due."


def test_list_blocks_empty():
    assert actions.list_blocks(MemStore(), is_owner=True) == (
        "La lista dei brani bloccati è vuota."
    )


def test_list_blocks_non_owner_refused():
    assert actions.list_blocks(MemStore(["Uno"]), is_owner=False) == actions.NOT_OWNER_SPEECH


def test_add_block_reports_store_failure():
    class FailStore(MemStore):
        def put(self, terms):
            from blocklist_store import BlocklistStoreError

            raise BlocklistStoreError("boom")

    assert "Non riesco a salvare" in actions.add_block(FailStore(), "X", is_owner=True)
