"""English support: EN router patterns, EN replies, EN parsing separators.

Mirrors the key Italian router/actions tests with lang="en". The catalog must
be complete (every Italian key has an English sibling) and messages must never
leak Italian into an English session.
"""

import pytest

import actions
import messages
from messages import msg, set_lang
from router import Router, PATTERNS


@pytest.fixture
def router(lms):
    return Router(lms)


@pytest.fixture(autouse=True)
def _reset_lang():
    yield
    set_lang("it")  # never leak the language into other test modules


# -- catalog ----------------------------------------------------------------
def test_catalogs_have_identical_keys():
    assert set(messages.IT) == set(messages.EN)


def test_msg_lang_selection():
    assert msg("paused", lang="en") == "Paused."
    assert msg("paused", lang="it") == "In pausa."
    set_lang("en")
    assert msg("paused") == "Paused."
    set_lang("it")
    assert msg("paused") == "In pausa."


def test_unsupported_lang_falls_back_to_italian():
    set_lang("de")
    assert msg("paused") == "In pausa."


# -- parsing (actions) --------------------------------------------------------
def test_parse_song_query_english_by_and_album():
    q = actions.parse_song_query("Comfortably Numb by Pink Floyd")
    assert q == {"title": "Comfortably Numb", "artist": "Pink Floyd", "album": None}
    q = actions.parse_song_query("Time from the album The Dark Side of the Moon")
    assert q["title"] == "Time"
    assert q["album"] == "The Dark Side of the Moon"


# -- transport & info ---------------------------------------------------------
@pytest.mark.parametrize(
    "phrase, expected_cmd",
    [
        ("pause", ["pause", "1"]),
        ("stop", ["pause", "1"]),
        ("resume", ["pause", "0"]),
        ("next track", ["playlist", "index", "+1"]),
        ("skip", ["playlist", "index", "+1"]),
        ("previous track", ["playlist", "index", "-1"]),
        ("go back", ["playlist", "index", "-1"]),
        ("turn up the volume", ["mixer", "volume", "+5"]),
        ("louder", ["mixer", "volume", "+5"]),
        ("turn down the volume", ["mixer", "volume", "-5"]),
        ("quieter", ["mixer", "volume", "-5"]),
    ],
)
def test_transport_phrases_en(router, transport, phrase, expected_cmd):
    router.handle(phrase, lang="en")
    assert transport.last_call()[1] == expected_cmd


def test_transport_replies_are_english(router, transport):
    assert router.handle("pause", lang="en") == "Paused."
    assert router.handle("resume", lang="en") == "Resuming playback."


def test_now_playing_en(router, transport):
    transport.responses["status"] = {"playlist_loop": [{"title": "Time", "artist": "PF"}]}
    assert router.handle("what's playing", lang="en") == "Now playing Time by PF."


def test_play_title_containing_transport_word_en(router, transport, make_tidal):
    # "Play Don't Stop Me Now" -> played, not mistaken for a stop/pause.
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://5.flc",
                      "name": "Don't Stop Me Now"}]},
    )
    router.handle("play Don't stop me now by Queen", source="tidal", lang="en")
    assert ["playlist", "play", "tidal://5.flc"] in transport.commands()
    assert ["pause", "1"] not in transport.commands()


# -- playback + English replies ------------------------------------------------
def test_play_song_en_reply(router, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://9.flc", "name": "Time"}]},
    )
    speech = router.handle("play Time", source="tidal", lang="en")
    assert speech.startswith("Playing Time")
    assert ["playlist", "play", "tidal://9.flc"] in transport.commands()


def test_play_song_not_found_en(router, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(categories={"Songs": "S"}, items={"S": []})
    speech = router.handle("play Xyzzy", source="tidal", lang="en")
    assert speech == "I couldn't find any track for Xyzzy."
    assert getattr(speech, "ok", None) is False


def test_play_album_en(router, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Albums": "A"},
        items={"A": [{"id": "alb1", "name": "The Wall", "hasitems": 1}]},
    )
    speech = router.handle("play the album The Wall", source="tidal", lang="en")
    assert speech == "Playing the album The Wall."


def test_local_prefix_en(router, transport):
    transport.responses["search"] = {}
    speech = router.handle("from my music play Xyzzy", lang="en")
    assert speech == "I couldn't find Xyzzy in your music."


def test_fallback_en(router, transport):
    speech = router.handle("what's the weather tomorrow", lang="en")
    assert speech.startswith("I didn't understand.")


def test_handle_many_empty_en(router):
    out = router.handle_many([], lang="en")
    assert out["speech"] == "I didn't hear anything."


# -- numbered list flow ---------------------------------------------------------
def test_top_tracks_then_choose_number_en(router, transport, make_tidal):
    transport.responses["tidal"] = make_tidal(
        categories={"Artists": "Ar"},
        items={"Ar": [{"id": "a1", "name": "Pink Floyd", "hasitems": 1}],
               "a1": [{"id": "tt", "name": "Top Tracks", "hasitems": 1}],
               "tt": [{"isaudio": 1, "url": "tidal://1.flc", "name": "Time"},
                      {"isaudio": 1, "url": "tidal://2.flc", "name": "Money"}]},
    )
    speech = router.handle("which are the top tracks by Pink Floyd",
                           source="tidal", lang="en")
    assert speech.startswith("Here are the most played tracks by Pink Floyd.")
    assert "1: Time" in speech and "2: Money" in speech
    speech = router.handle("play number two", source="tidal", lang="en")
    assert speech == "Playing Money."
    assert ["playlist", "play", "tidal://2.flc"] in transport.commands()


def test_choose_without_list_en(router, transport):
    assert router.handle("play number two", lang="en").startswith("First ask me for a list")


# -- language isolation ----------------------------------------------------------
def test_italian_still_default(router, transport):
    assert router.handle("pausa") == "In pausa."


def test_languages_do_not_leak_between_requests(router, transport):
    assert router.handle("pause", lang="en") == "Paused."
    assert router.handle("pausa", lang="it") == "In pausa."


def test_patterns_cover_both_langs():
    assert set(PATTERNS["it"]) == set(PATTERNS["en"])
