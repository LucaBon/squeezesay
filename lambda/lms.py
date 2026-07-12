"""Minimal Lyrion/Logitech Media Server (LMS) JSON-RPC client.

Talks to the LMS/Daphile control interface at ``<base_url>/jsonrpc.js`` using the
``slim.request`` method. The transport is injectable so the whole client can be
unit-tested without any network access (see ``tests/``).

TIDAL search & playback
------------------------
**Verified against a live LMS/Daphile with the ``michaelherger/lms-plugin-tidal``
plugin.** The plugin exposes an app feed (tag ``tidal``) browsed via the OPML
``items`` command; results come back under the ``loop_loop`` key. Searching is a
three-level navigation:

1. Home menu ``["tidal","items",0,N]`` contains a node of ``type == "search"``.
2. Enter it with ``item_id:<searchNodeId>`` + ``search:<term>`` -> category nodes
   ``Everything / Playlists / Artists / Albums / Songs`` (each with its own id).
3. Enter a category's id -> the actual items.

Item shapes (confirmed live):

* Song  -> ``{"type":"audio","isaudio":1,"url":"tidal://55391466.flc", ...}``  (play the url)
* Album/Playlist -> ``{"type":"playlist","isaudio":1,"hasitems":1, ...}`` (no url;
  play via ``["tidal","playlist","play","item_id:<id>"]``)
* Artist -> ``{"type":"outline","hasitems":1, ...}`` (browsable; played the same way)

Category names are matched in English as returned by the plugin; adjust if your
LMS UI language changes them.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

# A transport takes the JSON-RPC ``params`` (``[player_id, [cmd, ...]]``) and
# returns the parsed ``result`` object from the LMS response.
Transport = Callable[[list], Dict[str, Any]]

# TIDAL URIs seen live: ``tidal://55391466.flc`` (a track) and the entity forms
# ``tidal://album:ID`` / ``artist:`` / ``playlist:`` / ``mix:`` (also legacy ``wimp://``).
_TIDAL_URI = re.compile(
    r"(?:tidal|wimp)://(?:(?:track|album|artist|playlist|mix):[^\s\"']+|\d+\.[A-Za-z0-9]+)",
    re.IGNORECASE,
)


class LMSError(Exception):
    """Raised when the LMS server cannot be reached or returns garbage."""


def find_tidal_uri(obj: Any) -> Optional[str]:
    """Recursively search a (possibly nested) OPML item for the first TIDAL URI."""
    if isinstance(obj, str):
        match = _TIDAL_URI.search(obj)
        return match.group(0) if match else None
    if isinstance(obj, dict):
        for value in obj.values():
            uri = find_tidal_uri(value)
            if uri:
                return uri
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            uri = find_tidal_uri(value)
            if uri:
                return uri
    return None


def _split_text(text: Any) -> tuple:
    """Split a menu item's ``text`` ('Title\\nArtist') into (title, artist)."""
    if not text:
        return None, None
    lines = [p.strip() for p in str(text).split("\n") if p.strip()]
    if len(lines) >= 2:
        return lines[0], lines[1]
    return (lines[0] if lines else None), None


def uri_kind(uri: str) -> Optional[str]:
    """Classify a TIDAL URI as track/album/artist/playlist/mix."""
    match = re.match(
        r"(?:tidal|wimp)://(track|album|artist|playlist|mix):", uri, re.IGNORECASE
    )
    if match:
        return match.group(1).lower()
    if re.match(r"(?:tidal|wimp)://\d+\.[A-Za-z0-9]+$", uri, re.IGNORECASE):
        return "track"
    return None


