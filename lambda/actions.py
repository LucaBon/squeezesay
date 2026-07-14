"""Voice-action business logic, kept as pure functions for easy testing.

Each function takes an :class:`lms.LMSClient` (or any object with the same
methods) plus already-extracted slot values, performs the LMS/TIDAL operation,
and returns a speech string. The wording lives in the ``messages`` catalog
(referenced by key — see :mod:`messages` for the i18n plan); today the only
catalog is Italian. All LMS failures are turned into a friendly message
instead of raising, so the skill never crashes on a network hiccup.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Dict, List, Optional

from blocklist_store import BlocklistStoreError
from lms import LMSError
from messages import msg

# Legacy alias, frozen in the default language at import: kept for external
# callers/tests; the code paths below call msg() so replies follow the
# per-request language.
ERR_UNREACHABLE = msg("err_unreachable")
VOLUME_STEP = 5
LIST_LIMIT = 5

# Fuzzy-match gating (see _score / _rank / play_song). Title scoring only *overrides*
# TIDAL's own relevance ranking for a clear EXACT title match (e.g. "Money" over
# "Money for Nothing"). For anything else — an artist-name or partial query, or
# padded junk titles that merely contain all the words — we trust TIDAL's ordering,
# which also weighs the artist/full text the bare song titles don't expose. Field
# testing showed title-only scoring can't tell a good partial match from padded
# junk, so we don't second-guess TIDAL with a "did you mean"; the spoken
# confirmation ("Riproduco X di Y") is the safety net instead.
# CONFIDENT_SCORE is used by tools/probe_lms.py to flag, in a dry run, whether any
# title strongly matches the query.
CONFIDENT_SCORE = 0.72
EXACT_SCORE = 0.98   # normalized-equal title -> override TIDAL and play this one
DIDYOUMEAN_LIMIT = 3  # read back at most the top 3 when asking "which one?"


class ActionResult(str):
    """A speech string that also carries structured outcome data.

    Subclassing ``str`` keeps every existing caller and test working (equality,
    ``startswith``, ``.speak(...)``), while new callers can read ``.ok`` — did we
    act on the request? — and ``.candidates`` — a numbered list to disambiguate
    from. ``handle_many`` uses ``.ok`` instead of sniffing the ``"Non "`` prefix.
    """

    def __new__(cls, speech, *, ok=True, candidates=None, kind=None, terms=None):
        obj = super().__new__(cls, speech)
        obj.ok = ok
        obj.candidates = list(candidates or [])
        obj.kind = kind
        # Foreign names (title/artist/album/playlist) that appear verbatim in the
        # speech, so the web client can read those parts in their own language
        # while the Italian frame is read by an Italian voice.
        obj.terms = [t for t in (terms or []) if t]
        return obj


def _score(query: Optional[str], text: Optional[str]) -> float:
    """Similarity of a candidate ``text`` to the requested ``query`` in 0..1,
    accent/case-insensitive. Rewards the query's words all appearing in the
    candidate (so 'time' matches 'Time (Remastered)') and blends in a character
    ratio for near-misses/typos."""
    q = _normalize(query)
    t = _normalize(text)
    if not q or not t:
        return 0.0
    if q == t:
        return 1.0
    q_tokens = set(q.split())
    t_tokens = set(t.split())
    containment = len(q_tokens & t_tokens) / len(q_tokens) if q_tokens else 0.0
    ratio = difflib.SequenceMatcher(None, q, t).ratio()
    score = 0.6 * containment + 0.4 * ratio
    # Strong match when one side's words are wholly contained in the other: every
    # requested word is in the title ('time' -> 'Time (Remastered)'), OR the whole
    # title is in the request ('Comfortably Numb' <- 'comfortably numb pink floyd',
    # where the user appended the artist to disambiguate).
    if q_tokens and (q_tokens <= t_tokens or t_tokens <= q_tokens):
        score = max(score, 0.95)
    return score


def _rank(query: Optional[str], items: List[Dict], key: str = "title") -> List:
    """Return ``[(score, item), ...]`` sorted by descending match score against
    ``query``, keeping the original (TIDAL relevance) order as the tiebreaker."""
    scored = [(_score(query, it.get(key)), i, it) for i, it in enumerate(items)]
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [(sc, it) for sc, _i, it in scored]


# Leading filler the ASR/user often prepends ("metti la canzone X") that would
# pollute the search. Stripped before matching so "la canzone love" -> "love".
_LEAD_FILLER = re.compile(
    r"^(?:la\s+canzone|il\s+brano|la\s+traccia|il\s+pezzo|la\s+song|the\s+song)\s+",
    re.IGNORECASE,
)


def _strip_lead_filler(text: Optional[str]) -> str:
    return _LEAD_FILLER.sub("", (text or "").strip()).strip()


LOCAL_CONFIDENT = CONFIDENT_SCORE  # a local match must clearly fit the query to win


def _label(cand: Dict) -> str:
    """'Title di Artist' for a candidate, else just the title."""
    title = cand.get("title") or msg("generic_track")
    artist = cand.get("artist")
    return msg("label_title_artist", title=title, artist=artist) if artist else title


def _dedup_by_title_artist(cands: List[Dict]) -> List[Dict]:
    """Collapse candidates with the same (title, artist) — several editions of the
    same recording shouldn't look like an ambiguous choice."""
    seen = set()
    out = []
    for c in cands:
        key = (_normalize(c.get("title")), _normalize(c.get("artist")))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _ndistinct_titles(cands: List[Dict]) -> int:
    return len({_normalize(c.get("title")) for c in cands})


