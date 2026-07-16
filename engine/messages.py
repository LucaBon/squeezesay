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
    # Source tag appended to a play confirmation: with three sources (local,
    # TIDAL, Qobuz) the reply must say which one answered.
    "from_service": " da {service}",
    "from_local": " dalla tua musica",
    "heard_nothing": "Non ho sentito niente.",
    "router_fallback":
        "Non ho capito. Prova con: riproduci, metti l'album, dalla mia musica, "
        "oppure quali album ho di.",
    "internal_error": "Errore interno: {error}",
    "pro_required":
        "Questa è una funzione Pro: si attiva dalle impostazioni della pagina.",
}

EN = {
    # -- shared errors / gates ---------------------------------------------
    "err_unreachable":
        "I can't reach the system right now. Please try again in a moment.",
    "blocked":
        "That song exists, but it's not suitable for your age, so I can't play it.",
    "not_owner": "Only the parent can change the blocked-songs list.",

    # -- labels / list read-outs -------------------------------------------
    "generic_track": "track",
    "label_title_artist": "{title} by {artist}",
    "enum_item": "{n}: {name}",
    "didyoumean": "I found several for {query}. {listing}. Which one should I play?",

    # -- play (streaming) ----------------------------------------------------
    "ask_title": "I didn't catch the title. Can you repeat?",
    "no_track_found": "I couldn't find any track for {title}.",
    "playing": "Playing {name}.",
    "playing_by": "Playing {name} by {artist}.",
    "album_not_found": "I couldn't find the album {album}.",
    "playing_track_from_album": "Playing {title} from the album {album}.",
    "track_not_in_album":
        "I couldn't find {title} in the album {album}; playing the album.",
    "playing_album": "Playing the album {album}.",
    "ask_album": "I didn't catch which album. Can you repeat?",
    "ask_artist": "I didn't catch the artist. Can you repeat?",
    "artist_not_found": "I couldn't find the artist {artist}.",
    "artist_unplayable": "I can't play the artist {artist}.",
    "playing_artist": "Playing music by {artist}.",
    "ask_playlist": "I didn't catch which playlist. Can you repeat?",
    "playlist_not_found": "I couldn't find the playlist {name}.",
    "playing_playlist": "Playing the playlist {name}.",

    # -- transport / info ----------------------------------------------------
    "paused": "Paused.",
    "resumed": "Resuming playback.",
    "next_track": "Next track.",
    "previous_track": "Previous track.",
    "volume_up": "Volume up.",
    "volume_down": "Volume down.",
    "nothing_playing": "Nothing is playing right now.",
    "now_playing": "Now playing {title}.",
    "now_playing_by": "Now playing {title} by {artist}.",

    # -- lists -> numbered choice -------------------------------------------
    "which_artist": "Which artist?",
    "no_tracks_for": "I couldn't find tracks for {artist}.",
    "top_tracks": "Here are the most played tracks by {artist}. {listing}. Which one should I play?",
    "no_open_list":
        "First ask me for a list, for example: which are the top tracks by Pink Floyd.",
    "pick_range": "Pick a number from 1 to {n}.",

    # -- local library --------------------------------------------------------
    "ask_query": "I didn't catch what to play. Can you repeat?",
    "local_not_found": "I couldn't find {query} in your music.",
    "playing_local_album": "Playing the album {title} from your music.",
    "playing_local": "Playing {title} from your music.",
    "local_no_artist": "I don't have {artist} in your music.",
    "local_no_albums": "I couldn't find albums by {artist}.",
    "local_albums": "By {artist} I have: {listing}. Which one should I play?",

    # -- kid-safe blocklist ---------------------------------------------------
    "ask_block": "I didn't catch what to block. Can you repeat?",
    "already_blocked": "{term} is already in the blocked-songs list.",
    "blocklist_save_error":
        "I can't save the list right now. Please try again in a moment.",
    "block_added": "Ok, I blocked {term}.",
    "ask_unblock": "I didn't catch what to unblock. Can you repeat?",
    "not_in_blocklist": "{term} is not in the blocked-songs list.",
    "blocklist_update_error":
        "I can't update the list right now. Please try again in a moment.",
    "block_removed": "Ok, I unblocked {term}.",
    "blocklist_empty": "The blocked-songs list is empty.",
    "blocklist_listing": "Blocked songs: {terms}.",

    # -- web router (localvoice) ---------------------------------------------
    # Source tag appended to a play confirmation: with three sources (local,
    # TIDAL, Qobuz) the reply must say which one answered.
    "from_service": " from {service}",
    "from_local": " from your music",
    "heard_nothing": "I didn't hear anything.",
    "router_fallback":
        "I didn't understand. Try: play, play the album, from my music, "
        "or which albums do I have by.",
    "internal_error": "Internal error: {error}",
    "pro_required":
        "This is a Pro feature: activate it from the page settings.",
}

CATALOGS = {"it": IT, "en": EN}
DEFAULT_LANG = "it"

# Per-request language, so concurrent web requests in different languages don't
# step on each other (contextvars are async- and thread-safe per execution
# context; our HTTP server is thread-per-request).
import contextvars as _contextvars

_current_lang = _contextvars.ContextVar("vivavoce_lang", default=DEFAULT_LANG)


def set_lang(lang: str) -> None:
    """Select the reply language for the current request; unsupported values
    fall back to the default (Italian)."""
    _current_lang.set(lang if lang in CATALOGS else DEFAULT_LANG)


def get_lang() -> str:
    return _current_lang.get()


def msg(key: str, *, lang: str = None, **kwargs) -> str:
    """The message for ``key`` in ``lang`` (default: the per-request language
    set via :func:`set_lang`, else Italian), formatted with ``kwargs``. A
    missing key raises ``KeyError`` — a wrong key is a bug, not a runtime
    condition to paper over."""
    return CATALOGS[lang or _current_lang.get()][key].format(**kwargs)
