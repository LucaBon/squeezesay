"""Message catalog — every user-facing speech string, keyed by id.

This is step 1 of internationalization: the engine and the frontends reference
message *keys*, and the actual wording lives here. Adding a language then means
adding a catalog dict (step 2 will parameterize the language-specific parsing
patterns — the regexes in ``router.py`` and the separators in ``actions.py``).

Templates use :meth:`str.format` named fields; :func:`msg` formats them.
The catalog must stay behaviour-identical to the strings it replaced: the
whole test suite asserts on this exact Italian output.
"""

from __future__ import annotations

IT = {
    # -- shared errors / gates ---------------------------------------------
    "err_unreachable":
        "Non riesco a contattare l'impianto in questo momento. Riprova tra poco.",
    "blocked":
        "Questa canzone c'è, ma non è adatta alla tua età, quindi non posso metterla.",
    "not_owner": "Solo il genitore può cambiare la lista dei brani bloccati.",

    # -- labels / list read-outs -------------------------------------------
    "generic_track": "brano",
    "label_title_artist": "{title} di {artist}",
    "enum_item": "{n}: {name}",
    "didyoumean": "Ne ho diversi per {query}. {listing}. Quale metto?",

    # -- play (streaming) ----------------------------------------------------
    "ask_title": "Non ho capito il titolo. Puoi ripetere?",
    "no_track_found": "Non ho trovato nessun brano per {title}.",
    "playing": "Riproduco {name}.",
    "playing_by": "Riproduco {name} di {artist}.",
    "album_not_found": "Non ho trovato l'album {album}.",
    "playing_track_from_album": "Riproduco {title} dall'album {album}.",
    "track_not_in_album":
        "Non ho trovato {title} nell'album {album}; riproduco l'album.",
    "playing_album": "Riproduco l'album {album}.",
    "ask_album": "Non ho capito quale album. Puoi ripetere?",
    "ask_artist": "Non ho capito l'artista. Puoi ripetere?",
    "artist_not_found": "Non ho trovato l'artista {artist}.",
    "artist_unplayable": "Non riesco a riprodurre l'artista {artist}.",
    "playing_artist": "Riproduco la musica di {artist}.",
    "ask_playlist": "Non ho capito quale playlist. Puoi ripetere?",
    "playlist_not_found": "Non ho trovato la playlist {name}.",
    "playing_playlist": "Riproduco la playlist {name}.",

    # -- transport / info ----------------------------------------------------
    "paused": "In pausa.",
    "resumed": "Riprendo la riproduzione.",
    "next_track": "Brano successivo.",
    "previous_track": "Brano precedente.",
    "volume_up": "Volume alzato.",
    "volume_down": "Volume abbassato.",
    "nothing_playing": "Al momento non sta suonando niente.",
    "now_playing": "Sta suonando {title}.",
    "now_playing_by": "Sta suonando {title} di {artist}.",

    # -- lists -> numbered choice -------------------------------------------
    "which_artist": "Di quale artista?",
    "no_tracks_for": "Non ho trovato brani per {artist}.",
    "top_tracks": "Ecco i brani più ascoltati di {artist}. {listing}. Quale metto?",
    "no_open_list":
        "Prima chiedimi un elenco, ad esempio: quali sono i brani di Pink Floyd.",
    "pick_range": "Scegli un numero da 1 a {n}.",

    # -- local library --------------------------------------------------------
    "ask_query": "Non ho capito cosa mettere. Puoi ripetere?",
    "local_not_found": "Non ho trovato {query} nella tua musica.",
    "playing_local_album": "Riproduco l'album {title} dalla tua musica.",
    "playing_local": "Riproduco {title} dalla tua musica.",
    "local_no_artist": "Non ho {artist} nella tua musica.",
    "local_no_albums": "Non ho trovato album di {artist}.",
    "local_albums": "Di {artist} ho: {listing}. Quale metto?",

    # -- kid-safe blocklist ---------------------------------------------------
    "ask_block": "Non ho capito cosa bloccare. Puoi ripetere?",
    "already_blocked": "{term} è già nella lista dei brani bloccati.",
    "blocklist_save_error":
        "Non riesco a salvare la lista in questo momento. Riprova tra poco.",
    "block_added": "Ok, ho bloccato {term}.",
    "ask_unblock": "Non ho capito cosa sbloccare. Puoi ripetere?",
    "not_in_blocklist": "{term} non è nella lista dei brani bloccati.",
    "blocklist_update_error":
        "Non riesco ad aggiornare la lista in questo momento. Riprova tra poco.",
    "block_removed": "Ok, ho sbloccato {term}.",
    "blocklist_empty": "La lista dei brani bloccati è vuota.",
    "blocklist_listing": "Brani bloccati: {terms}.",

    # -- web router (localvoice) ---------------------------------------------
    "heard_nothing": "Non ho sentito niente.",
    "router_fallback":
        "Non ho capito. Prova con: riproduci, metti l'album, dalla mia musica, "
        "oppure quali album ho di.",
    "internal_error": "Errore interno: {error}",

    # -- Alexa skill -----------------------------------------------------------
    "launch":
        "Impianto pronto. Puoi dire, ad esempio: riproduci Comfortably Numb dei "
        "Pink Floyd; metti l'album The Wall; metti la musica di Aerosmith; oppure "
        "metti in pausa. Cosa ascoltiamo?",
    "launch_no_personalization": " Personalizzazione non ancora configurata.",
    "help":
        "Posso riprodurre un brano, un album, un artista o una playlist, in streaming "
        "o dalla tua musica. Prova: riproduci Time dei Pink Floyd; metti l'album The "
        "Wall; quali album ho di Yes, poi metti la due. Posso anche mettere in pausa, "
        "cambiare traccia e regolare il volume. Cosa vuoi ascoltare?",
    "alexa_fallback": "Non ho capito. Prova a dire: riproduci, oppure metti la musica di.",
    "alexa_error": "Si è verificato un problema con l'impianto. Riprova tra poco.",
}

CATALOGS = {"it": IT}
DEFAULT_LANG = "it"


def msg(key: str, *, lang: str = None, **kwargs) -> str:
    """The message for ``key`` in ``lang`` (default Italian), formatted with
    ``kwargs``. A missing key raises ``KeyError`` — a wrong key is a bug, not
    a runtime condition to paper over."""
    return CATALOGS[lang or DEFAULT_LANG][key].format(**kwargs)