def _did_you_mean(query: Optional[str], cands: List[Dict]) -> ActionResult:
    """Ask which of several candidates to play, reading back the top ones as
    '1: Title di Artist, ...'. ``cands`` are choose_from-ready (TIDAL {title,url}
    or local {title,action,arg}); callers pass an already blocked-filtered list."""
    picks = cands[:DIDYOUMEAN_LIMIT]
    listing = ", ".join(
        msg("enum_item", n=i + 1, name=_label(c)) for i, c in enumerate(picks)
    )
    terms = []
    for c in picks:
        if c.get("title"):
            terms.append(c["title"])
        if c.get("artist"):
            terms.append(c["artist"])
    speech = msg("didyoumean", query=query, listing=listing)
    return ActionResult(speech, ok=True, candidates=picks, kind="disambiguate", terms=terms)


def _play_tidal_track(lms, track: Dict, fallback_title: Optional[str], *, guard: Optional[Guard] = None) -> ActionResult:
    if guard and guard.blocks(track.get("title")):
        return ActionResult(msg("blocked"), ok=False)
    lms.play_url(track["url"])
    speech, terms = _confirm_song(lms, track, fallback_title)
    return ActionResult(speech, ok=True, terms=terms)



# Spoken when a restricted (non-owner) speaker asks for a blocked song/singer.
BLOCKED_SPEECH = msg("blocked")
# Spoken when a non-owner tries to change the blocklist by voice.
NOT_OWNER_SPEECH = msg("not_owner")


def _normalize(text: Optional[str]) -> str:
    """Lowercase + strip accents + collapse spaces, for accent/case-insensitive
    Italian matching ('Andrà' -> 'andra')."""
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip()


def parse_blocklist(raw) -> List[str]:
    """Turn a comma/newline string (or list) into de-duplicated display terms.

    Terms are kept in their original spoken/typed form (so they read back nicely
    in ``list_blocks``); matching normalizes on the fly in :func:`is_blocked`."""
    if not raw:
        return []
    parts = raw if isinstance(raw, (list, tuple)) else re.split(r"[,\n]", str(raw))
    out: List[str] = []
    seen = set()
    for part in parts:
        term = str(part).strip()
        norm = _normalize(term)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(term)
    return out


def is_blocked(text: Optional[str], blocklist: Optional[List[str]]) -> bool:
    """True if any blocklist term appears in ``text`` as a whole word (normalized).

    Word-boundary matching avoids false positives like a blocked 'ass' hitting
    'bass', while still catching multi-word terms and inflections around them."""
    norm = _normalize(text)
    if not norm:
        return False
    for term in blocklist or []:
        term_norm = _normalize(term)
        if term_norm and re.search(rf"\b{re.escape(term_norm)}\b", norm):
            return True
    return False


