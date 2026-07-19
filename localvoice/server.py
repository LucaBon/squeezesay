#!/usr/bin/env python3
"""Local voice web server — no cloud, no accounts.

Serves a page with a microphone button (browser speech recognition, it-IT) that
posts the transcript to ``/command``; the ``actions.py``/``lms.py`` engine
drives LMS/Daphile over the LAN. Runs entirely at home.

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
sys.path.insert(0, os.path.join(ROOT, "engine"))  # actions, lms
sys.path.insert(0, HERE)  # router

import appdata  # noqa: E402
import discovery  # noqa: E402
import licensing  # noqa: E402
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


def _http_fetch(url: str, timeout: float = 5.0):
    """GET ``url`` returning ``(content_type, bytes)`` — the artwork proxy's
    default transport (injectable in tests)."""
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.headers.get("Content-Type") or "image/jpeg", resp.read()


def make_handler(lms, material_url: str, services, default_service: str,
                 ca_path=None, artwork_fetch=_http_fetch, license_mgr=None,
                 kidsafe=None, transcriber=None, multiroom=None):
    # One Router (and thus its "metti la N" list state) per browser/client id
    # AND per selected player, so two phones — or one phone switched between
    # rooms — don't clobber each other's numbered list. Clients send a stable
    # id; without one they share a single default router.
    routers = {}
    lock = threading.Lock()
    services = list(services)

    def multiroom_ok() -> bool:
        """Multi-room (player selector + «in cucina» targeting) is Pro; the
        feature object lives in pro/multiroom.py, like kid-safe."""
        return multiroom is not None and multiroom.pro_ok()

    def client_for(player_id: str):
        """The LMS client for an optional per-request player override (the
        UI player selector, Pro); the startup default player otherwise."""
        return lms.for_player(player_id) if player_id and multiroom_ok() else lms

    def router_for(client_id: str, player_id: str = "") -> Router:
        key = (client_id, player_id if (player_id and multiroom_ok()) else "")
        with lock:
            r = routers.get(key)
            if r is None:
                r = Router(client_for(key[1]), default_service=default_service,
                           services=tuple(services),
                           kidsafe=kidsafe, client_id=client_id,
                           multiroom=multiroom)
                routers[key] = r
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
            elif self.path.startswith("/nowplaying"):
                self._send_nowplaying()
            elif self.path.startswith("/artwork"):
                self._send_artwork()
            elif self.path.startswith("/players"):
                self._send_players()
            elif self.path == "/license":
                status = license_mgr.status() if license_mgr else {"pro": False}
                self._send(200, json.dumps(status))
            elif self.path.startswith("/asr"):
                self._asr_status()
            elif self.path.startswith("/kidsafe"):
                self._kidsafe_status()
            else:
                self._send(404, "not found", "text/plain")

        def _asr_status(self):
            # La pagina mostra l'interruttore «riconoscimento locale» solo se
            # il motore c'è davvero (gruppo opzionale "asr" installato).
            ok = transcriber is not None and transcriber.available()
            payload = {"available": ok}
            if ok:
                payload["model"] = getattr(transcriber, "model_name", None)
            self._send(200, json.dumps(payload))

        # Un comando parlato dura pochi secondi: 15 MB coprono con margine
        # anche un wav non compresso, e tolgono senso a un upload-bomba.
        MAX_AUDIO_BYTES = 15 * 1024 * 1024

        def _transcribe(self):
            # Il corpo è il blob audio di MediaRecorder (webm/opus o wav),
            # la lingua viaggia nella query string. Come gli altri endpoint:
            # mai un 5xx — i casi degradati rispondono 200 con ok:false.
            length = int(self.headers.get("Content-Length", 0) or 0)

            def refuse(error):
                if length:  # drena il corpo: keep-alive pulito anche su rifiuto
                    self.rfile.read(length)
                self._send(200, json.dumps({"ok": False, "error": error}))

            if transcriber is None or not transcriber.available():
                refuse("unavailable")
                return
            # Funzione Pro, applicata lato server come il kid-safe: il toggle
            # nascosto nella UI non basta a proteggere la CPU del server.
            if license_mgr and not license_mgr.is_pro():
                refuse("pro_required")
                return
            if not length:
                refuse("empty")
                return
            if length > self.MAX_AUDIO_BYTES:
                refuse("too_large")
                return
            audio = self.rfile.read(length)
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            lang = (query.get("lang") or ["it"])[0]
            try:
                result = transcriber.transcribe(audio, lang)
            except Exception as exc:
                self._send(200, json.dumps({"ok": False, "error": str(exc)}))
                return
            text = (result.get("text") or "").strip()
            alternatives = [a for a in (result.get("alternatives") or [])
                            if a and a.strip()]
            if not alternatives and text:
                alternatives = [text]
            self._send(200, json.dumps(
                {"ok": True, "text": text, "alternatives": alternatives},
                ensure_ascii=False))

        def _kidsafe_state(self, client_id: str) -> dict:
            state = {
                "pro": kidsafe.pro_ok(),
                "enabled": kidsafe.enabled(),
                "haspin": kidsafe.has_pin(),
                "locked": not kidsafe.is_unlocked(client_id),
            }
            if not state["locked"]:
                # I termini si vedono solo da sbloccati: un bambino non deve
                # poter leggere la lista per aggirarla.
                state["terms"] = kidsafe.terms()
            return state

        def _kidsafe_status(self):
            if not kidsafe:
                self._send(200, json.dumps({"pro": False, "enabled": False}))
                return
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            client_id = (query.get("client") or ["default"])[0]
            self._send(200, json.dumps(self._kidsafe_state(client_id)))

        def _kidsafe_action(self):
            if not kidsafe:
                self._send(200, json.dumps(
                    {"ok": False, "error": "unavailable"}))
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                payload = {}
            client_id = payload.get("client") or "default"
            action = payload.get("action") or ""
            pin = payload.get("pin") or ""
            term = payload.get("term") or ""
            if action == "unlock":
                result = ({"ok": True} if kidsafe.unlock(client_id, pin)
                          else {"ok": False, "error": "wrong_pin"})
            elif action == "lock":
                kidsafe.lock(client_id)
                result = {"ok": True}
            elif action == "enable":
                result = kidsafe.enable(pin, client_id)
            elif action == "disable":
                result = kidsafe.disable(client_id)
            elif action in ("add", "remove"):
                result = kidsafe.edit_terms(action, term, client_id)
            else:
                result = {"ok": False, "error": "unknown_action"}
            result.update(self._kidsafe_state(client_id))
            self._send(200, json.dumps(result, ensure_ascii=False))

        def _activate_license(self):
            # Attivazione una tantum dalla UI impostazioni. Server solo LAN:
            # nessuna auth extra, come per /command.
            if not license_mgr:
                self._send(200, json.dumps(
                    {"ok": False, "error": "unavailable"}))
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                key = json.loads(raw.decode("utf-8")).get("key", "")
            except (ValueError, UnicodeDecodeError):
                key = ""
            result = license_mgr.activate(key)
            if result.get("ok"):
                result.update(license_mgr.status())
            self._send(200, json.dumps(result))

        def _query_player(self) -> str:
            """The optional ``player`` query param (the UI player selector)."""
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            return (query.get("player") or [""])[0]

        def _send_players(self):
            # La lista player per il selettore stanza della UI. Mai un 5xx:
            # con l'LMS giù (o senza il modulo multiroom) risponde ok:false e
            # il selettore resta com'è.
            if multiroom is None:
                self._send(200, json.dumps({"ok": False, "players": []}))
                return
            try:
                players = multiroom.players()
            except Exception:
                self._send(200, json.dumps({"ok": False, "players": []}))
                return
            out = [{"id": p["playerid"], "name": p.get("name") or p["playerid"]}
                   for p in players if p.get("playerid")]
            self._send(200, json.dumps(
                {"ok": True, "pro": multiroom.pro_ok(), "current": lms.player_id,
                 "players": out},
                ensure_ascii=False))

        def _nowplaying_payload(self, client=None):
            # Mai un 5xx: il pannello si nasconde su mode "unknown", niente
            # spam di errori in console quando l'LMS è giù.
            client = client or lms
            try:
                info = client.status_info()
            except Exception:
                return {"mode": "unknown"}
            if info.get("artwork"):
                # Cache-buster: cambia col brano, così il browser non mostra
                # la copertina precedente. L'URL vero lo risolve /artwork.
                from urllib.parse import quote
                token = abs(hash((info["artwork"], info.get("title")))) % 10**8
                player_q = ("" if client.player_id == lms.player_id
                            else "&player=" + quote(client.player_id))
                info["artwork"] = f"/artwork?v={token}{player_q}"
            return info

        def _send_nowplaying(self):
            payload = self._nowplaying_payload(client_for(self._query_player()))
            self._send(200, json.dumps(payload, ensure_ascii=False))

        def _player_action(self):
            # Trasporto dal mini-player (pausa/riprendi/salta/seek): neutro
            # rispetto ai contenuti, quindi niente gate kid-safe. Risponde
            # sempre 200 con lo stato aggiornato, così la UI si allinea
            # subito senza aspettare il prossimo poll.
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                payload = {}
            action = payload.get("action") or ""
            client = client_for(payload.get("player") or "")
            actions = {
                "pause": client.pause,
                "resume": client.resume,
                "next": client.next_track,
                "prev": client.previous_track,
            }
            try:
                if action == "seek":
                    client.seek(float(payload.get("seconds") or 0))
                elif action == "volume":
                    client.volume_set(int(float(payload.get("value") or 0)))
                elif action in actions:
                    actions[action]()
                else:
                    self._send(200, json.dumps(
                        {"ok": False, "error": "unknown_action"}))
                    return
            except Exception:
                self._send(200, json.dumps({"ok": False, "mode": "unknown"}))
                return
            info = self._nowplaying_payload(client)
            info["ok"] = True
            self._send(200, json.dumps(info, ensure_ascii=False))

        def _send_artwork(self):
            # Proxy lato server della copertina: la pagina è HTTPS e l'LMS è
            # HTTP — un <img> diretto sarebbe mixed content (bloccato). Nessun
            # parametro dal client: l'URL viene sempre ricavato qui dallo
            # status del player, quindi niente open relay.
            try:
                art = client_for(self._query_player()).status_info().get("artwork")
                if not art:
                    self._send(404, "no artwork", "text/plain")
                    return
                if not art.startswith(("http://", "https://")):
                    art = lms.base_url + art
                ctype, data = artwork_fetch(art)
            except Exception:
                self._send(404, "artwork unavailable", "text/plain")
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path == "/license":
                self._activate_license()
                return
            if self.path == "/kidsafe":
                self._kidsafe_action()
                return
            if self.path == "/player":
                self._player_action()
                return
            if self.path.startswith("/transcribe"):
                self._transcribe()
                return
            if self.path != "/command":
                self._send(404, '{"speech":"non trovato"}')
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            client_id, text, player_id = "default", "", ""
            try:
                payload = json.loads(raw.decode("utf-8"))
                text = payload.get("text", "")
                client_id = payload.get("client") or "default"
                # The UI player selector: commands go to that player's router.
                player_id = payload.get("player") or ""
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
                result = router_for(client_id, player_id).handle_many(
                    alternatives, source, lang)
            except Exception as exc:  # never 500 the client
                result = {"speech": msg("internal_error", error=exc), "used": text,
                          "ok": False, "error": str(exc), "terms": []}
            self._send(200, json.dumps(result, ensure_ascii=False))

        def log_message(self, *args):  # keep the console quiet
            pass

    return Handler


def main() -> int:
    # Ogni opzione ha un gemello d'ambiente (PREFIX_LMS, PREFIX_PORT, ...):
    # Docker/HA configurano via env, la riga di comando vince quando presente.
    ap = argparse.ArgumentParser(description="Server vocale locale per LMS/Daphile.")
    ap.add_argument("--lms", default=appdata.env("LMS"),
                    help="es. http://192.168.1.50:9000 "
                         "(auto-rilevato sulla rete se omesso)")
    ap.add_argument("--player", default=appdata.env("PLAYER"),
                    help="MAC del player; default: il primo trovato")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=int(appdata.env("PORT", "8730")))
    ap.add_argument("--cert", help="certificato TLS (per il mic da altri device)")
    ap.add_argument("--key", help="chiave TLS")
    ap.add_argument("--data-dir", default=None,
                    help="cartella per lo stato persistente del server "
                         "(licenza, kid-safe). Default: PREFIX_DATA_DIR, poi "
                         "%%APPDATA%% su Windows o ~/.local/share altrove.")
    ap.add_argument("--material-url", default=appdata.env("MATERIAL_URL"),
                    help="URL della UI da aprire col link 'Material Skin'. "
                         "Default: <lms>/material/ . Se Material Skin non è "
                         "installato, punta alla UI classica (es. <lms>/).")
    ap.add_argument("--services", default=appdata.env("SERVICES", "auto"),
                    help="servizi streaming offerti nel selettore, es. "
                         "tidal,qobuz. Default 'auto': rileva i plugin "
                         "installati sull'LMS (fallback: tidal).")
    ap.add_argument("--default-service",
                    default=appdata.env("DEFAULT_SERVICE", "tidal"),
                    help="servizio streaming usato in modalità automatica e "
                         "quando la frase non ne nomina uno (default: tidal)")
    ap.add_argument("--asr-model",
                    default=appdata.env("ASR_MODEL", "small"),
                    help="modello Whisper per il riconoscimento vocale locale "
                         "(tiny/base/small/medium...; default: small). Serve "
                         "il gruppo opzionale: uv sync --group asr")
    args = ap.parse_args()
    data_dir = appdata.data_dir(args.data_dir)
    license_mgr = licensing.LicenseManager(data_dir)
    license_mgr.revalidate_async()  # settimanale, best-effort, mai bloccante
    from pro.kidsafe import KidSafe
    kidsafe = KidSafe(data_dir, license_mgr)
    # Riconoscimento vocale locale (Pro): costruito sempre, il modello si
    # carica solo al primo /transcribe. I modelli finiscono nella cartella
    # dati (in Docker: il volume persistente), non nell'immagine.
    from pro.asr import WhisperTranscriber
    transcriber = WhisperTranscriber(
        args.asr_model, cache_dir=os.path.join(data_dir, "asr-models"))
    if transcriber.available():
        print(f"Riconoscimento vocale locale attivo (faster-whisper, "
              f"modello {args.asr_model}): l'audio del microfono resta in casa.")
    else:
        print("Riconoscimento vocale locale non installato: il microfono usa "
              "il riconoscimento del browser. Per attivarlo: uv sync --group asr")

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
    # Multi-stanza (Pro): come il kid-safe, il modulo vive in pro/ e il core
    # riceve solo l'oggetto col suo piccolo contratto.
    from pro.multiroom import MultiRoom
    multiroom = MultiRoom(license_mgr, client.get_players)

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
                     ca_path=ca_path, license_mgr=license_mgr,
                     kidsafe=kidsafe, transcriber=transcriber,
                     multiroom=multiroom),
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
