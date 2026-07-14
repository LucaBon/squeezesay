"""Local Italian intent router.

Maps free Italian text (from the browser's speech recognition, or a text box) to
the SAME action functions used by the Alexa skill (``actions.py`` + ``lms.py``).
No cloud, no Alexa — just rules over the transcribed text.

Music sources:
- **local library** (USB disk) and the **streaming services** (TIDAL, Qobuz).
  Ambiguous commands ("riproduci X", "metti l'album X", "metti la musica di X")
  follow the ``source`` passed by the UI selector; "auto" tries local first,
  then the configured default streaming service. Explicit phrases always win:
  "dalla mia musica …" forces local, "da tidal …" / "da qobuz …" force that
  service, regardless of the selector.

State (the last read-out list) is kept in-instance for the "metti la N" choice.
"""

from __future__ import annotations

import re

import actions
from messages import msg

_LOCAL = r"(?:dalla mia musica|dal disco|in locale|dalla libreria)"
_TIDAL = r"(?:da tidal|su tidal|con tidal)"
_QOBUZ = r"(?:da qobuz|su qobuz|con qobuz)"

# Web Speech (it-IT) transcribes a spoken position as a word ("tre"), not "3".
_NUM_WORDS = {
    "uno": 1, "un": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
    # common English forms the it-IT recognizer sometimes emits
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}


def _as_number(token):
    """A spoken position -> int, or None if the token isn't a number."""
    token = (token or "").strip().lower()
    if token.isdigit():
        return int(token)
    return _NUM_WORDS.get(token)


