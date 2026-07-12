#!/usr/bin/env python3
"""Local voice web server — no cloud, no Alexa, no AWS.

Serves a page with a microphone button (browser speech recognition, it-IT) that
posts the transcript to ``/command``; the same ``actions.py``/``lms.py`` engine
used by the Alexa skill drives LMS/Daphile over the LAN. Runs entirely at home.

    python localvoice/server.py            # auto-discovers LMS on the LAN
    python localvoice/server.py --lms http://192.168.1.50:9000   # or point it

Then open http://<this-pc-ip>:8730 from a phone/tablet/PC on the same network.
(The mic needs HTTPS from another device — pass --cert/--key; see README. The
text box works everywhere.)
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lambda"))  # actions, lms
sys.path.insert(0, HERE)  # router

import discovery  # noqa: E402
from lms import LMSClient  # noqa: E402
from router import Router  # noqa: E402

INDEX_HTML = open(os.path.join(HERE, "index.html"), encoding="utf-8").read()


def make_handler(lms, material_url: str):
    # One Router (and thus its "metti la N" list state) per browser/client id, so
    # two phones don't clobber each other's numbered list. Clients send a stable
    # id; without one they share a single default router.
    routers = {}
    lock = threading.Lock()

    def router_for(client_id: str) -> Router:
        with lock:
            r = routers.get(client_id)
            if r is None:
                r = Router(lms)
                routers[client_id] = r
            return r

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                page = INDEX_HTML.replace("__MATERIAL_URL__", material_url)
                self._send(200, page, "text/html")
            else:
                self._send(404, "not found", "text/plain")

        def do_POST(self):
            if self.path != "/command":
                self._send(404, '{"speech":"non trovato"}')
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            client_id, text = "default", ""
            try:
                payload = json.loads(raw.decode("utf-8"))
                text = payload.get("text", "")
                client_id = payload.get("client") or "default"
                # Auto source (default): the router tries the local library first,
                # then TIDAL. Explicit phrases ("dalla mia musica", "da tidal") and
                # an explicit source still override.
                source = payload.get("source") or "auto"
                # Prefer the ASR alternatives when present (mic hands-free mode);
                # the plain text box just sends one string.
                alternatives = payload.get("alternatives") or ([text] if text else [])
            except (ValueError, UnicodeDecodeError):
                source, alternatives = "auto", []
            try:
                result = router_for(client_id).handle_many(alternatives, source)
            except Exception as exc:  # never 500 the client
                result = {"speech": f"Errore interno: {exc}", "used": text,
                          "ok": False, "error": str(exc), "terms": []}
            self._send(200, json.dumps(result, ensure_ascii=False))

        def log_message(self, *args):  # keep the console quiet
            pass

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description="Server vocale locale per LMS/Daphile.")
    ap.add_argument("--lms", help="es. http://192.168.1.50:9000 "
                                  "(auto-rilevato sulla rete se omesso)")
    ap.add_argument("--player", help="MAC del player; default: il primo trovato")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8730)
    ap.add_argument("--cert", help="certificato TLS (per il mic da altri device)")
    ap.add_argument("--key", help="chiave TLS")
    ap.add_argument("--material-url",
                    help="URL della UI da aprire col link 'Material Skin'. "
                         "Default: <lms>/material/ . Se Material Skin non è "
                         "installato, punta alla UI classica (es. <lms>/).")
    args = ap.parse_args()

    lms_url = args.lms
    if not lms_url:
        print("Cerco un server LMS sulla rete (UDP 3483)...")
        lms_url = discovery.discover_base_url()
        if not lms_url:
            print("Nessun LMS trovato. Riprova indicando l'indirizzo: "
                  "--lms http://IP-DEL-SERVER:9000")
            return 1
        print(f"LMS trovato: {lms_url}")

    player = args.player
    if not player:
        players = LMSClient(lms_url, "0").get_players()
        if not players:
            print(f"Nessun player trovato su {lms_url}")
            return 1
        player = players[0]["playerid"]
        print(f"Player: {players[0].get('name')} ({player})")

    material_url = args.material_url or (lms_url.rstrip("/") + "/material/")
    httpd = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(LMSClient(lms_url, player), material_url),
    )

    scheme = "http"
    if args.cert and args.key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"

    print(f"Pronto: {scheme}://<ip-di-questo-pc>:{args.port}   (LMS {lms_url})")
    print("Ctrl+C per fermare.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
