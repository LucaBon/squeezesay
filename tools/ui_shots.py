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


def serve():
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(ROOT), **kw)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
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
            ctx.close()
        browser.close()
    print("done ->", OUT)


if __name__ == "__main__":
    main()