class Guard:
    """Speaker-based access gate. When ``restricted`` is True, any request text
    matching ``blocklist`` is refused with :data:`BLOCKED_SPEECH`. When it's
    False the guard is transparent, so passing ``guard=None`` is also a no-op."""

    def __init__(self, restricted: bool = False, blocklist: Optional[List[str]] = None):
        self.restricted = restricted
        self.blocklist = blocklist or []

    def blocks(self, *texts: Optional[str]) -> bool:
        if not self.restricted:
            return False
        return any(is_blocked(t, self.blocklist) for t in texts if t)

# Splits "titolo dall'album X" / "title from album X" into title + album.
_ALBUM_SEP = re.compile(
    r"\b(?:dall['’]?\s*album|dell['’]?\s*album|dal\s+disco|dall['’]?\s*disco|"
    r"from\s+(?:the\s+)?album)\b",
    re.IGNORECASE,
)
# Splits "titolo di/dei/degli X" / "title by X" into title + artist. Used only to
# *rank* results (the search still runs on the full text), so a mis-split — e.g. a
# title that itself contains "di" — degrades gracefully instead of breaking.
_ARTIST_SEP = re.compile(
    r"\b(?:dei|degli|delle|della|dell['’]|del|di|by)\s+", re.IGNORECASE
)


def parse_song_query(text: Optional[str]) -> Dict[str, Optional[str]]:
    """Parse a free-text song request into ``{'title', 'artist', 'album'}``.

    "Time dall'album Dark Side" -> title='Time', album='Dark Side'.
    "Comfortably Numb dei Pink Floyd" -> title='Comfortably Numb', artist='Pink Floyd'.
    "Comfortably Numb Pink Floyd" (no connector) stays title-only."""
    text = _strip_lead_filler(text)
    album = None
    match = _ALBUM_SEP.search(text)
    if match:
        pre = text[: match.start()].strip()
        album = text[match.end():].strip() or None
    else:
        pre = text
    title, artist = pre, None
    am = _ARTIST_SEP.search(pre)
    if am:
        head, tail = pre[: am.start()].strip(), pre[am.end():].strip()
        if head and tail:  # both sides non-empty -> treat as "title <conn> artist"
            title, artist = head, tail
    return {"title": title or None, "artist": artist, "album": album}


def play_song(lms, query: Optional[str], *, guard: Optional[Guard] = None) -> ActionResult:
    parsed = parse_song_query(query)
    title, artist, album = parsed["title"], parsed["artist"], parsed["album"]
    if not title and not album:
        return ActionResult(msg("ask_title"), ok=False)
    if guard and guard.blocks(title, artist, album):
        return ActionResult(msg("blocked"), ok=False)
    try:
        if album:
            return _play_from_album(lms, title, album, guard=guard)
        # Search on the full text (title + artist) — TIDAL's full-text search wants
        # both — then rank/disambiguate using the parsed parts.
        search_text = " ".join(p for p in (title, artist) if p) or title
        tracks = lms.search_tracks(search_text)
        if not tracks:
            return ActionResult(msg("no_track_found", title=title), ok=False)
        return _resolve_song(lms, tracks, title, artist, guard=guard)
    except LMSError:
        return ActionResult(msg("err_unreachable"), ok=False)