class LMSClient:
    def __init__(
        self,
        base_url: str,
        player_id: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 8.0,
        transport: Optional[Transport] = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not player_id:
            raise ValueError("player_id is required")
        self.base_url = base_url.rstrip("/")
        self.player_id = player_id
        self.username = username
        self.password = password
        self.timeout = timeout
        self._transport: Transport = transport or self._http_transport

    # -- low level ---------------------------------------------------------
    def _rpc(self, player: str, cmd: List[Any]) -> Dict[str, Any]:
        result = self._transport([player, [str(c) for c in cmd]])
        if not isinstance(result, dict):
            raise LMSError(f"Unexpected LMS result type: {type(result)!r}")
        return result

    def command(self, *cmd: Any) -> Dict[str, Any]:
        """Run a command scoped to the configured player."""
        return self._rpc(self.player_id, list(cmd))

    def server_command(self, *cmd: Any) -> Dict[str, Any]:
        """Run a server-wide command (player id ``-``)."""
        return self._rpc("-", list(cmd))

    def _http_transport(self, params: list) -> Dict[str, Any]:
        import base64
        import json
        import urllib.error
        import urllib.request

        payload = json.dumps(
            {"id": 1, "method": "slim.request", "params": params}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/jsonrpc.js",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        if self.username:
            token = base64.b64encode(
                f"{self.username}:{self.password or ''}".encode("utf-8")
            ).decode("ascii")
            req.add_header("Authorization", "Basic " + token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise LMSError(f"LMS request failed: {exc}") from exc
        if not isinstance(body, dict) or "result" not in body:
            raise LMSError(f"Unexpected LMS response: {body!r}")
        return body["result"]

    # -- players -----------------------------------------------------------
    def get_players(self) -> List[Dict[str, Any]]:
        res = self.server_command("players", "0", "100")
        return res.get("players_loop", []) or []

    # -- TIDAL browse/search ----------------------------------------------
    def _tidal_items(self, *params: Any) -> List[Dict[str, Any]]:
        res = self.command("tidal", "items", *params)
        return res.get("loop_loop") or res.get("item_loop") or []

    def tidal_search_node_id(self) -> Optional[str]:
        """Id of the plugin's 'Search' node (type == 'search') in the home menu."""
        for item in self._tidal_items("0", "50"):
            if item.get("type") == "search":
                return item.get("id")
        return None

    def tidal_search_categories(self, query: str, count: int = 30) -> Dict[str, str]:
        """Map of category name -> node id for a query (Songs, Artists, ...)."""
        node = self.tidal_search_node_id()
        if node is None:
            return {}
        items = self._tidal_items(
            "0", str(count), f"item_id:{node}", f"search:{query}"
        )
        return {it["name"]: it["id"] for it in items if it.get("name") and it.get("id")}

    # Canonical category -> accepted names as the plugin may localize them. We
    # match by name (case-insensitive) trying each alias, so search keeps working
    # if the LMS UI language is switched (English default + common Italian forms).
    CATEGORY_ALIASES = {
        "Songs": ("Songs", "Brani", "Canzoni", "Tracce"),
        "Albums": ("Albums", "Album"),
        "Artists": ("Artists", "Artisti"),
        "Playlists": ("Playlists", "Playlist"),
    }

    def _resolve_category(self, cats: Dict[str, str], canonical: str) -> Optional[str]:
        wanted = self.CATEGORY_ALIASES.get(canonical, (canonical,))
        norm = {name.strip().lower(): cid for name, cid in cats.items()}
        for alias in wanted:
            cid = norm.get(alias.strip().lower())
            if cid:
                return cid
        return None

    def tidal_category_items(
        self, query: str, category: str, count: int = 20
    ) -> List[Dict[str, Any]]:
        cats = self.tidal_search_categories(query, count)
        node_id = self._resolve_category(cats, category)
        if not node_id:
            return []
        return self._tidal_items("0", str(count), f"item_id:{node_id}", "want_url:1")

    def search_tracks(self, query: str, count: int = 20) -> List[Dict[str, Any]]:
        """Return playable tracks ``[{'url', 'title'[, 'artist']}, ...]`` for a query.

        Uses the Songs category in **menu mode** (``menu:1``): each item carries the
        artist as the 2nd line of ``text`` ('Title\\nArtist') and the play URL under
        ``presetParams.favorites_url`` — the plain ``want_url`` mode strips both to a
        bare title. Falls back to ``name``/``url``/``artist`` keys so the simulated
        transport in tests still works."""
        cats = self.tidal_search_categories(query, count)
        node = self._resolve_category(cats, "Songs")
        if not node:
            return []
        out: List[Dict[str, Any]] = []
        for item in self._tidal_items("0", str(count), f"item_id:{node}", "menu:1"):
            if item.get("isaudio") == 0:
                continue
            preset = item.get("presetParams") or {}
            url = item.get("url") or preset.get("favorites_url") or find_tidal_uri(item)
            if not url:
                continue
            title, artist = _split_text(item.get("text"))
            title = title or item.get("name")
            artist = artist or item.get("artist")
            track = {"url": url, "title": title}
            if artist:
                track["artist"] = artist
            out.append(track)
        return out

    def playlist_candidates(self, query: str, count: int = 20) -> List[Dict[str, Any]]:
        return [
            {"id": it["id"], "title": it.get("name")}
            for it in self.tidal_category_items(query, "Playlists", count)
            if it.get("id")
        ]

    def find_playlist(self, query: str, count: int = 20) -> Optional[Dict[str, Any]]:
        cands = self.playlist_candidates(query, count)
        return cands[0] if cands else None

    def album_candidates(self, query: str, count: int = 20) -> List[Dict[str, Any]]:
        """All album matches for a query, in TIDAL relevance order. The caller
        scores these against the request (edition words like 'Live In Berlin'
        surface the right edition)."""
        return [
            {"id": it["id"], "title": it.get("name")}
            for it in self.tidal_category_items(query, "Albums", count)
            if it.get("id")
        ]

    def find_album(self, query: str, count: int = 20) -> Optional[Dict[str, Any]]:
        cands = self.album_candidates(query, count)
        return cands[0] if cands else None

    def album_tracks(self, query: str, count: int = 50) -> Dict[str, Any]:
        """Return ``{'album': {...} | None, 'tracks': [{'url','title'}, ...]}``."""
        album = self.find_album(query, count)
        if not album:
            return {"album": None, "tracks": []}
        tracks: List[Dict[str, Any]] = []
        for item in self._tidal_items(
            "0", str(count), f"item_id:{album['id']}", "want_url:1"
        ):
            url = item.get("url") or find_tidal_uri(item)
            if item.get("isaudio") and url:
                tracks.append({"url": url, "title": item.get("name")})
        return {"album": album, "tracks": tracks}

    def find_artist(self, query: str, count: int = 20) -> Optional[Dict[str, Any]]:
        for item in self.tidal_category_items(query, "Artists", count):
            if item.get("id"):
                return {"id": item["id"], "title": item.get("name")}
        return None

    # Artist "outline" nodes are NOT directly playable (verified live: playing
    # them is a no-op). Their music lives in child nodes; we drill the first
    # available of these to a list of playable track URLs.
    ARTIST_PLAYABLE_CHILDREN = ("Top Tracks", "Artist Mix")

    def artist_top_tracks(
        self, query: str, count: int = 20
    ) -> Dict[str, Any]:
        """Return ``{'artist': {...} | None, 'tracks': [{'url','title'}, ...]}``."""
        artist = self.find_artist(query, count)
        if not artist:
            return {"artist": None, "tracks": []}
        children = self._tidal_items(
            "0", str(count), f"item_id:{artist['id']}", "want_url:1"
        )
        by_name = {c["name"]: c["id"] for c in children if c.get("name") and c.get("id")}
        tracks: List[Dict[str, Any]] = []
        for child_name in self.ARTIST_PLAYABLE_CHILDREN:
            node_id = by_name.get(child_name)
            if not node_id:
                continue
            for item in self._tidal_items(
                "0", str(count), f"item_id:{node_id}", "want_url:1"
            ):
                url = item.get("url") or find_tidal_uri(item)
                if item.get("isaudio") and url:
                    tracks.append({"url": url, "title": item.get("name")})
            if tracks:
                break
        return {"artist": artist, "tracks": tracks}

    # -- local library (Music Folder / USB drive) -------------------------
    # Uses LMS core commands with stable numeric ids (verified live), so local
    # playback is fully deterministic — unlike the TIDAL app-feed navigation.
    # LMS ``search:`` is a loose keyword search across fields; it can return
    # loosely-related rows. So we return all candidates and let the caller score
    # them against the query (title + artist) instead of trusting the first row.
    def local_artist_candidates(self, query: str, count: int = 10) -> List[Dict[str, Any]]:
        loop = self.server_command(
            "artists", "0", str(count), f"search:{query}"
        ).get("artists_loop") or []
        return [{"id": a["id"], "title": a.get("artist")} for a in loop if a.get("id") is not None]

    def find_local_artist(self, query: str, count: int = 10) -> Optional[Dict[str, Any]]:
        cands = self.local_artist_candidates(query, count)
        return cands[0] if cands else None

    def local_album_candidates(self, query: str, count: int = 10) -> List[Dict[str, Any]]:
        loop = self.server_command(
            "albums", "0", str(count), f"search:{query}", "tags:la"
        ).get("albums_loop") or []
        return [
            {"id": a["id"], "title": a.get("album"), "artist": a.get("artist")}
            for a in loop if a.get("id") is not None
        ]

    def find_local_album(self, query: str, count: int = 10) -> Optional[Dict[str, Any]]:
        cands = self.local_album_candidates(query, count)
        return cands[0] if cands else None

    def local_track_candidates(self, query: str, count: int = 10) -> List[Dict[str, Any]]:
        loop = self.server_command(
            "titles", "0", str(count), f"search:{query}", "tags:a"
        ).get("titles_loop") or []
        out: List[Dict[str, Any]] = []
        for a in loop:
            if a.get("id") is None:
                continue
            cand = {"id": a["id"], "title": a.get("title")}
            if a.get("artist"):
                cand["artist"] = a["artist"]
            out.append(cand)
        return out

    def find_local_track(self, query: str, count: int = 10) -> Optional[Dict[str, Any]]:
        cands = self.local_track_candidates(query, count)
        return cands[0] if cands else None

    def local_albums_by_artist(self, query: str, count: int = 50) -> Dict[str, Any]:
        artist = self.find_local_artist(query)
        if not artist:
            return {"artist": None, "albums": []}
        loop = self.server_command(
            "albums", "0", str(count), f"artist_id:{artist['id']}", "tags:la"
        ).get("albums_loop") or []
        albums = [{"id": a["id"], "title": a.get("album")} for a in loop if a.get("id")]
        return {"artist": artist, "albums": albums}

    def play_local_artist(self, artist_id: Any) -> Dict[str, Any]:
        return self.command("playlistcontrol", "cmd:load", f"artist_id:{artist_id}")

    def play_local_album(self, album_id: Any) -> Dict[str, Any]:
        return self.command("playlistcontrol", "cmd:load", f"album_id:{album_id}")

    def play_local_track(self, track_id: Any) -> Dict[str, Any]:
        return self.command("playlistcontrol", "cmd:load", f"track_id:{track_id}")

    def now_playing_info(self) -> Optional[Dict[str, Any]]:
        res = self.command("status", "-", "1", "tags:aAlN")
        loop = res.get("playlist_loop") or []
        if not loop:
            return None
        item = loop[0]
        return {"title": item.get("title"), "artist": item.get("artist")}

    # -- playback / controls ----------------------------------------------
    def play_url(self, url: str) -> Dict[str, Any]:
        """Play a direct URL (e.g. a track ``tidal://<id>.flc``) on the player."""
        return self.command("playlist", "play", url)

    def play_browse_item(self, item_id: str) -> Dict[str, Any]:
        """Play a browseable TIDAL node (album/playlist) by its OPML id."""
        return self.command("tidal", "playlist", "play", f"item_id:{item_id}")

    def add_url(self, url: str) -> Dict[str, Any]:
        return self.command("playlist", "add", url)

    def play_tracks(self, urls: List[str]) -> None:
        """Play the first URL (replacing the queue) then enqueue the rest."""
        if not urls:
            return
        self.play_url(urls[0])
        for url in urls[1:]:
            self.add_url(url)

    def pause(self) -> Dict[str, Any]:
        return self.command("pause", "1")

    def resume(self) -> Dict[str, Any]:
        return self.command("pause", "0")

    def next_track(self) -> Dict[str, Any]:
        return self.command("playlist", "index", "+1")

    def previous_track(self) -> Dict[str, Any]:
        return self.command("playlist", "index", "-1")

    def volume(self, delta: int) -> Dict[str, Any]:
        sign = "+" if delta >= 0 else "-"
        return self.command("mixer", "volume", f"{sign}{abs(int(delta))}")
