"""Local intent router (Italian + English).

Maps free text (from the browser's speech recognition, or a text box) to the
action functions of the shared engine (``actions.py`` + ``lms.py``).
No cloud — just rules over the transcribed text.

Language: every pattern lives in ``PATTERNS[lang]`` (it/en); the client sends
the language it is speaking (the page's mic-language selector) and the reply
comes back in that language via the ``messages`` catalog. Unsupported
languages fall back to Italian.

Music sources:
- **local library** (USB disk) and the **streaming services** (TIDAL, Qobuz).
  Ambiguous commands ("riproduci X" / "play X") follow the ``source`` passed by
  the UI selector; "auto" tries local first, then the configured default
  streaming service. Explicit phrases always win: "dalla mia musica …" /
  "from my music …" forces local, "da tidal …" / "on tidal …" force a service.

State (the last read-out list) is kept in-instance for the "metti la N" /
"play number N" choice.
"""

from __future__ import annotations

import re

import actions
from messages import msg, set_lang

# Web Speech transcribes a spoken position as a word ("tre"/"three"), not "3".
_NUM_WORDS = {
    "uno": 1, "un": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# People answer a read-out list with "la seconda" / "the second one" at least
# as often as with the bare number — but ONLY while a list is open: without
# one, "metti la quinta" is music (Beethoven), not a pick, so ordinals are
# gated on an open list while cardinals keep answering with a helpful hint.
_ORDINAL_WORDS = {
    "primo": 1, "prima": 1, "secondo": 2, "seconda": 2, "terzo": 3, "terza": 3,
    "quarto": 4, "quarta": 4, "quinto": 5, "quinta": 5, "sesto": 6, "sesta": 6,
    "settimo": 7, "settima": 7, "ottavo": 8, "ottava": 8, "nono": 9, "nona": 9,
    "decimo": 10, "decima": 10,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}


def _as_number(token, ordinals=False):
    """A spoken position -> int, or None if the token isn't a number."""
    token = (token or "").strip().lower()
    if token.isdigit():
        return int(token)
    number = _NUM_WORDS.get(token)
    if number is None and ordinals:
        number = _ORDINAL_WORDS.get(token)
    return number


def _c(pattern):  # compiled, case-insensitive
    return re.compile(pattern, re.I)


_IT_LOCAL = r"(?:dalla mia musica|dal disco|in locale|dalla libreria)"
_EN_LOCAL = r"(?:from my (?:music|library)|from the library|locally)"

# One entry per routing step; the handle() flow is identical across languages.
# ``service`` is a template expanded per streaming service name.
PATTERNS = {
    "it": {
        "is_play": _c(r"\b(?:metti|rimetti|riproduci|suona|fai\s+partire|voglio\s+ascoltare)\b"),
        "pause_explicit": _c(r"\bin\s+pausa\b"),
        "pause": _c(r"\b(pausa|ferma|stop)\b"),
        # Bare "play" always resumes, even though it is also a play verb.
        "resume_explicit": _c(r"^play\s*$"),
        "resume": _c(r"\b(riprendi|riparti|continua|play)\b"),
        "next": _c(r"\b(success|prossim|avanti|salta)"),
        "prev": _c(r"\b(precedent|indietro|torna)"),
        "vol_up": _c(r"(alza|aumenta).{0,12}volume|pi[uù] forte"),
        "vol_down": _c(r"(abbassa|diminuisci).{0,12}volume|pi[uù] piano"),
        "nowplaying": _c(r"(cosa|che).{0,8}(suona|canzone|ascolt)"),
        "choose_number": _c(r"(?:metti|scegli|voglio)?\s*(?:(?:la|il)\s+)?numero\s+([a-z0-9]+)\s*$"),
        # "la 2" and ordinals: "la seconda", "metti la seconda canzone"
        "choose_article": _c(r"(?:metti|scegli|voglio)?\s*(?:la|il)\s+([a-z0-9]+)"
                             r"(?:\s+(?:canzone|brano|opzione))?\s*$"),
        "local_prefix": _c(rf"{_IT_LOCAL}\s+(?:metti\s+|riproduci\s+)?(.+)$"),
        "local_suffix": _c(rf"(?:metti|riproduci|suona)\s+(.+?)\s+{_IT_LOCAL}\s*$"),
        "service": r"(?:da {s}|su {s}|con {s})\s+(?:metti\s+|riproduci\s+)?(.+)$",
        "albums_list": _c(r"(?:quali|che).{0,12}album.{0,4}di\s+(.+)$"),
        "toptracks": _c(r"(?:quali.{0,10}brani|top tracks|brani.{0,15}ascoltati).*?di\s+(.+)$"),
        "name_pick": _c(r"(?:(?:voglio\s+ascoltare|fai\s+partire|metti|scegli|riproduci|suona|voglio)\s+)?(.+)$"),
        "album": _c(r"(?:metti|riproduci|fai partire)\s+l['’]?\s*album\s+(.+)$"),
        "playlist": _c(r"(?:metti|riproduci|fai partire)\s+la\s+playlist\s+(.+)$"),
        # Plural only ("canzoni/brani"): "metti la canzone del sole" is a song
        # title (Battisti), not an artist request.
        "artist": _c(r"(?:metti|riproduci|fai partire)\s+"
                     r"(?:(?:la\s+)?musica\s+(?:di|dei|degli|delle|del|della|dell['’])"
                     r"|l['’]?\s*artista"
                     r"|(?:tutte\s+le\s+|le\s+|i\s+)?(?:canzoni|brani)\s+"
                     r"(?:di|dei|degli|delle|del|della|dell['’]))\s+(.+)$"),
        "generic_play": _c(r"(?:riproduci|metti|suona|fai partire|voglio ascoltare)\s+(.+)$"),
    },
    "en": {
        # ``put`` alone (not just "put on") so the suffix form "put X on" is
        # guarded from transport words too ("put Don't Stop Me Now on").
        "is_play": _c(r"\b(?:play|put|start|listen\s+to|i\s+want\s+to\s+(?:hear|listen\s+to))\b"),
        "pause_explicit": _c(r"\bon\s+pause\b"),
        "pause": _c(r"\b(pause|stop|halt)\b"),
        # Bare "play" resumes (like a remote's ▶), even though it's a play verb.
        "resume_explicit": _c(r"^(?:play|resume)\s*$"),
        "resume": _c(r"\b(resume|continue|unpause|keep\s+going)\b"),
        "next": _c(r"\b(next|skip|forward)\b"),
        "prev": _c(r"\b(previous|go\s+back|back)\b"),
        "vol_up": _c(r"(?:turn|put|pump|crank)?\s*up.{0,12}volume|volume\s+up"
                     r"|(?:raise|increase)\s.{0,8}volume|turn\s+it\s+up|louder"),
        "vol_down": _c(r"(?:turn|put)?\s*down.{0,12}volume|volume\s+down"
                       r"|(?:lower|decrease|reduce)\s.{0,8}volume|turn\s+it\s+down"
                       r"|quieter|softer"),
        # Loose on purpose (mirrors the Italian style) and gated by is_play in
        # handle(), so "play What Is This Feeling" stays a play command. Also
        # covers the apostrophe-less ASR form "whats playing".
        "nowplaying": _c(r"\bwhat'?s?\b.{0,10}(?:playing|song|this\b)"
                         r"|now\s+playing|who\s+(?:is\s+this|sings)"),
        "choose_number": _c(r"(?:play|choose|pick|put\s+on)?\s*(?:the\s+)?number\s+([a-z0-9]+)\s*$"),
        # "the 2" and ordinals: "the second", "play the second one/song"
        "choose_article": _c(r"(?:play|choose|pick|put\s+on)?\s*the\s+([a-z0-9]+)"
                             r"(?:\s+(?:one|song|track|option))?\s*$"),
        "local_prefix": _c(rf"{_EN_LOCAL}\s+(?:play\s+|put\s+on\s+)?(.+)$"),
        "local_suffix": _c(rf"(?:play|put\s+on|start)\s+(.+?)\s+{_EN_LOCAL}\s*$"),
        "service": r"(?:from {s}|on {s}|with {s})\s+(?:play\s+|put\s+on\s+)?(.+)$",
        "albums_list": _c(r"(?:which|what).{0,12}albums?.{0,16}(?:by|of|from)\s+(.+)$"),
        "toptracks": _c(r"(?:top\s+tracks|best\s+(?:songs|tracks)|most\s+(?:played|listened)"
                        r"|which\s+songs).*?(?:by|of|from)\s+(.+)$"),
        "name_pick": _c(r"(?:(?:i\s+want\s+to\s+(?:hear|listen\s+to)|play|choose|pick|put\s+on|start)\s+)?(.+)$"),
        "album": _c(r"(?:play|put\s+on|start)\s+(?:the\s+)?album\s+(.+)$"),
        "playlist": _c(r"(?:play|put\s+on|start)\s+(?:the\s+)?playlist\s+(.+)$"),
        # Only "by" for songs/tracks: "songs of/from" collide with real titles
        # ("Songs from the Wood", "Songs of Innocence").
        "artist": _c(r"(?:play|put\s+on|start)\s+"
                     r"(?:(?:some\s+|the\s+)?music\s+(?:by|of|from)|something\s+by"
                     r"|the\s+artist|(?:all\s+)?(?:the\s+)?(?:songs?|tracks?)\s+by)\s+(.+)$"),
        "generic_play": _c(r"(?:play|put\s+on|start|listen\s+to"
                           r"|i\s+want\s+to\s+(?:hear|listen\s+to))\s+(.+)$"),
        # Suffix form: "put Dark Side of the Moon on"
        "generic_play_suffix": _c(r"^put\s+(.+?)\s+on\s*$"),
    },
}


# Web Speech rarely transcribes the service names right — they aren't real
# words, so each recognizer writes what it hears in its own language:
#   qobuz -> it «kobuz»/«cobus», en "kaboots"/"cabooze", es «cobús»/«cobos»/
#            «que bus», de «Kobutz»/«Kobuts»/«Kobus», fr «cobusse»/«kobuze»
#   tidal -> it «taidal»/«tidol», en "title", es «Vidal»/«tídal»,
#            de «Titel»/«Taidel»/«Tiedal», fr «tidale»/«tidalle»
# The explicit-source phrase must match what was *heard*, so each service name
# expands to a sound-alike pattern instead of the literal spelling.
_SERVICE_SOUNDS = {
    "tidal": r"(?:t(?:ai|ay|ei|ie|i|í|y)[\s\-]?d[aeoà]?l{1,2}e?"
             r"|titles?|titel|tider|tida|vidal)",
    "qobuz": r"(?:[qkc](?:u?[oóa]|ue)[\s\-]?b(?:oo|[uoaúù])[\s\-]?"
             r"(?:ts|tz|zz|ss|z|s)e?)",
}


def _service_re(name: str) -> str:
    """Regex snippet matching a service name as ASR may transcribe it."""
    return _SERVICE_SOUNDS.get(name, re.escape(name))


# Display names for the source tag in play confirmations.
_SERVICE_LABELS = {"tidal": "TIDAL", "qobuz": "Qobuz"}


def _source_suffix(name) -> str:
    """The localized ' da TIDAL' / ' from your music' tag for a source name
    ('local' or a service), so play replies say which source answered."""
    if not name:
        return ""
    if name == "local":
        return msg("from_local")
    return msg("from_service", service=_SERVICE_LABELS.get(name, name))


class Router:
    def __init__(self, lms, default_service="tidal", services=("tidal", "qobuz")):
        self.lms = lms
        # Streaming sources this router accepts as a ``source`` value; anything
        # else streams from ``default_service`` (also the "auto" fallback).
        self.default_service = default_service
        self.services = tuple(services)
        self.candidates = None  # candidates from the last list command
        # Where those candidates play from ('local' or a service name), so a
        # follow-up pick's confirmation can say the source too.
        self.cand_source = None
        # True when THIS turn opened a numbered list (a list command or a
        # 'did you mean'), so the web client can render tappable choice buttons
        # only for the reply that offers them, not on every later reply.
        self._opened = False

    def _stream_name(self, source):
        """The streaming service a request goes to: ``source`` when it names a
        known service, else the default streaming service."""
        return source if source in self.services else self.default_service

    def _stream(self, source):
        """The LMS client for a streaming request (see :meth:`_stream_name`)."""
        return self.lms.for_service(self._stream_name(source))

    def _tag(self, res, suffix: str):
        """Splice the source tag into a play confirmation ('Riproduco Time.' ->
        'Riproduco Time da Qobuz.'). Only acted-on plays are tagged: misses,
        errors and 'did you mean' questions pass through untouched."""
        if not suffix or not getattr(res, "ok", False) or getattr(res, "kind", None):
            return res
        speech = (res[:-1] if res.endswith(".") else str(res)) + suffix + "."
        return actions.ActionResult(speech, ok=True, candidates=res.candidates,
                                    kind=res.kind, terms=res.terms)

    def _remember(self, result: dict, src=None) -> str:
        self.candidates = result["candidates"] or None
        self._opened = bool(self.candidates)
        if self.candidates:
            self.cand_source = src
        return result["speech"]

    def _played(self, result, src=None):
        """Remember any 'did you mean' candidates a play result carried (and
        their source), so a follow-up 'metti la N' / name-pick can choose."""
        cands = getattr(result, "candidates", None)
        if cands:
            self.candidates = cands
            self.cand_source = src
            self._opened = True
        return result

    def _resolve(self, arg: str, stream_fn, source: str):
        if source == "local":
            return self._played(actions.play_local(self.lms, arg), "local")
        name = self._stream_name(source)
        stream = self.lms.for_service(name)
        if source == "auto":
            # Auto: prefer a confident local-library hit, else fall back to the
            # default streaming service (no cascading across services).
            # play_local only plays when it matches, so a miss has no effect.
            res = actions.play_local(self.lms, arg)
            if getattr(res, "ok", False):
                return self._played(res, "local")
        return self._played(self._tag(stream_fn(stream, arg), _source_suffix(name)),
                            name)

    def handle_many(self, alternatives, source: str = "tidal", lang: str = "it") -> dict:
        """Try each speech-recognition alternative until one is a hit.

        Web Speech (it-IT) often mangles English names ('Audioslave' -> 'sfigati');
        a lower-ranked alternative frequently transcribes them better. Playback
        happens only on a hit, so trying a miss has no side effect. Returns
        ``{'speech', 'used'}`` where ``used`` is the alternative that was kept
        (the primary one if none matched)."""
        set_lang(lang)
        alts = [a for a in (alternatives or []) if (a or "").strip()]
        if not alts:
            return {"speech": msg("heard_nothing"), "used": "", "ok": False,
                    "terms": [], "choices": []}
        primary = None
        for alt in alts:
            speech = self.handle(alt, source, lang)
            # A result is a hit when it acted on the request. ActionResult carries
            # an explicit ``.ok``; for any plain string we fall back to the old
            # "Non ..." heuristic so nothing regresses (Italian-only, harmless
            # in English: EN misses are ActionResults and carry .ok).
            ok = getattr(speech, "ok", not speech.strip().lower().startswith("non "))
            if primary is None:
                primary = (speech, alt, ok)
            if ok:
                return {"speech": speech, "used": alt, "ok": True,
                        "terms": list(getattr(speech, "terms", [])),
                        "choices": self._choices()}
        return {"speech": primary[0], "used": primary[1], "ok": primary[2],
                "terms": list(getattr(primary[0], "terms", [])),
                "choices": self._choices()}

    def _choices(self) -> list:
        """Tappable numbered choices for the web app, but only for a reply that
        just opened a list; ``[]`` otherwise. Reuses ``actions._label`` so the
        button text matches the spoken '1: Title di Artist' read-out."""
        if not self._opened or not self.candidates:
            return []
        return [{"n": i + 1, "label": actions._label(c)}
                for i, c in enumerate(self.candidates)]

    def handle(self, text: str, source: str = "tidal", lang: str = "it") -> str:
        # Reset per turn; _remember/_played set it when this turn opens a list.
        # A bare 'metti la N' pick doesn't re-open one, so its reply carries no
        # buttons (the list was already shown on the previous reply).
        self._opened = False
        set_lang(lang)
        P = PATTERNS.get(lang) or PATTERNS["it"]
        t = (text or "").strip()
        # Dictation often appends final punctuation ("Metti la 2."): it would
        # break the $-anchored patterns (picks, suffix forms) and leak into the
        # search terms, so strip it.
        t = re.sub(r"[.!?…]+$", "", t).strip()
        if not t:
            return msg("heard_nothing")

        # A play command carries a title after the verb; its transport-sounding
        # words ("Don't Stop Me Now" -> "stop") must NOT be mistaken for
        # transport controls, or the song is never played. "in pausa"/"on pause"
        # stays an explicit pause even with a play verb ("metti in pausa").
        is_play = bool(P["is_play"].search(t))

        # 1) transport & info (source-independent)
        if P["pause_explicit"].search(t) or (not is_play and P["pause"].search(t)):
            return actions.pause(self.lms)
        # Bare "play" is a resume even though "play" is also a play verb.
        if P["resume_explicit"].match(t) or (not is_play and P["resume"].search(t)):
            return actions.resume(self.lms)
        if not is_play and P["next"].search(t):
            return actions.next_track(self.lms)
        if not is_play and P["prev"].search(t):
            return actions.previous_track(self.lms)
        if P["vol_up"].search(t):
            return actions.change_volume(self.lms, "up")
        if P["vol_down"].search(t):
            return actions.change_volume(self.lms, "down")
        # Gated by is_play so a title like "What Is This Feeling" still plays.
        if not is_play and P["nowplaying"].search(t):
            return actions.now_playing(self.lms)

        # 2) choose from the last read-out list by position. Accepts a digit or a
        # spoken number word ("la 2" / "the two", "numero tre" / "number three");
        # ASR gives words, not digits. The explicit forms answer even with no
        # open list (helpful hint); a bare numeral only counts as a pick while a
        # list is open, so it can't swallow an unrelated one-word command.
        m = P["choose_number"].match(t) or P["choose_article"].match(t)
        number = _as_number(m.group(1), ordinals=bool(self.candidates)) if m else None
        if number is None and self.candidates:
            bare = re.match(r"([a-z0-9]+)\s*$", t, re.I)
            number = _as_number(bare.group(1), ordinals=True) if bare else None
        if number is not None:
            return self._tag(actions.choose_from(self.lms, self.candidates, number),
                             _source_suffix(self.cand_source))

        # 3) explicit source override phrases (win over the selector). Service
        # phrases route only the generic play_song; album/artist follow the
        # selector.
        m = P["local_prefix"].search(t)
        if m:
            return self._played(actions.play_local(self.lms, m.group(1).strip()), "local")
        m = P["local_suffix"].search(t)
        if m:
            return self._played(actions.play_local(self.lms, m.group(1).strip()), "local")
        for service in self.services:
            m = re.search(P["service"].format(s=_service_re(service)), t, re.I)
            if m:
                res = actions.play_song(self.lms.for_service(service), m.group(1).strip())
                return self._played(self._tag(res, _source_suffix(service)), service)

        # 4) lists that open a numbered choice
        m = P["albums_list"].search(t)
        if m:  # "quali album ho di X" / "which albums do I have by X" -> local
            return self._remember(
                actions.local_albums_list(self.lms, m.group(1).strip()), "local")
        m = P["toptracks"].search(t)
        if m:  # top tracks -> streaming (selected or default service)
            return self._remember(
                actions.top_tracks_list(self._stream(source), m.group(1).strip()),
                self._stream_name(source))

        # 4b) name-based choice from the last read-out list (only while a list is
        # open). "metti Supernatural" / "play Supernatural" / bare "Supernatural"
        # -> the remembered candidate, never a fresh whole-library search.
        # choose_by_name returns None when nothing matches ("not a selection"),
        # so routing continues to the generic branches below.
        if self.candidates:
            m = P["name_pick"].match(t)
            if m:
                chosen = actions.choose_by_name(
                    self.lms, self.candidates, m.group(1).strip()
                )
                if chosen is not None:
                    return self._tag(chosen, _source_suffix(self.cand_source))

        # 5) album — streaming or local per selector
        m = P["album"].search(t)
        if m:
            return self._resolve(m.group(1).strip(), actions.play_album, source)

        # 6) playlist (streaming: selected or default service)
        m = P["playlist"].search(t)
        if m:
            name = self._stream_name(source)
            return self._tag(
                actions.play_playlist(self.lms.for_service(name), m.group(1).strip()),
                _source_suffix(name))

        # 7) artist — streaming or local per selector
        m = P["artist"].search(t)
        if m:
            return self._resolve(m.group(1).strip(), actions.play_artist, source)

        # 8) generic play — streaming or local per selector
        m = P["generic_play"].search(t)
        if not m and "generic_play_suffix" in P:  # EN: "put Dark Side on"
            m = P["generic_play_suffix"].match(t)
        if m:
            return self._resolve(m.group(1).strip(), actions.play_song, source)

        return msg("router_fallback")