def _resolve_song(lms, tracks, title, artist, *, guard=None) -> ActionResult:
    """Pick a track, disambiguate, or ask — from the TIDAL results and the parsed
    title/artist. Candidates stay in TIDAL's own relevance order, so padded-junk
    titles ranked low never reach the shortlist."""
    exacts = [t for t in tracks if _score(title, t.get("title")) >= EXACT_SCORE]
    strong = [t for t in tracks if _score(title, t.get("title")) >= CONFIDENT_SCORE]
    # 1) An artist was named -> play the matching edition (search_tracks carries the
    #    artist, so this picks the right one among identical-title songs).
    if artist and strong:
        best = max(strong[:DIDYOUMEAN_LIMIT], key=lambda t: _score(artist, t.get("artist")))
        if _score(artist, best.get("artist")) >= CONFIDENT_SCORE:
            return _play_tidal_track(lms, best, title, guard=guard)
    # 2) Exact title match -> play TIDAL's top exact (e.g. "Money" over "Money for
    #    Nothing"). 3) No title match at all -> trust TIDAL's own ranking.
    if exacts:
        return _play_tidal_track(lms, exacts[0], title, guard=guard)
    if not strong:
        return _play_tidal_track(lms, tracks[0], title, guard=guard)
    # 4) Several strong partial matches. One song (same title) -> play the top; if
    #    genuinely different titles -> ask the top 3.
    head = strong[:DIDYOUMEAN_LIMIT]
    if guard and guard.restricted:
        head = [t for t in head if not is_blocked(t.get("title"), guard.blocklist)]
    if not head:
        return ActionResult(msg("no_track_found", title=title), ok=False)
    if _ndistinct_titles(head) < 2:
        return _play_tidal_track(lms, head[0], title, guard=guard)
    return _did_you_mean(title, _dedup_by_title_artist(head))


def _confirm_song(lms, track: Dict, fallback_title: Optional[str]):
    """Confirm what's playing, adding the artist when known. Returns
    ``(speech, terms)`` where terms are the foreign name(s) in the speech. TIDAL
    song-search items carry no artist, but the now-playing status does — so we
    read it back once and use it only if the playing title matches what we just
    started (guards against status still showing the previous track)."""
    name = track.get("title") or fallback_title
    artist = track.get("artist")
    if not artist and name:
        try:
            now = lms.now_playing_info()
        except LMSError:
            now = None
        if now and _normalize(now.get("title")) == _normalize(name):
            artist = now.get("artist")
    if artist:
        return msg("playing_by", name=name, artist=artist), [name, artist]
    return msg("playing", name=name), [name]


def _play_from_album(
    lms, title: Optional[str], album: str, *, guard: Optional[Guard] = None
) -> ActionResult:
    result = lms.album_tracks(album)
    if not result["album"]:
        return ActionResult(msg("album_not_found", album=album), ok=False)
    album_name = result["album"]["title"] or album
    if guard and guard.blocks(album_name):
        return ActionResult(msg("blocked"), ok=False)
    if title:
        ranked = _rank(title, result["tracks"])
        if ranked and ranked[0][0] >= CONFIDENT_SCORE:
            track = ranked[0][1]
            if guard and guard.blocks(track.get("title")):
                return ActionResult(msg("blocked"), ok=False)
            lms.play_url(track["url"])
            return ActionResult(
                msg("playing_track_from_album", title=track["title"], album=album_name),
                ok=True, terms=[track["title"], album_name],
            )
        # title not found in that album -> play the whole album instead
        lms.play_browse_item(result["album"]["id"])
        return ActionResult(
            msg("track_not_in_album", title=title, album=album_name),
            ok=True, terms=[title, album_name],
        )
    lms.play_browse_item(result["album"]["id"])
    return ActionResult(
        msg("playing_album", album=album_name), ok=True, terms=[album_name]
    )


def play_album(lms, album: Optional[str], *, guard: Optional[Guard] = None) -> ActionResult:
    album = (album or "").strip()
    if not album:
        return ActionResult(msg("ask_album"), ok=False)
    if guard and guard.blocks(album):
        return ActionResult(msg("blocked"), ok=False)
    try:
        cands = lms.album_candidates(album)
        if not cands:
            return ActionResult(msg("album_not_found", album=album), ok=False)
        item = _rank(album, cands)[0][1]  # best title match, not blindly the first
        if guard and guard.blocks(item.get("title")):
            return ActionResult(msg("blocked"), ok=False)
        lms.play_browse_item(item["id"])
    except LMSError:
        return ActionResult(msg("err_unreachable"), ok=False)
    name = item["title"] or album
    return ActionResult(msg("playing_album", album=name), ok=True, terms=[name])