class Router:
    def __init__(self, lms, default_service="tidal", services=("tidal", "qobuz")):
        self.lms = lms
        # Streaming sources this router accepts as a ``source`` value; anything
        # else streams from ``default_service`` (also the "auto" fallback).
        self.default_service = default_service
        self.services = tuple(services)
        self.candidates = None  # candidates from the last list command
        # True when THIS turn opened a numbered list (a list command or a
        # 'did you mean'), so the web client can render tappable choice buttons
        # only for the reply that offers them, not on every later reply.
        self._opened = False

    def _stream(self, source):
        """The LMS client for a streaming request: bound to ``source`` when
        it names a known service, else to the default streaming service."""
        name = source if source in self.services else self.default_service
        return self.lms.for_service(name)

    def _remember(self, result: dict) -> str:
        self.candidates = result["candidates"] or None
        self._opened = bool(self.candidates)
        return result["speech"]

    def _played(self, result):
        """Remember any 'did you mean' candidates a play result carried, so a
        follow-up 'metti la N' / name-pick can choose from them."""
        cands = getattr(result, "candidates", None)
        if cands:
            self.candidates = cands
            self._opened = True
        return result

    def _play_auto(self, arg: str, stream_fn, stream):
        """Auto source: prefer a confident local-library hit, else fall back to
        the default streaming service (no cascading across services).
        play_local only plays when it matches, so a miss has no effect."""
        res = actions.play_local(self.lms, arg)
        if getattr(res, "ok", False):
            return res
        return stream_fn(stream, arg)

    def _resolve(self, arg: str, stream_fn, source: str):
        if source == "local":
            return self._played(actions.play_local(self.lms, arg))
        stream = self._stream(source)
        if source == "auto":
            return self._played(self._play_auto(arg, stream_fn, stream))
        return self._played(stream_fn(stream, arg))

    def handle_many(self, alternatives, source: str = "tidal") -> dict:
        """Try each speech-recognition alternative until one is a hit.

        Web Speech (it-IT) often mangles English names ('Audioslave' -> 'sfigati');
        a lower-ranked alternative frequently transcribes them better. A response
        starting with 'Non ' means nothing matched (not found / not understood /
        unreachable), so we fall through to the next alternative. Playback happens
        only on a hit, so trying a miss has no side effect. Returns
        ``{'speech', 'used'}`` where ``used`` is the alternative that was kept
        (the primary one if none matched)."""
        alts = [a for a in (alternatives or []) if (a or "").strip()]
        if not alts:
            return {"speech": msg("heard_nothing"), "used": "", "ok": False,
                    "terms": [], "choices": []}
        primary = None
        for alt in alts:
            speech = self.handle(alt, source)
            # A result is a hit when it acted on the request. ActionResult carries
            # an explicit ``.ok``; for any plain string we fall back to the old
            # "Non ..." heuristic so nothing regresses.
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

    def handle(self, text: str, source: str = "tidal") -> str:
        # Reset per turn; _remember/_played set it when this turn opens a list.
        # A bare 'metti la N' pick doesn't re-open one, so its reply carries no
        # buttons (the list was already shown on the previous reply).
        self._opened = False
        t = (text or "").strip()
        if not t:
            return msg("heard_nothing")

        # A play command carries a title after the verb; its transport-sounding
        # words ("Don't Stop Me Now" -> "stop", "Play" -> "play") must NOT be
        # mistaken for transport controls, or the song is never played. "in pausa"
        # stays an explicit pause even with "metti" ("metti in pausa").
        is_play = bool(re.search(
            r"\b(?:metti|rimetti|riproduci|suona|fai\s+partire|voglio\s+ascoltare)\b",
            t, re.I))

        # 1) transport & info (source-independent)
        if re.search(r"\bin\s+pausa\b", t, re.I) or (
                not is_play and re.search(r"\b(pausa|ferma|stop)\b", t, re.I)):
            return actions.pause(self.lms)
        if not is_play and re.search(r"\b(riprendi|riparti|continua|play)\b", t, re.I):
            return actions.resume(self.lms)
        if not is_play and re.search(r"\b(success|prossim|avanti|salta)", t, re.I):
            return actions.next_track(self.lms)
        if not is_play and re.search(r"\b(precedent|indietro|torna)", t, re.I):
            return actions.previous_track(self.lms)
        if re.search(r"(alza|aumenta).{0,12}volume|pi[uù] forte", t, re.I):
            return actions.change_volume(self.lms, "up")
        if re.search(r"(abbassa|diminuisci).{0,12}volume|pi[uù] piano", t, re.I):
            return actions.change_volume(self.lms, "down")
        if re.search(r"(cosa|che).{0,8}(suona|canzone|ascolt)", t, re.I):
            return actions.now_playing(self.lms)

        # 2) choose from the last read-out list by position. Accepts a digit or a
        # spoken number word ("la 2", "numero tre", bare "tre"/"3"); it-IT ASR
        # gives words, not digits. Explicit "la N"/"numero N" answer even with no
        # open list (helpful hint); a bare numeral only counts as a pick while a
        # list is open, so it can't swallow an unrelated one-word command.
        m = re.match(
            r"(?:metti|scegli|voglio)?\s*(?:(?:la|il)\s+)?numero\s+([a-z0-9]+)\s*$", t, re.I
        ) or re.match(
            r"(?:metti|scegli|voglio)?\s*(?:la|il)\s+([a-z0-9]+)\s*$", t, re.I
        )
        number = _as_number(m.group(1)) if m else None
        if number is None and self.candidates:
            bare = re.match(r"([a-z0-9]+)\s*$", t, re.I)
            number = _as_number(bare.group(1)) if bare else None
        if number is not None:
            return actions.choose_from(self.lms, self.candidates, number)

        # 3) explicit source override phrases (win over the selector). Like the
        # original TIDAL phrase, service phrases route only the generic
        # play_song; album/artist follow the selector.
        m = re.search(rf"{_LOCAL}\s+(?:metti\s+|riproduci\s+)?(.+)$", t, re.I)
        if m:
            return self._played(actions.play_local(self.lms, m.group(1).strip()))
        m = re.search(rf"(?:metti|riproduci|suona)\s+(.+?)\s+{_LOCAL}\s*$", t, re.I)
        if m:
            return self._played(actions.play_local(self.lms, m.group(1).strip()))
        m = re.search(rf"{_TIDAL}\s+(?:metti\s+|riproduci\s+)?(.+)$", t, re.I)
        if m:
            return self._played(
                actions.play_song(self.lms.for_service("tidal"), m.group(1).strip()))
        m = re.search(rf"{_QOBUZ}\s+(?:metti\s+|riproduci\s+)?(.+)$", t, re.I)
        if m:
            return self._played(
                actions.play_song(self.lms.for_service("qobuz"), m.group(1).strip()))

        # 4) lists that open a numbered choice
        m = re.search(r"(?:quali|che).{0,12}album.{0,4}di\s+(.+)$", t, re.I)
        if m:  # "quali album ho di X" -> your local library
            return self._remember(actions.local_albums_list(self.lms, m.group(1).strip()))
        m = re.search(
            r"(?:quali.{0,10}brani|top tracks|brani.{0,15}ascoltati).*?di\s+(.+)$", t, re.I
        )
        if m:  # top tracks -> streaming (selected or default service)
            return self._remember(
                actions.top_tracks_list(self._stream(source), m.group(1).strip()))

        # 4b) name-based choice from the last read-out list (only while a list is
        # open). "metti Supernatural" / "l'album Supernatural" / bare
        # "Supernatural" -> the remembered candidate, never a fresh whole-library
        # search. choose_by_name returns None when nothing matches ("not a
        # selection"), so routing continues to the generic branches below.
        if self.candidates:
            m = re.match(
                r"(?:(?:voglio\s+ascoltare|fai\s+partire|metti|scegli|riproduci"
                r"|suona|voglio)\s+)?(.+)$",
                t,
                re.I,
            )
            if m:
                chosen = actions.choose_by_name(
                    self.lms, self.candidates, m.group(1).strip()
                )
                if chosen is not None:
                    return chosen

        # 5) album — streaming or local per selector
        m = re.search(r"(?:metti|riproduci|fai partire)\s+l['’]?\s*album\s+(.+)$", t, re.I)
        if m:
            return self._resolve(m.group(1).strip(), actions.play_album, source)

        # 6) playlist (streaming: selected or default service)
        m = re.search(r"(?:metti|riproduci|fai partire)\s+la\s+playlist\s+(.+)$", t, re.I)
        if m:
            return actions.play_playlist(self._stream(source), m.group(1).strip())

        # 7) artist — streaming or local per selector. Accepts "(la) musica di/
        # dei/degli/delle/del/della/dell' X", "l'artista X", "le canzoni di X".
        m = re.search(
            r"(?:metti|riproduci|fai partire)\s+"
            r"(?:(?:la\s+)?musica\s+(?:di|dei|degli|delle|del|della|dell['’])"
            r"|l['’]?\s*artista|le canzoni di)\s+(.+)$",
            t,
            re.I,
        )
        if m:
            return self._resolve(m.group(1).strip(), actions.play_artist, source)

        # 8) generic play — streaming or local per selector
        m = re.search(r"(?:riproduci|metti|suona|fai partire|voglio ascoltare)\s+(.+)$", t, re.I)
        if m:
            return self._resolve(m.group(1).strip(), actions.play_song, source)

        return msg("router_fallback")
