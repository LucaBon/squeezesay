"""Interaction test for the local-recognition mic path (Playwright).

Serves localvoice/ statically (same harness as ui_shots) and stubs the backend
with page.route: /asr says the engine is there, /license says Pro, /transcribe
returns a canned transcript. Chromium runs with a fake microphone, so a real
MediaRecorder capture happens: mic tap → record → tap → POST /transcribe →
the transcript (and its alternatives) must land in POST /command untouched.

    uv run python tools/ui_asr_test.py
"""
import json
import threading
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

import ui_shots


def fulfill_json(payload):
    return lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(payload))


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ui_shots._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    transcribes, commands = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=[
            "--use-fake-ui-for-media-stream",     # auto-grant the mic prompt
            "--use-fake-device-for-media-stream", # synthetic audio input
        ])
        page = browser.new_page()
        page.route("**/asr", fulfill_json({"available": True, "model": "small"}))
        page.route("**/license", fulfill_json({"pro": True, "key": "****TEST"}))
        page.route("**/kidsafe*", fulfill_json({"pro": True, "enabled": False}))
        page.route("**/nowplaying", fulfill_json({"mode": "stop"}))

        def on_transcribe(route):
            req = route.request
            transcribes.append({"url": req.url,
                                "body_bytes": len(req.post_data_buffer or b"")})
            fulfill_json({"ok": True, "text": "metti la radio",
                          "alternatives": ["metti la radio",
                                           "metti la ratio"]})(route)

        def on_command(route):
            commands.append(json.loads(route.request.post_data))
            fulfill_json({"speech": "Fatto.", "ok": True, "used":
                          "metti la radio", "terms": []})(route)

        page.route("**/transcribe*", on_transcribe)
        page.route("**/command", on_command)

        page.goto(base + "/index.html")
        # Pro arrives async (/license): the toggle row shows once /asr answers
        # and the checkbox unlocks once Pro is applied.
        page.wait_for_selector("#localasrrow", state="visible")
        page.wait_for_function("!document.getElementById('localasr').disabled")
        page.check("#localasr")
        page.check("#autosend")   # hands-free: the transcript sends itself

        # Tap to record, tap again to stop — the exact press/release UX.
        page.click("#mic")
        page.wait_for_selector("#mic.listening")
        page.wait_for_timeout(700)  # capture some fake audio
        page.click("#mic")
        page.wait_for_function("document.querySelectorAll('#log .you').length > 0")
        browser.close()
    httpd.shutdown()

    assert len(transcribes) == 1, transcribes
    assert "lang=it" in transcribes[0]["url"], transcribes[0]
    assert transcribes[0]["body_bytes"] > 0, "empty recording posted"
    assert len(commands) == 1, commands
    assert commands[0]["text"] == "metti la radio"
    assert commands[0]["alternatives"] == ["metti la radio", "metti la ratio"]
    assert commands[0]["lang"] == "it"
    print("ok: mic tap/release -> /transcribe -> /command "
          f"(audio {transcribes[0]['body_bytes']} bytes, "
          "alternatives passed through)")


if __name__ == "__main__":
    main()
