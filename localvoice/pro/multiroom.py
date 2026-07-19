# Copyright (c) 2026 Luca Bonura. Proprietary — see licenses/PRO-EULA.md.
# Not covered by the repository's AGPL-3.0 license.
"""Multi-room targeting (Pro): command any player in the house.

The AGPL core stays policy-free: ``LMSClient.for_player()`` is a generic
mechanism, and the router/server accept an *injected* multiroom object with a
narrow contract (``pro_ok`` / ``players`` / ``extract_room``) — like kid-safe.
This module owns the feature: the license gate, the cached player list, and
the room-phrase understanding («metti Time in cucina», "play X in the
kitchen") with the fuzzy matching that survives ASR spelling («salotto» for a
player named «Salotto Hi-Fi»).

Room extraction is deliberately conservative: a phrase is only treated as a
room when its «in <words>» tail (or head) actually names a player, so
"Breakfast in America" stays a song title.
"""

from __future__ import annotations

import difflib
import time
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

# Room matching consults the player list on every command: cache it a few
# seconds so a command costs one LMS round-trip, not two.
CACHE_TTL = 5.0

# Prepositions that may introduce a room. "su" is left out of the Italian set:
# it introduces services («su tidal»), not rooms.
_PREPS = {
    "it": ("in", "nella", "nel", "sulla", "sul"),
    "en": ("in", "on"),
}
_ARTICLES = ("the ", "la ", "il ", "lo ", "l'", "le ", "gli ")


def _fold(text: Optional[str]) -> str:
    """Lowercase + accent-fold («salòtto» == «salotto»)."""
    t = unicodedata.normalize("NFD", (text or "").strip().lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _match_player(room: str, players: List[Dict[str, Any]]) -> Optional[Dict]:
    """The player whose name best matches a spoken room, or None. Fuzzy on
    purpose: ASR writes «salotto» for a player named «Salotto Hi-Fi»."""
    room_f = _fold(room)
    for article in _ARTICLES:
        if room_f.startswith(article):
            room_f = room_f[len(article):].strip()
            break
    if not room_f:
        return None
    best, best_score = None, 0.0
    for player in players:
        name_f = _fold(player.get("name"))
        if not name_f or not player.get("playerid"):
            continue
        score = difflib.SequenceMatcher(None, room_f, name_f).ratio()
        if len(room_f) >= 3 and (name_f.startswith(room_f) or room_f == name_f):
            score = max(score, 0.96)
        if score > best_score:
            best, best_score = player, score
    return best if best_score >= 0.75 else None


class MultiRoom:
    """The multi-room feature behind the router and the web endpoints.

    ``license_mgr`` may be None (no license infrastructure: everything stays
    gated off). ``get_players`` is the LMS query, injected so the server and
    the tests decide where players come from.
    """

    def __init__(self, license_mgr, get_players: Callable[[], list],
                 cache_ttl: float = CACHE_TTL) -> None:
        self.license = license_mgr
        self.get_players = get_players
        self.cache_ttl = cache_ttl
        self._cache: List[Dict[str, Any]] = []
        self._cached_at = 0.0

    def pro_ok(self) -> bool:
        return self.license is not None and self.license.is_pro()

    def players(self) -> List[Dict[str, Any]]:
        """The player list, cached for a few seconds. Raises like the LMS
        query on failure (the /players endpoint reports it; the voice path
        uses :meth:`_players_safe` instead)."""
        now = time.monotonic()
        if now - self._cached_at > self.cache_ttl:
            self._cache = self.get_players() or []
            self._cached_at = now
        return self._cache

    def _players_safe(self) -> List[Dict[str, Any]]:
        try:
            return self.players()
        except Exception:
            return []

    def extract_room(self, text: str, lang: str) -> Tuple[str, Optional[Dict]]:
        """``(text_without_room, player)`` when the phrase carries an
        «in <room>» that names a real player; ``(text, None)`` otherwise."""
        players = self._players_safe()
        if not players:
            return text, None
        preps = _PREPS.get(lang) or _PREPS["it"]
        words = text.split()
        # Suffix: «metti X in cucina» (room = the last 1-3 words).
        for n in (3, 2, 1):
            if len(words) >= n + 2 and words[-(n + 1)].lower() in preps:
                player = _match_player(" ".join(words[-n:]), players)
                if player:
                    return " ".join(words[:-(n + 1)]).rstrip(" ,"), player
        # Prefix: «in cucina metti X».
        if len(words) >= 3 and words[0].lower() in preps:
            for n in (3, 2, 1):
                if len(words) >= n + 2:
                    player = _match_player(" ".join(words[1:1 + n]), players)
                    if player:
                        return " ".join(words[1 + n:]), player
        return text, None
