"""Integration tests for the Alexa handlers.

These drive the *real* Lambda entry point (``lambda_function.handler``) with
realistic Alexa request envelopes, exercising the full ask-sdk dispatch:
deserialize event -> route to handler -> run the real action logic against a
fake LMS transport -> serialize the Response. Only the LMS network boundary is
faked, so this covers intent routing, slot extraction, speech text and the
exception handler.
"""

import pytest

pytest.importorskip("ask_sdk_core")  # skip cleanly if the SDK isn't installed

import lambda_function  # noqa: E402
from actions import ERR_UNREACHABLE  # noqa: E402
from lms import LMSClient  # noqa: E402


# -- Alexa event builders -------------------------------------------------
def _envelope(request, person_id=None):
    system = {
        "application": {"applicationId": "amzn1.ask.skill.test"},
        "user": {"userId": "amzn1.ask.account.test"},
        "device": {"deviceId": "dev", "supportedInterfaces": {}},
    }
    if person_id:  # recognized Voice ID speaker (personalization)
        system["person"] = {
            "personId": person_id,
            "authenticationConfidenceLevel": {"level": 400},
        }
    return {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "amzn1.echo-api.session.test",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "user": {"userId": "amzn1.ask.account.test"},
        },
        "context": {"System": system},
        "request": request,
    }


def launch_request(locale="it-IT", person_id=None):
    return _envelope(
        {
            "type": "LaunchRequest",
            "requestId": "amzn1.echo-api.request.1",
            "timestamp": "2024-01-01T00:00:00Z",
            "locale": locale,
        },
        person_id=person_id,
    )


def intent_request(name, slots=None, locale="it-IT", person_id=None):
    slot_map = {
        k: {"name": k, "value": v, "confirmationStatus": "NONE"}
        for k, v in (slots or {}).items()
    }
    return _envelope(
        {
            "type": "IntentRequest",
            "requestId": "amzn1.echo-api.request.1",
            "timestamp": "2024-01-01T00:00:00Z",
            "locale": locale,
            "dialogState": "COMPLETED",
            "intent": {"name": name, "confirmationStatus": "NONE", "slots": slot_map},
        },
        person_id=person_id,
    )


def speech(response):
    return response["response"]["outputSpeech"]["ssml"]


@pytest.fixture
def wired(monkeypatch, transport):
    """Point the skill's LMS factory at a fake-transport-backed client."""
    client = LMSClient("http://lms.local:9000", "aa:bb:cc:dd:ee:ff", transport=transport)
    monkeypatch.setattr(lambda_function, "_lms", lambda: client)
    return transport


# -- tests ----------------------------------------------------------------
def test_launch(wired):
    resp = lambda_function.handler(launch_request(), None)
    assert "Impianto pronto" in speech(resp)
    # keeps the session open to wait for a command
    assert resp["response"]["shouldEndSession"] is False


def test_play_song_end_to_end(wired, make_tidal):
    wired.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://42.flc", "name": "Time"}]},
    )
    resp = lambda_function.handler(
        intent_request("RiproduciBranoIntent", {"query": "time"}), None
    )
    assert "Riproduco Time" in speech(resp)
    assert ["playlist", "play", "tidal://42.flc"] in wired.commands()


def test_play_song_no_results(wired, make_tidal):
    wired.responses["tidal"] = make_tidal(categories={"Songs": "S"}, items={"S": []})
    resp = lambda_function.handler(
        intent_request("RiproduciBranoIntent", {"query": "xyz"}), None
    )
    assert "Non ho trovato" in speech(resp)


def test_play_artist_end_to_end(wired, make_tidal):
    wired.responses["tidal"] = make_tidal(
        categories={"Artists": "A"},
        items={
            "A": [{"type": "outline", "id": "AR", "name": "Pink Floyd"}],
            "AR": [{"name": "Top Tracks", "id": "TT"}],
            "TT": [{"isaudio": 1, "url": "tidal://1.flc", "name": "A"}],
        },
    )
    resp = lambda_function.handler(
        intent_request("RiproduciArtistaIntent", {"artist": "pink floyd"}), None
    )
    assert "Riproduco la musica di pink floyd" in speech(resp)
    assert ["playlist", "play", "tidal://1.flc"] in wired.commands()


def test_play_album_intent(wired, make_tidal):
    wired.responses["tidal"] = make_tidal(
        categories={"Albums": "AL"},
        items={"AL": [{"type": "playlist", "id": "ALB", "name": "The Wall"}]},
    )
    resp = lambda_function.handler(
        intent_request("RiproduciAlbumIntent", {"album": "the wall"}), None
    )
    assert "Riproduco l'album The Wall" in speech(resp)
    assert ["tidal", "playlist", "play", "item_id:ALB"] in wired.commands()


