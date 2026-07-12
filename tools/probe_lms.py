#!/usr/bin/env python3
"""Client di prova per validare la skill contro un LMS/Daphile REALE.

Cosa fa (read-only salvo --play):
  1. Trova il server LMS sulla LAN (discovery UDP Squeezebox) oppure usa --url.
  2. Elenca i player (per scegliere il tuo Daphile).
  3. Esegue la ricerca Tidal nativa del plugin:
        ["tidal","items","0",N,"search:<query>","want_url:1"]
     e stampa la STRUTTURA GREZZA degli item (per confermare i nomi dei campi).
  4. La passa al parser reale `lms.tidal_search` e mostra cosa estrae.
  5. Con --play, riproduce il primo brano trovato sul player scelto.

Esempi:
  uv run python tools/probe_lms.py --query "Pink Floyd"
  uv run python tools/probe_lms.py --url http://192.168.1.50:9000 --query "Time"
  uv run python tools/probe_lms.py --query "Money" --play
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "lambda"))

import actions  # noqa: E402
from lms import LMSClient, LMSError, find_tidal_uri, uri_kind  # noqa: E402


# -- LAN discovery (Squeezebox TLV protocol, UDP 3483) --------------------
def _parse_tlv(buf: bytes) -> dict:
    out, i = {}, 0
    while i + 5 <= len(buf):
        tag = buf[i : i + 4].decode("ascii", "replace")
        length = buf[i + 4]
        value = buf[i + 5 : i + 5 + length]
        out[tag] = value.decode("utf-8", "replace")
        i += 5 + length
    return out


def discover(timeout: float = 2.0) -> list:
    """Broadcast a discovery request and collect LMS servers on the LAN."""
    fields = [b"NAME", b"IPAD", b"JSON", b"VERS"]
    request = b"e" + b"".join(tag + b"\x00" for tag in fields)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    servers, seen = [], set()
    try:
        sock.sendto(request, ("255.255.255.255", 3483))
    except OSError as exc:
        print(f"[discovery] impossibile inviare broadcast: {exc}")
        return servers
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            break
        except OSError:
            break
        if data[:1] != b"E" or addr[0] in seen:
            continue
        seen.add(addr[0])
        tlv = _parse_tlv(data[1:])
        servers.append({"ip": addr[0], **tlv})
    sock.close()
    return servers


def resolve_base_url(args) -> str | None:
    if args.url:
        return args.url.rstrip("/")
    print("[discovery] cerco un server LMS sulla LAN (UDP 3483)...")
    servers = discover(timeout=args.discover_timeout)
    if not servers:
        print("[discovery] nessun server trovato. Riprova con --url http://IP:9000")
        return None
    for srv in servers:
        print(f"  trovato: {srv.get('NAME','?')} @ {srv['ip']} "
              f"(json:{srv.get('JSON','9000')}, vers:{srv.get('VERS','?')})")
    first = servers[0]
    port = first.get("JSON") or "9000"
    return f"http://{first['ip']}:{port}"


# -- pretty helpers -------------------------------------------------------
def _show(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="Valida la skill contro un LMS reale.")
    ap.add_argument("--url", help="Base URL LMS, es. http://192.168.1.50:9000")
    ap.add_argument("--player", help="Player id (MAC). Default: il primo trovato.")
    ap.add_argument("--query", default="Pink Floyd", help="Testo di ricerca Tidal.")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--user", help="Basic auth (se il tunnel/LMS lo richiede).")
    ap.add_argument("--password", default="")
    ap.add_argument("--play", action="store_true", help="Riproduci il primo brano.")
    ap.add_argument("--raw-items", type=int, default=3,
                    help="Quanti item grezzi stampare per ispezione.")
    ap.add_argument("--discover-timeout", type=float, default=2.0)
    args = ap.parse_args()

    base_url = resolve_base_url(args)
    if not base_url:
        return 2
    print(f"\n[LMS] uso {base_url}")

    # player_id serve al client; ne mettiamo uno provvisorio finché non elenchiamo.
    client = LMSClient(base_url, args.player or "0", username=args.user,
                       password=args.password)

    # 1) players
    try:
        players = client.get_players()
    except LMSError as exc:
        print(f"[ERRORE] non raggiungo LMS: {exc}")
        print("  Verifica IP/porta e che l'interfaccia JSON-RPC sia attiva.")
        return 1
    if not players:
        print("[players] nessun player attivo. Accendi/collega il player Daphile.")
        return 1
    print(f"\n[players] {len(players)} trovati:")
    for p in players:
        print(f"  - {p.get('name','?')}  id={p.get('playerid')}  "
              f"model={p.get('modelname', p.get('model','?'))}")

    player_id = args.player or players[0].get("playerid")
    client.player_id = player_id
    print(f"\n[player scelto] {player_id}")

    # 2) navigazione di ricerca a 3 livelli (home -> Search -> categoria)
    parsed = actions.parse_song_query(args.query)
    print(f"\n[parse] titolo={parsed['title']!r} artista={parsed['artist']!r} "
          f"album={parsed['album']!r}")
    print(f"\n[ricerca Tidal] query={args.query!r}")
    try:
        node = client.tidal_search_node_id()
        print(f"  nodo Search id={node!r}")
        cats = client.tidal_search_categories(args.query, count=args.count)
        print(f"  categorie: {cats}")
    except LMSError as exc:
        print(f"[ERRORE] navigazione Tidal fallita: {exc}")
        print("  Il plugin TIDAL è installato e loggato? Prova la UI web di LMS.")
        return 1

    # 3) risultati dei tre intent
    try:
        tracks = client.search_tracks(args.query, count=args.count)
        playlist = client.find_playlist(args.query, count=args.count)
        artist = client.find_artist(args.query, count=args.count)
    except LMSError as exc:
        print(f"[ERRORE] estrazione risultati fallita: {exc}")
        return 1

    print(f"\n[search_tracks -> {len(tracks)} brani]:")
    for t in tracks[: args.raw_items]:
        who = f"  di {t['artist']}" if t.get("artist") else ""
        print(f"  {t.get('title')!r:45} {t['url']}{who}")
    print(f"\n[find_playlist] -> {playlist}")
    print(f"[find_artist]   -> {artist}")

    if not tracks:
        print("\n[NOTA] nessun brano estratto: mandami l'output sopra e adatto il parser.")

    # 3b) STRUTTURA GREZZA del primo item Song: serve per confermare sotto quale
    # campo il plugin espone l'artista (search_tracks lo copia solo se presente).
    try:
        raw = client.tidal_category_items(args.query, "Songs", count=args.count)
    except LMSError:
        raw = []
    if raw:
        print("\n[item Song grezzo #1] chiavi disponibili (cerca il campo artista):")
        print("  " + _show(raw[0]).replace("\n", "\n  "))
        if not any(t.get("artist") for t in tracks):
            print("  [NOTA] nessun campo 'artist' estratto. Se sopra vedi l'artista "
                  "sotto un'altra chiave, dimmela e la colleghiamo alla conferma vocale.")

    # 3c) ANTEPRIMA P0: come il motore reale classifica e cosa deciderebbe
    if tracks:
        ranked = actions._rank(args.query, tracks)
        print(f"\n[P0 scoring] classifica per query={args.query!r} "
              f"(soglia sicurezza {actions.CONFIDENT_SCORE}):")
        for score, t in ranked[: args.raw_items]:
            mark = "OK" if score >= actions.CONFIDENT_SCORE else "??"
            print(f"  [{mark}] {score:.2f}  {t.get('title')!r}")
        if not any(s >= actions.CONFIDENT_SCORE for s, _ in ranked):
            print(f"  -> nessun titolo supera la soglia: uso l'ordine di TIDAL "
                  f"(primo: {tracks[0].get('title')!r}).")
        if any(t.get("artist") for t in tracks):
            print("  artista letto dalla ricerca (menu mode) -> conferma e "
                  "disambiguazione per artista attive.")

    # 4) riproduzione opzionale via il MOTORE REALE (scoring + conferma / "intendevi").
    #    SIDE EFFECT: suona sull'impianto!
    if args.play:
        print(f"\n[PLAY] motore reale: actions.play_song({args.query!r})")
        speech = actions.play_song(client, args.query)
        print(f'  risposta vocale: "{speech}"')
        print(f"  ok={getattr(speech, 'ok', '?')} "
              f"candidati={len(getattr(speech, 'candidates', []))}")
        if getattr(speech, "candidates", None):
            print("  -> era ambiguo: il motore chiede invece di indovinare (giusto!).")
        else:
            time.sleep(1.5)
            print("  ora in riproduzione:", client.now_playing_info())

    print("\n[OK] prova completata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