def play_artist(lms, artist: Optional[str], *, guard: Optional[Guard] = None) -> ActionResult:
    artist = (artist or "").strip()
    if not artist:
        return ActionResult(msg("ask_artist"), ok=False)
    if guard and guard.blocks(artist):
        return ActionResult(msg("blocked"), ok=False)
    try:
        result = lms.artist_top_tracks(artist)
        if not result["artist"]:
            return ActionResult(msg("artist_not_found", artist=artist), ok=False)
        if guard and guard.blocks(result["artist"].get("title")):
            return ActionResult(msg("blocked"), ok=False)
        tracks = result["tracks"]
        if not tracks:
            return ActionResult(msg("artist_unplayable", artist=artist), ok=False)
        lms.play_tracks([t["url"] for t in tracks])
    except LMSError:
        return ActionResult(msg("err_unreachable"), ok=False)
    return ActionResult(msg("playing_artist", artist=artist), ok=True, terms=[artist])


def play_playlist(lms, name: Optional[str], *, guard: Optional[Guard] = None) -> ActionResult:
    name = (name or "").strip()
    if not name:
        return ActionResult(msg("ask_playlist"), ok=False)
    if guard and guard.blocks(name):
        return ActionResult(msg("blocked"), ok=False)
    try:
        cands = lms.playlist_candidates(name)
        if not cands:
            return ActionResult(msg("playlist_not_found", name=name), ok=False)
        item = _rank(name, cands)[0][1]
        if guard and guard.blocks(item.get("title")):
            return ActionResult(msg("blocked"), ok=False)
        lms.play_browse_item(item["id"])
    except LMSError:
        return ActionResult(msg("err_unreachable"), ok=False)
    return ActionResult(msg("playing_playlist", name=name), ok=True, terms=[name])


def pause(lms) -> str:
    try:
        lms.pause()
    except LMSError:
        return msg("err_unreachable")
    return msg("paused")


def resume(lms) -> str:
    try:
        lms.resume()
    except LMSError:
        return msg("err_unreachable")
    return msg("resumed")


def next_track(lms) -> str:
    try:
        lms.next_track()
    except LMSError:
        return msg("err_unreachable")
    return msg("next_track")


def previous_track(lms) -> str:
    try:
        lms.previous_track()
    except LMSError:
        return msg("err_unreachable")
    return msg("previous_track")


def change_volume(lms, direction: str) -> str:
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")
    delta = VOLUME_STEP if direction == "up" else -VOLUME_STEP
    try:
        lms.volume(delta)
    except LMSError:
        return msg("err_unreachable")
    return msg("volume_up") if direction == "up" else msg("volume_down")


def now_playing(lms) -> str:
    try:
        info = lms.now_playing_info()
    except LMSError:
        return msg("err_unreachable")
    if not info or not info.get("title"):
        return ActionResult(msg("nothing_playing"), ok=True)
    title = info.get("title")
    artist = info.get("artist")
    if artist:
        return ActionResult(
            msg("now_playing_by", title=title, artist=artist),
            ok=True, terms=[title, artist],
        )
    return ActionResult(msg("now_playing", title=title), ok=True, terms=[title])


# -- conversational flow: list -> choose by number ------------------------
def top_tracks_list(
    lms, artist: Optional[str], limit: int = LIST_LIMIT, *, guard: Optional[Guard] = None
) -> Dict:
    """Return ``{'speech', 'candidates'}``. The handler reads the list aloud and
    stores ``candidates`` (title+url) in session for a follow-up choice."""
    artist = (artist or "").strip()
    if not artist:
        return {"speech": msg("which_artist"), "candidates": []}
    if guard and guard.blocks(artist):
        return {"speech": msg("blocked"), "candidates": []}
    try:
        tracks = lms.artist_top_tracks(artist)["tracks"]
    except LMSError:
        return {"speech": msg("err_unreachable"), "candidates": []}
    if guard and guard.restricted:  # drop blocked tracks so they can't be chosen
        tracks = [t for t in tracks if not is_blocked(t.get("title"), guard.blocklist)]
    tracks = tracks[:limit]
    if not tracks:
        return {"speech": msg("no_tracks_for", artist=artist), "candidates": []}
    listing = ", ".join(
        msg("enum_item", n=i + 1, name=t["title"]) for i, t in enumerate(tracks)
    )
    speech = msg("top_tracks", artist=artist, listing=listing)
    candidates = [{"title": t["title"], "url": t["url"]} for t in tracks]
    return {"speech": speech, "candidates": candidates}