def test_conversational_list_then_choose(wired, make_tidal):
    wired.responses["tidal"] = make_tidal(
        categories={"Artists": "A"},
        items={
            "A": [{"type": "outline", "id": "AR", "name": "Pink Floyd"}],
            "AR": [{"name": "Top Tracks", "id": "TT"}],
            "TT": [
                {"isaudio": 1, "url": "tidal://1.flc", "name": "Time"},
                {"isaudio": 1, "url": "tidal://2.flc", "name": "Money"},
            ],
        },
    )
    # turn 1: ask for the list -> session stays open and stores candidates
    r1 = lambda_function.handler(
        intent_request("ElencaTopTracksIntent", {"artist": "pink floyd"}), None
    )
    assert "1: Time" in speech(r1)
    assert r1["response"]["shouldEndSession"] is False
    session_attrs = r1["sessionAttributes"]
    assert session_attrs["candidates"][1]["title"] == "Money"

    # turn 2: choose number 2, echoing session attributes back (as Alexa does)
    ev = intent_request("ScegliNumeroIntent", {"numero": "2"})
    ev["session"]["attributes"] = session_attrs
    r2 = lambda_function.handler(ev, None)
    assert "Riproduco Money" in speech(r2)
    assert ["playlist", "play", "tidal://2.flc"] in wired.commands()


def test_list_then_choose_by_name_on_alexa(wired, make_tidal):
    # After a list, "metti <nome>" (RiproduciBranoIntent) must pick the listed
    # item by name, not run a fresh search. Wire the choice implicit tidal search
    # to a DIFFERENT url so we can prove the candidate path was used.
    wired.responses["tidal"] = make_tidal(
        categories={"Artists": "A", "Songs": "S"},
        items={
            "A": [{"type": "outline", "id": "AR", "name": "Pink Floyd"}],
            "AR": [{"name": "Top Tracks", "id": "TT"}],
            "TT": [
                {"isaudio": 1, "url": "tidal://1.flc", "name": "Time"},
                {"isaudio": 1, "url": "tidal://2.flc", "name": "Money"},
            ],
            "S": [{"isaudio": 1, "url": "tidal://999.flc", "name": "Money"}],  # fresh search
        },
    )
    r1 = lambda_function.handler(
        intent_request("ElencaTopTracksIntent", {"artist": "pink floyd"}), None
    )
    ev = intent_request("RiproduciBranoIntent", {"query": "Money"})
    ev["session"]["attributes"] = r1["sessionAttributes"]
    r2 = lambda_function.handler(ev, None)
    assert "Riproduco Money" in speech(r2)
    assert ["playlist", "play", "tidal://2.flc"] in wired.commands()  # the listed one
    assert ["playlist", "play", "tidal://999.flc"] not in wired.commands()


def test_local_did_you_mean_then_choose_on_alexa(wired):
    wired.responses["albums"] = {"count": 0}
    wired.responses["artists"] = {"count": 0}
    wired.responses["titles"] = {
        "titles_loop": [
            {"id": 1, "title": "Love", "artist": "Kendrick Lamar"},
            {"id": 2, "title": "Love", "artist": "Nat King Cole"},
        ]
    }
    r1 = lambda_function.handler(
        intent_request("RiproduciLocaleIntent", {"query": "love"}), None
    )
    assert "1: Love di Kendrick Lamar" in speech(r1)
    assert r1["response"]["shouldEndSession"] is False
    ev = intent_request("ScegliNumeroIntent", {"numero": "2"})
    ev["session"]["attributes"] = r1["sessionAttributes"]
    r2 = lambda_function.handler(ev, None)
    assert "Riproduco Love" in speech(r2)
    assert ["playlistcontrol", "cmd:load", "track_id:2"] in wired.commands()


def test_play_local_intent(wired):
    wired.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125", "artist": "Yes"}]
    }
    resp = lambda_function.handler(
        intent_request("RiproduciLocaleIntent", {"query": "90125"}), None
    )
    assert "dalla tua musica" in speech(resp)
    assert ["playlistcontrol", "cmd:load", "album_id:345"] in wired.commands()


def test_local_albums_list_then_choose(wired):
    wired.responses["artists"] = {"artists_loop": [{"id": 1, "artist": "Yes"}]}
    wired.responses["albums"] = {
        "albums_loop": [{"id": 345, "album": "90125"}, {"id": 9, "album": "Fragile"}]
    }
    r1 = lambda_function.handler(
        intent_request("ElencaAlbumLocaleIntent", {"artist": "yes"}), None
    )
    assert "1: 90125" in speech(r1)
    ev = intent_request("ScegliNumeroIntent", {"numero": "2"})
    ev["session"]["attributes"] = r1["sessionAttributes"]
    r2 = lambda_function.handler(ev, None)
    assert "Riproduco Fragile" in speech(r2)
    assert ["playlistcontrol", "cmd:load", "album_id:9"] in wired.commands()


def test_choose_without_list_is_guided(wired):
    resp = lambda_function.handler(
        intent_request("ScegliNumeroIntent", {"numero": "1"}), None
    )
    assert "elenco" in speech(resp).lower()


