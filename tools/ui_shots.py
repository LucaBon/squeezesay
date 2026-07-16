"""Screenshot harness for the localvoice UI (visual review loop).

Serves localvoice/ statically and captures the key UI states at a phone
viewport with Playwright. Screenshots land in tools/shots/.
"""
import http.server
import pathlib
import threading

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent / "localvoice"
OUT = pathlib.Path(__file__).resolve().parent / "shots"
OUT.mkdir(exist_ok=True)
PORT = 8931

# Simulate a conversation so bubbles/chips render (backend is not running).
FILL_LOG = """
bubble("metti Wish You Were Here dei Pink Floyd", "you");
const p = bubble("", "sys"); p.classList.add("pending");
bubble("Riproduco: Wish You Were Here — Pink Floyd", "sys");
bubble("volume al 40", "you");
bubble("Volume impostato al 40%.", "sys");
bubble("Non ho capito il comando.", "sys").classList.add("warn");
"""

# Feed the now-playing panel directly (no LMS behind the static server).
FILL_NOWPLAYING = """
renderNowPlaying({mode: "play", title: "Wish You Were Here",
                  artist: "Pink Floyd", album: "Wish You Were Here",
                  duration: 334, elapsed: 128, artwork: "/icon-192.png"});
"""


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Static file server that fills the server-side placeholders: served raw,
    ``const SERVICES = __SERVICES__;`` is a ReferenceError that kills every
    script statement after it (settings, log, now-playing)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = (ROOT / "index.html").read_text(encoding="utf-8")
            page = page.replace("__SERVICES__", '["tidal", "qobuz"]')
            page = page.replace("__MATERIAL_URL__", "#")
            data = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


def serve():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


def main():
    serve()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for scheme in ("dark", "light"):
            ctx = browser.new_context(
                viewport={"width": 390, "height": 844},
                device_scale_factor=2,
                is_mobile=True,
                has_touch=True,
                color_scheme=scheme,
            )
            page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{PORT}/index.html")
            page.wait_for_timeout(400)
            page.screenshot(path=OUT / f"01-empty-{scheme}.png")
            page.evaluate(FILL_LOG)
            page.wait_for_timeout(300)
            page.screenshot(path=OUT / f"02-conversation-{scheme}.png")
            page.evaluate("document.getElementById('mic').classList.add('listening')")
            page.wait_for_timeout(300)
            page.screenshot(path=OUT / f"03-listening-{scheme}.png")
            page.evaluate("document.getElementById('mic').classList.remove('listening')")
            page.evaluate(FILL_NOWPLAYING)
            page.wait_for_timeout(300)
            page.screenshot(path=OUT / f"04-nowplaying-{scheme}.png")
            # Pro states: locked (free tier, settings open on the pitch) and
            # active (mic unlocked, license line in settings).
            page.evaluate("setPro({pro: false}); showProUpsell();")
            page.wait_for_timeout(400)
            page.screenshot(path=OUT / f"05-pro-locked-{scheme}.png")
            page.evaluate("setPro({pro: true, key: '****ABCD'})")
            page.wait_for_timeout(300)
            page.screenshot(path=OUT / f"06-pro-active-{scheme}.png")
            # Kid-safe: unlocked parent view with a couple of blocked terms.
            page.evaluate(
                "KS = {pro: true, enabled: true, haspin: true, locked: false,"
                " terms: ['Bad Song', 'Explicit Artist']}; renderKidsafe();"
                " document.getElementById('kidsafebox').scrollIntoView();")
            page.wait_for_timeout(300)
            page.screenshot(path=OUT / f"07-kidsafe-{scheme}.png")
            ctx.close()
        browser.close()
    print("done ->", OUT)


if __name__ == "__main__":
    main()