def _dispatch_play(lms, candidate: Dict) -> None:
    """Play a candidate. Its 'action'/'arg' say how; falls back to a plain URL
    so both TIDAL ({'title','url'}) and local ({'title','action','arg'}) lists work."""
    action = candidate.get("action")
    arg = candidate.get("arg")
    if action == "play_album_id":
        lms.play_local_album(arg)
    elif action == "play_artist_id":
        lms.play_local_artist(arg)
    elif action == "play_track_id":
        lms.play_local_track(arg)
    else:
        lms.play_url(arg or candidate.get("url"))


def choose_from(
    lms,
    candidates: Optional[List[Dict]],
    number: Optional[int],
    *,
    guard: Optional[Guard] = None,
) -> str:
    """Play the N-th candidate from a previously read-out list."""
    if not candidates:
        return msg("no_open_list")
    if number is None or number < 1 or number > len(candidates):
        return msg("pick_range", n=len(candidates))
    chosen = candidates[number - 1]
    if guard and guard.blocks(chosen.get("title")):
        return msg("blocked")
    try:
        _dispatch_play(lms, chosen)
    except LMSError:
        return msg("err_unreachable")
    return msg("playing", name=chosen["title"])


def choose_by_name(
    lms,
    candidates: Optional[List[Dict]],
    name: Optional[str],
    *,
    guard: Optional[Guard] = None,
) -> Optional[str]:
    """Play the candidate whose title matches ``name`` from a previously read-out
    list. Returns ``None`` when there's no list, no name, or no title matches, so
    the caller falls back to a fresh search. ``None`` is deliberately *not* a
    'Non ...' miss string: it means 'this wasn't a selection, keep routing'."""
    if not candidates:
        return None
    query = _normalize(name)
    if not query:
        return None
    chosen = None
    for cand in candidates:  # 1) exact normalized title match wins
        if _normalize(cand.get("title")) == query:
            chosen = cand
            break
    if chosen is None:  # 2) whole-word match either direction
        for cand in candidates:
            title = _normalize(cand.get("title"))
            if not title:
                continue
            if re.search(rf"\b{re.escape(title)}\b", query) or re.search(
                rf"\b{re.escape(query)}\b", title
            ):
                chosen = cand
                break
    if chosen is None:
        return None
    if guard and guard.blocks(chosen.get("title")):
        return msg("blocked")
    try:
        _dispatch_play(lms, chosen)
    except LMSError:
        return msg("err_unreachable")
    return msg("playing", name=chosen["title"])


# -- local library (Music Folder / USB) -----------------------------------
def _local_group(cands, query, kind, action, guard):
    """Confident, distinct candidates for one category, each scored by its own name
    (album/track by title, artist by name) and turned into a choose_from-ready dict."""
    out = []
    for c in cands:
        if guard and guard.restricted and is_blocked(c.get("title"), guard.blocklist):
            continue
        s = _score(query, c.get("title"))
        if s < LOCAL_CONFIDENT:
            continue
        cand = {"title": c.get("title"), "action": action, "arg": c["id"], "_kind": kind}
        if c.get("artist"):
            cand["artist"] = c["artist"]
        out.append((s, cand))
    out.sort(key=lambda x: -x[0])
    return out


