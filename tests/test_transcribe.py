"""Local speech recognition endpoints: ``GET /asr`` and ``POST /transcribe``.

The transcriber is injectable on ``make_handler`` (like ``artwork_fetch``), so
these tests exercise the real HTTP stack with a fake engine — no model, no
download. Contract under test: ``/asr`` advertises availability; ``/transcribe``
never 5xxes (unavailable / not-Pro / empty / engine failure all answer 200 with
``ok: false``), forwards the audio bytes and the ``lang`` query param to the
engine, and passes the alternatives through for the /command mechanism.
"""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import server as srv


class FakeTranscriber:
    model_name = "small"

    def __init__(self, available=True, result=None, error=None):
        self.calls = []  # list of (audio_bytes, lang)
        self._available = available
        self.result = result if result is not None else {
            "text": "metti la radio",
            "alternatives": ["metti la radio", "metti la ratio"],
        }
        self.error = error

    def available(self):
        return self._available

    def transcribe(self, audio, lang="it"):
        self.calls.append((audio, lang))
        if self.error:
            raise self.error
        return self.result


class FakeLicense:
    def __init__(self, pro=True):
        self.pro = pro

    def is_pro(self):
        return self.pro

    def status(self):
        return {"pro": self.pro}


@pytest.fixture
def serve(lms):
    """Factory: the real handler on an ephemeral port, with an injectable
    transcriber/license; every started server is shut down at teardown."""
    servers = []

    def start(transcriber=None, license_mgr=None):
        handler = srv.make_handler(lms, "http://lms.local:9000/material/",
                                   ["tidal"], "tidal",
                                   transcriber=transcriber,
                                   license_mgr=license_mgr)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield start
    for httpd in servers:
        httpd.shutdown()


def _get_json(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def _post_audio(url, body):
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "audio/webm"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


# -- GET /asr ------------------------------------------------------------------

def test_asr_reports_available_with_model(serve):
    base = serve(transcriber=FakeTranscriber())
    status, data = _get_json(base + "/asr")
    assert status == 200
    assert data == {"available": True, "model": "small"}


def test_asr_reports_unavailable_without_transcriber(serve):
    base = serve(transcriber=None)
    assert _get_json(base + "/asr")[1] == {"available": False}


def test_asr_reports_unavailable_when_engine_missing(serve):
    # Transcriber wired but faster-whisper not installed: same answer.
    base = serve(transcriber=FakeTranscriber(available=False))
    assert _get_json(base + "/asr")[1] == {"available": False}


# -- POST /transcribe ----------------------------------------------------------

def test_transcribe_returns_text_and_alternatives(serve):
    fake = FakeTranscriber()
    base = serve(transcriber=fake, license_mgr=FakeLicense(pro=True))
    status, data = _post_audio(base + "/transcribe?lang=en", b"OPUSDATA")
    assert status == 200
    assert data == {"ok": True, "text": "metti la radio",
                    "alternatives": ["metti la radio", "metti la ratio"]}
    # The engine got the raw audio and the language from the query string.
    assert fake.calls == [(b"OPUSDATA", "en")]


def test_transcribe_defaults_to_italian(serve):
    fake = FakeTranscriber()
    base = serve(transcriber=fake)
    _post_audio(base + "/transcribe", b"AUDIO")
    assert fake.calls[0][1] == "it"


def test_transcribe_unavailable_answers_200(serve):
    base = serve(transcriber=None)
    status, data = _post_audio(base + "/transcribe", b"AUDIO")
    assert status == 200
    assert data == {"ok": False, "error": "unavailable"}


def test_transcribe_engine_missing_answers_unavailable(serve):
    fake = FakeTranscriber(available=False)
    base = serve(transcriber=fake)
    assert _post_audio(base + "/transcribe", b"AUDIO")[1] == {
        "ok": False, "error": "unavailable"}
    assert fake.calls == []  # never reaches the engine


def test_transcribe_is_pro_gated_server_side(serve):
    # Like kid-safe: hiding the toggle in the UI is not enforcement — a free
    # install must not burn server CPU on /transcribe.
    fake = FakeTranscriber()
    base = serve(transcriber=fake, license_mgr=FakeLicense(pro=False))
    status, data = _post_audio(base + "/transcribe", b"AUDIO")
    assert status == 200
    assert data == {"ok": False, "error": "pro_required"}
    assert fake.calls == []


def test_transcribe_empty_body_is_refused(serve):
    fake = FakeTranscriber()
    base = serve(transcriber=fake)
    status, data = _post_audio(base + "/transcribe", b"")
    assert status == 200
    assert data == {"ok": False, "error": "empty"}
    assert fake.calls == []


def test_transcribe_garbage_audio_answers_200(serve):
    # Whatever blows up inside the engine (corrupt container, decode error)
    # must come back as ok:false, never as a 5xx.
    fake = FakeTranscriber(error=RuntimeError("cannot decode"))
    base = serve(transcriber=fake)
    status, data = _post_audio(base + "/transcribe", b"not really audio")
    assert status == 200
    assert data["ok"] is False
    assert "cannot decode" in data["error"]


def test_transcribe_alternatives_fall_back_to_text(serve):
    # An engine with no n-best (Whisper) still feeds the /command mechanism:
    # the single transcript becomes the one-element alternatives list.
    fake = FakeTranscriber(result={"text": "pausa", "alternatives": []})
    base = serve(transcriber=fake)
    _status, data = _post_audio(base + "/transcribe", b"AUDIO")
    assert data == {"ok": True, "text": "pausa", "alternatives": ["pausa"]}


def test_transcribe_silence_gives_ok_empty(serve):
    fake = FakeTranscriber(result={"text": "", "alternatives": []})
    base = serve(transcriber=fake)
    _status, data = _post_audio(base + "/transcribe", b"AUDIO")
    assert data == {"ok": True, "text": "", "alternatives": []}