def test_pause_intent(wired):
    resp = lambda_function.handler(intent_request("AMAZON.PauseIntent"), None)
    assert "In pausa" in speech(resp)
    assert ["pause", "1"] in wired.commands()


def test_next_intent(wired):
    resp = lambda_function.handler(intent_request("AMAZON.NextIntent"), None)
    assert "successivo" in speech(resp)
    assert ["playlist", "index", "+1"] in wired.commands()


def test_volume_up_intent(wired):
    resp = lambda_function.handler(intent_request("AlzaVolumeIntent"), None)
    assert "Volume alzato" in speech(resp)
    assert ["mixer", "volume", "+5"] in wired.commands()


def test_now_playing_intent(wired):
    wired.responses["status"] = {
        "playlist_loop": [{"title": "Time", "artist": "Pink Floyd"}]
    }
    resp = lambda_function.handler(intent_request("CosaStaSuonandoIntent"), None)
    assert "Sta suonando Time di Pink Floyd" in speech(resp)


def test_help_intent(wired):
    resp = lambda_function.handler(intent_request("AMAZON.HelpIntent"), None)
    assert "Posso riprodurre" in speech(resp)


def test_lms_unreachable_is_friendly(wired):
    wired.raise_on.add("tidal")  # search command fails
    resp = lambda_function.handler(
        intent_request("RiproduciBranoIntent", {"query": "time"}), None
    )
    assert ERR_UNREACHABLE in speech(resp)


def test_unknown_intent_hits_exception_handler(wired):
    # No handler for this intent -> ask-sdk raises -> CatchAllExceptionHandler
    resp = lambda_function.handler(intent_request("IntentInesistente"), None)
    assert "problema" in speech(resp).lower()


# -- personalization / kid-safe gating ------------------------------------
from actions import BLOCKED_SPEECH, NOT_OWNER_SPEECH  # noqa: E402

OWNER = "amzn1.ask.person.OWNER"


class _MemStore:
    def __init__(self, terms=None):
        self.terms = list(terms or [])

    def get(self):
        return list(self.terms)

    def put(self, terms):
        self.terms = list(terms)


@pytest.fixture
def gated(wired, monkeypatch):
    """Configure the owner + a shared in-memory blocklist store."""
    monkeypatch.setenv("TRUSTED_PERSON_ID", OWNER)
    monkeypatch.setenv("KIDSAFE_BLOCKLIST", "vietata")
    store = _MemStore()
    monkeypatch.setattr(lambda_function, "_store", lambda: store)
    return store


def test_blocked_for_unrecognized_voice(gated):
    # no person object -> not the owner -> restricted -> refusal (before any LMS call)
    resp = lambda_function.handler(
        intent_request("RiproduciBranoIntent", {"query": "vietata"}), None
    )
    assert BLOCKED_SPEECH in speech(resp)


def test_blocked_for_different_person(gated):
    resp = lambda_function.handler(
        intent_request(
            "RiproduciBranoIntent", {"query": "vietata"}, person_id="amzn1.ask.person.OTHER"
        ),
        None,
    )
    assert BLOCKED_SPEECH in speech(resp)


def test_owner_bypasses_block(gated, wired, make_tidal):
    wired.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://5.flc", "name": "Vietata"}]},
    )
    resp = lambda_function.handler(
        intent_request("RiproduciBranoIntent", {"query": "vietata"}, person_id=OWNER),
        None,
    )
    assert "Riproduco Vietata" in speech(resp)


def test_no_config_plays_normally(wired, make_tidal):
    # regression: with personalization unconfigured, nothing is restricted
    wired.responses["tidal"] = make_tidal(
        categories={"Songs": "S"},
        items={"S": [{"isaudio": 1, "url": "tidal://42.flc", "name": "Time"}]},
    )
    resp = lambda_function.handler(
        intent_request("RiproduciBranoIntent", {"query": "time"}), None
    )
    assert "Riproduco Time" in speech(resp)


def test_owner_adds_block_then_others_are_blocked(gated):
    # owner adds a term by voice -> stored + confirmed
    r1 = lambda_function.handler(
        intent_request("AggiungiBloccoIntent", {"term": "cattiva"}, person_id=OWNER), None
    )
    assert "ho bloccato cattiva" in speech(r1)
    assert gated.get() == ["cattiva"]
    # now an unrecognized voice asking for it is refused (no redeploy needed)
    r2 = lambda_function.handler(
        intent_request("RiproduciBranoIntent", {"query": "cattiva"}), None
    )
    assert BLOCKED_SPEECH in speech(r2)


def test_non_owner_cannot_edit_blocklist(gated):
    r = lambda_function.handler(
        intent_request("AggiungiBloccoIntent", {"term": "cattiva"}), None
    )
    assert NOT_OWNER_SPEECH in speech(r)
    assert gated.get() == []


def test_owner_lists_blocks(gated):
    gated.put(["uno", "due"])
    r = lambda_function.handler(
        intent_request("ElencaBlocchiIntent", person_id=OWNER), None
    )
    assert "uno" in speech(r) and "due" in speech(r)