def play_local(lms, query: Optional[str], *, guard: Optional[Guard] = None) -> ActionResult:
    """Play from the local library. Candidates are scored (title, or artist name for
    the artist category) so a generic word like 'love' never plays an unrelated row;
    an artist query plays the artist, not one of their albums; and when several
    tracks genuinely match, it asks (local rows carry the artist, so the list reads
    'Love di X, Love di Y')."""
    query = _strip_lead_filler(query)
    if not query:
        return ActionResult(msg("ask_query"), ok=False)
    if guard and guard.blocks(query):
        return ActionResult(msg("blocked"), ok=False)
    try:
        groups = [
            g for g in (
                _local_group(lms.local_album_candidates(query), query, "album", "play_album_id", guard),
                _local_group(lms.local_artist_candidates(query), query, "artist", "play_artist_id", guard),
                _local_group(lms.local_track_candidates(query), query, "track", "play_track_id", guard),
            ) if g
        ]
        if not groups:
            return ActionResult(msg("local_not_found", query=query), ok=False)
        groups.sort(key=lambda g: -g[0][0])  # best-scoring category wins
        winner = [cand for _s, cand in groups[0]]
        distinct = _dedup_by_title_artist(winner)
        if len(distinct) >= 2:
            return _did_you_mean(query, distinct)
        item = distinct[0]
        _dispatch_play(lms, item)
        speech = (
            msg("playing_local_album", title=item["title"])
            if item["_kind"] == "album"
            else msg("playing_local", title=item["title"])
        )
        return ActionResult(speech, ok=True, terms=[item["title"]])
    except LMSError:
        return ActionResult(msg("err_unreachable"), ok=False)


def local_albums_list(
    lms, artist: Optional[str], limit: int = LIST_LIMIT, *, guard: Optional[Guard] = None
) -> Dict:
    """Return ``{'speech', 'candidates'}`` listing a local artist's albums; each
    candidate plays that album by id when chosen."""
    artist = (artist or "").strip()
    if not artist:
        return {"speech": msg("which_artist"), "candidates": []}
    if guard and guard.blocks(artist):
        return {"speech": msg("blocked"), "candidates": []}
    try:
        result = lms.local_albums_by_artist(artist)
    except LMSError:
        return {"speech": msg("err_unreachable"), "candidates": []}
    if not result["artist"]:
        return {"speech": msg("local_no_artist", artist=artist), "candidates": []}
    albums = result["albums"]
    if guard and guard.restricted:  # drop blocked albums so they can't be chosen
        albums = [a for a in albums if not is_blocked(a.get("title"), guard.blocklist)]
    albums = albums[:limit]
    if not albums:
        return {"speech": msg("local_no_albums", artist=artist), "candidates": []}
    listing = ", ".join(
        msg("enum_item", n=i + 1, name=a["title"]) for i, a in enumerate(albums)
    )
    speech = msg("local_albums", artist=result["artist"]["title"], listing=listing)
    candidates = [
        {"title": a["title"], "action": "play_album_id", "arg": a["id"]} for a in albums
    ]
    return {"speech": speech, "candidates": candidates}


# -- voice-editable blocklist (owner only) --------------------------------
# These edit only the *dynamic* stored terms; the config KIDSAFE_BLOCKLIST
# baseline is permanent and can't be removed by voice.
def add_block(store, term: Optional[str], *, is_owner: bool) -> str:
    """Add a song/singer term to the blocklist. Owner-gated."""
    if not is_owner:
        return msg("not_owner")
    term = (term or "").strip()
    if not term:
        return msg("ask_block")
    try:
        terms = store.get()
        if any(_normalize(t) == _normalize(term) for t in terms):
            return msg("already_blocked", term=term)
        store.put(terms + [term])
    except BlocklistStoreError:
        return msg("blocklist_save_error")
    return msg("block_added", term=term)


def remove_block(store, term: Optional[str], *, is_owner: bool) -> str:
    """Remove a term from the blocklist. Owner-gated."""
    if not is_owner:
        return msg("not_owner")
    term = (term or "").strip()
    if not term:
        return msg("ask_unblock")
    try:
        terms = store.get()
        kept = [t for t in terms if _normalize(t) != _normalize(term)]
        if len(kept) == len(terms):
            return msg("not_in_blocklist", term=term)
        store.put(kept)
    except BlocklistStoreError:
        return msg("blocklist_update_error")
    return msg("block_removed", term=term)


def list_blocks(store, *, is_owner: bool) -> str:
    """Read the blocked terms aloud. Owner-gated."""
    if not is_owner:
        return msg("not_owner")
    terms = store.get()
    if not terms:
        return msg("blocklist_empty")
    return msg("blocklist_listing", terms=", ".join(terms))
