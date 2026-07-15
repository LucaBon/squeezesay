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
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lambda"))  # actions, lms
sys.path.insert(0, HERE)  # router

import discovery  # noqa: E402
from lms import SERVICES, LMSClient, LMSError  # noqa: E402
from messages import msg  # noqa: E402
from router import Router  # noqa: E402

def _index_html() -> str:
    # Riletta a ogni richiesta: un edit a index.html arriva con un semplice
    # refresh, senza riavviare il server. Costo trascurabile in LAN locale.
    with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
        return f.read()

# PWA assets, read once at startup like the page itself. ca.pem is resolved at
# runtime (next to --cert) so the phone can download and trust the local CA.
def _read_bytes(name: str) -> bytes:
    with open(os.path.join(HERE, name), "rb") as f:
        return f.read()

STATIC = {
    "/manifest.webmanifest": (_read_bytes("manifest.webmanifest"),
                              "application/manifest+json"),
    "/sw.js": (_read_bytes("sw.js"), "text/javascript"),
    "/icon-192.png": (_read_bytes("icon-192.png"), "image/png"),
    "/icon-512.png": (_read_bytes("icon-512.png"), "image/png"),
}


def lan_ips() -> list:
    """This machine's primary LAN IPv4, for printing a ready-to-open URL.

    Best-effort, used only for display (never to bind). Uses the default-route
    address — the one a phone on the same LAN should target — which naturally
    skips virtual adapters (WSL/Hyper-V vEthernet). No packet is actually sent;
    the UDP connect just makes the OS pick the outgoing route. Falls back to a
    non-loopback hostname address only if the route probe fails.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return [ip]
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                return [ip]
    except OSError:
        pass
    return []


def wait_for_players(lms_url: str, delay: float = 5.0, sleep=time.sleep) -> list:
    """The LMS player list, retrying until the LMS answers.

    Il PC che ospita questo server spesso si risveglia (o fa boot) PRIMA che
    la rete sia tornata su: un LMS irraggiungibile in quel momento non è un
    errore fatale ma uno stato transitorio. Invece di morire con un traceback
    (costringendo a rilanciare a mano finché non va), aspetta e riprova.
    Ctrl+C esce.
    """
    waited = False
    while True:
        try:
            players = LMSClient(lms_url, "0").get_players()
            if waited:
                print("LMS raggiunto.")
            return players
        except LMSError as exc:
            if not waited:
                print(f"LMS non raggiungibile: {exc}")
                print(f"Aspetto che {lms_url} risponda, riprovo ogni "
                      f"{delay:g} secondi (Ctrl+C per uscire)...")
                waited = True
            sleep(delay)


def make_handler(lms, material_url: str, services, default_service: str,
                 ca_path=None):
    # One Router (and thus its "metti la N" list state) per browser/client id, so
    # two phones don't clobber each other's numbered list. Clients send a stable
    # id; without one they share a single default router.
    routers = {}
    lock = threading.Lock()
    services = list(services)

    def router_for(client_id: str) -> Router:
        with lock:
            r = routers.get(client_id)
            if r is None:
                r = Router(lms, default_service=default_service,
                           services=tuple(services))
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
                page = _index_html().replace("__MATERIAL_URL__", material_url)
                page = page.replace("__SERVICES__", json.dumps(services))
                self._send(200, page, "text/html")
            elif self.path in STATIC:
                data, ctype = STATIC[self.path]
                self._send(200, data, ctype)
            elif self.path == "/ca.pem" and ca_path and os.path.exists(ca_path):
                # La CA locale da installare (una volta) sul telefono/PC: dopo,
                # lucchetto verde e PWA installabile senza avvisi.
                with open(ca_path, "rb") as f:
                    self._send(200, f.read(), "application/x-pem-file")
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
                # The language the user is speaking (the page's mic-language
                # selector): commands are parsed and answered in that language.
                lang = payload.get("lang") or "it"
                # Prefer the ASR alternatives when present (mic hands-free mode);
                # the plain text box just sends one string.
                alternatives = payload.get("alternatives") or ([text] if text else [])
            except (ValueError, UnicodeDecodeError):
                source, alternatives, lang = "auto", [], "it"
            try:
                result = router_for(client_id).handle_many(alternatives, source, lang)
            except Exception as exc:  # never 500 the client
                result = {"speech": msg("internal_error", error=exc), "used": text,
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
    ap.add_argument("--services", default="auto",
                    help="servizi streaming offerti nel selettore, es. "
                         "tidal,qobuz. Default 'auto': rileva i plugin "
                         "installati sull'LMS (fallback: tidal).")
    ap.add_argument("--default-service", default="tidal",
                    help="servizio streaming usato in modalità automatica e "
                         "quando la frase non ne nomina uno (default: tidal)")
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

    # Aspetta che l'LMS risponda anche quando --player è già noto: subito dopo
    # c'è la rilevazione dei servizi streaming, che con la rete giù ripiegherebbe
    # in silenzio sul solo TIDAL.
    try:
        players = wait_for_players(lms_url)
    except KeyboardInterrupt:
        print("\nStop.")
        return 1

    player = args.player
    if not player:
        if not players:
            print(f"Nessun player trovato su {lms_url}")
            return 1
        player = players[0]["playerid"]
        print(f"Player: {players[0].get('name')} ({player})")

    client = LMSClient(lms_url, player)

    # Which streaming services the source selector offers. "auto" asks the LMS
    # which plugins are installed; an explicit list skips the detection (the
    # escape hatch if the apps query misbehaves on some LMS version).
    if args.services.strip().lower() == "auto":
        try:
            services = client.installed_services()
        except Exception:
            services = []
        if services:
            print(f"Servizi streaming rilevati: {', '.join(services)}")
        else:
            services = ["tidal"]
            print("Nessun servizio streaming rilevato: assumo TIDAL "
                  "(indica i tuoi con --services tidal,qobuz).")
    else:
        services = [s.strip().lower() for s in args.services.split(",") if s.strip()]
        unknown = [s for s in services if s not in SERVICES]
        if unknown or not services:
            print(f"--services non valido: {args.services!r} "
                  f"(disponibili: {', '.join(SERVICES)})")
            return 1

    default_service = args.default_service.strip().lower()
    if default_service not in services:
        default_service = services[0]
        print(f"--default-service non tra i servizi attivi: uso {default_service}")

    material_url = args.material_url or (lms_url.rstrip("/") + "/material/")
    # La CA locale (se make_cert l'ha creata) vive accanto al certificato.
    ca_path = None
    if args.cert:
        candidate = os.path.join(os.path.dirname(os.path.abspath(args.cert)), "ca.pem")
        if os.path.exists(candidate):
            ca_path = candidate
    httpd = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(client, material_url, services, default_service,
                     ca_path=ca_path),
    )

    scheme = "http"
    if args.cert and args.key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"

    # Print the real address to open, not a placeholder. If --host pins a
    # specific interface, show that; otherwise (0.0.0.0) show this PC's LAN IP.
    if args.host not in ("0.0.0.0", "", "::"):
        hosts = [args.host]
    else:
        hosts = lan_ips() or ["<ip-di-questo-pc>"]
    print(f"Pronto: {scheme}://{hosts[0]}:{args.port}   (LMS {lms_url})")
    for extra in hosts[1:]:
        print(f"        {scheme}://{extra}:{args.port}")
    print("Apri l'indirizzo qui sopra dal telefono/PC sulla stessa rete.")
    if scheme == "http":
        # Web Speech (il microfono) richiede un contesto sicuro: da un altro
        # device serve HTTPS. La casella di testo invece funziona anche in HTTP.
        print("Nota: in HTTP il microfono funziona solo su questo PC (localhost); "
              "la casella di testo funziona ovunque.")
        print("      Per il microfono dal telefono serve HTTPS con certificato:")
        print("        uv run python tools/make_cert.py")
        print(f"        uv run python localvoice/server.py --lms {lms_url} "
              "--cert cert.pem --key key.pem")
    else:
        print("Microfono disponibile anche dal telefono (HTTPS). Al primo accesso "
              "accetta una volta l'avviso del certificato self-signed.")
        if ca_path:
            print("Per togliere l'avviso e installare la pagina come app: scarica "
                  f"https://{hosts[0]}:{args.port}/ca.pem sul telefono e installala "
                  "come certificato CA (una volta sola).")
    print("Ctrl+C per fermare.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
