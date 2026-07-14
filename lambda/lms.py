"""Minimal Lyrion/Logitech Media Server (LMS) JSON-RPC client.

Talks to the LMS/Daphile control interface at ``<base_url>/jsonrpc.js`` using the
``slim.request`` method. The transport is injectable so the whole client can be
unit-tested without any network access (see ``tests/``).

Streaming search & playback (app feeds)
---------------------------------------
Streaming plugins (TIDAL, Qobuz) expose an LMS *app feed* — an OPML tree browsed
via the ``items`` command; results come back under the ``loop_loop`` key. Which
feed a client instance talks to is set by its ``ServiceSpec`` (see ``SERVICES``).
Searching is a three-level navigation:

1. Home menu ``["<tag>","items",0,N]`` contains a node of ``type == "search"``.
2. Enter it with ``item_id:<searchNodeId>`` + ``search:<term>`` -> category nodes
   ``Everything / Playlists / Artists / Albums / Songs`` (each with its own id).
3. Enter a category's id -> the actual items.

Item shapes (confirmed live for TIDAL, tag ``tidal``, plugin
``michaelherger/lms-plugin-tidal``):

* Song  -> ``{"type":"audio","isaudio":1,"url":"tidal://55391466.flc", ...}``  (play the url)
* Album/Playlist -> ``{"type":"playlist","isaudio":1,"hasitems":1, ...}`` (no url;
  play via ``["<tag>","playlist","play","item_id:<id>"]``)
* Artist -> ``{"type":"outline","hasitems":1, ...}`` (browsable; played the same way)

Qobuz (tag ``qobuz``, plugin ``LMS-Community/plugin-Qobuz`` 3.7.0) follows the
same pattern and is verified live too (2026-07-14); its quirks — nested search
node, "Releases" category, " (Hi-Res)" title tag, "Artist - Album" text line —
are captured in ``SERVICES["qobuz"]``.

Category names are matched against the per-service alias tables; adjust if your
LMS UI language changes them.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# A transport takes the JSON-RPC ``params`` (``[player_id, [cmd, ...]]``) and
# returns the parsed ``result`` object from the LMS response.
Transport = Callable[[list], Dict[str, Any]]


def _uri_re(schemes: Tuple[str, ...]) -> "re.Pattern":
    """URI regex for a service's scheme(s): entity forms (``album:ID`` etc.) or
    the bare-track form ``<digits>.<ext>`` (e.g. ``tidal://55391466.flc``)."""
    alt = "|".join(re.escape(s) for s in schemes)
    return re.compile(
        rf"(?:{alt})://(?:(?:track|album|artist|playlist|mix):[^\s\"']+|\d+\.[A-Za-z0-9]+)",
        re.IGNORECASE,
    )


@dataclass(frozen=True)
class ServiceSpec:
    """Everything service-specific about an LMS streaming app feed."""

    name: str                    # registry key: "tidal" / "qobuz"
    tag: str                     # CLI tag: cmd[0] of ["<tag>","items",...]
    schemes: Tuple[str, ...]     # URL scheme(s) the plugin's tracks use
    category_aliases: Dict[str, tuple]  # canonical -> names the plugin may show
    artist_children: Tuple[str, ...]    # playable child nodes under an artist
    # Some plugins (Qobuz) nest the search node one level down: home shows a
    # plain "Search" link whose CHILD is the ``type == "search"`` node. These
    # are the (lowercased) home-menu names worth entering to look for it.
    search_parents: Tuple[str, ...] = ()
    # Display noise the plugin appends to track titles (e.g. Qobuz's
    # " (Hi-Res)" quality tag and " [E]" parental marker), stripped before
    # scoring/confirmation so «Comfortably Numb» matches exactly.
    title_noise_re: Any = None
    # When the menu-mode text's 2nd line is "Artist<sep>Album" (Qobuz) rather
    # than just the artist (TIDAL), split on this to keep the artist part.
    artist_line_sep: Optional[str] = None
    uri_re: Any = field(init=False, default=None, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "uri_re", _uri_re(self.schemes))


SERVICES: Dict[str, ServiceSpec] = {
    # Verified against a live LMS/Daphile (see module docstring).
    "tidal": ServiceSpec(
        name="tidal",
        tag="tidal",
        schemes=("tidal", "wimp"),  # wimp:// is the legacy TIDAL scheme
        category_aliases={
            "Songs": ("Songs", "Brani", "Canzoni", "Tracce"),
            "Albums": ("Albums", "Album"),
            "Artists": ("Artists", "Artisti"),
            "Playlists": ("Playlists", "Playlist"),
        },
        artist_children=("Top Tracks", "Artist Mix"),
    ),
    # Verified live against LMS 9.0.3 + plugin-Qobuz 3.7.0 (2026-07-14):
    # categories come back as Releases/Artists/Songs/Playlists, the search
    # node is nested under a "Search" link, tracks are ``qobuz://<id>.flac``,
    # titles carry " (Hi-Res)" and the artist line is "Artist - Album".
    "qobuz": ServiceSpec(
        name="qobuz",
        tag="qobuz",
        schemes=("qobuz",),
        category_aliases={
            "Songs": ("Songs", "Tracks", "Brani", "Canzoni", "Tracce"),
            "Albums": ("Releases", "Albums", "Album"),
            "Artists": ("Artists", "Artisti"),
            "Playlists": ("Playlists", "Playlist"),
        },
        artist_children=("Songs", "Top Tracks"),
        search_parents=("search", "cerca", "ricerca"),
        title_noise_re=re.compile(r"(?:\s*\(Hi-Res\)|\s*\[E\])+\s*$", re.IGNORECASE),
        artist_line_sep=" - ",
    ),
}

# All registered schemes, for service-independent URI classification.
_ANY_SCHEME = "|".join(
    re.escape(s) for spec in SERVICES.values() for s in spec.schemes
)

# Backward-compatible alias (the TIDAL-only regex predates ServiceSpec).
_TIDAL_URI = SERVICES["tidal"].uri_re


class LMSError(Exception):
    """Raised when the LMS server cannot be reached or returns garbage."""


def find_uri(obj: Any, pattern: "re.Pattern") -> Optional[str]:
    """Recursively search a (possibly nested) OPML item for the first URI
    matching ``pattern``."""
    if isinstance(obj, str):
        match = pattern.search(obj)
        return match.group(0) if match else None
    if isinstance(obj, dict):
        for value in obj.values():
            uri = find_uri(value, pattern)
            if uri:
                return uri
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            uri = find_uri(value, pattern)
            if uri:
                return uri
    return None


def find_tidal_uri(obj: Any) -> Optional[str]:
    """Recursively search a (possibly nested) OPML item for the first TIDAL URI."""
    return find_uri(obj, _TIDAL_URI)


def _split_text(text: Any) -> tuple:
    """Split a menu item's ``text`` ('Title\\nArtist') into (title, artist)."""
    if not text:
        return None, None
    lines = [p.strip() for p in str(text).split("\n") if p.strip()]
    if len(lines) >= 2:
        return lines[0], lines[1]
    return (lines[0] if lines else None), None


def uri_kind(uri: str) -> Optional[str]:
    """Classify a streaming URI (any registered service) as
    track/album/artist/playlist/mix."""
    match = re.match(
        rf"(?:{_ANY_SCHEME})://(track|album|artist|playlist|mix):", uri, re.IGNORECASE
    )
    if match:
        return match.group(1).lower()
    if re.match(rf"(?:{_ANY_SCHEME})://\d+\.[A-Za-z0-9]+$", uri, re.IGNORECASE):
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
        service: str = "tidal",
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not player_id:
            raise ValueError("player_id is required")
        if service not in SERVICES:
            raise ValueError(
                f"unknown service {service!r} (available: {', '.join(SERVICES)})"
            )
        self.base_url = base_url.rstrip("/")
        self.player_id = player_id
        self.username = username
        self.password = password
        self.timeout = timeout
        self.service = SERVICES[service]
        self._transport: Transport = transport or self._http_transport

    def for_service(self, name: str) -> "LMSClient":
        """This client re-targeted at another streaming service. Returns a
        shallow copy sharing transport/base_url/player, so one configured
        client can serve every registered service."""
        spec = SERVICES.get(name)
        if spec is None:
            raise ValueError(
                f"unknown service {name!r} (available: {', '.join(SERVICES)})"
            )
        if spec is self.service:
            return self
        clone = copy.copy(self)
        clone.service = spec
        return clone

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

    def installed_services(self) -> List[str]:
        """Registered services whose plugin shows up in the player's LMS apps
        menu. The loop key is read in both spellings LMS has used."""
        res = self.command("apps", "0", "100")
        loop = res.get("appss_loop") or res.get("apps_loop") or []
        tags = {a.get("cmd") for a in loop if a.get("cmd")}
        return [name for name, spec in SERVICES.items() if spec.tag in tags]

    # -- streaming app-feed browse/search (TIDAL, Qobuz, ...) --------------
    def _app_items(self, *params: Any) -> List[Dict[str, Any]]:
        res = self.command(self.service.tag, "items", *params)
        return res.get("loop_loop") or res.get("item_loop") or []

    def search_node_id(self) -> Optional[str]:
        """Id of the plugin's search node (type == 'search').

        TIDAL exposes it right in the home menu; Qobuz nests it one level
        down (home 'Search' link -> 'New search'), so when the home menu has
        none we enter the ``search_parents`` nodes and look again."""
        items = self._app_items("0", "50")
        for item in items:
            if item.get("type") == "search":
                return item.get("id")
        for item in items:
            name = (item.get("name") or "").strip().lower()
            if item.get("id") and item.get("hasitems") and name in self.service.search_parents:
                for child in self._app_items("0", "50", f"item_id:{item['id']}"):
                    if child.get("type") == "search":
                        return child.get("id")
        return None

    def search_categories(self, query: str, count: int = 30) -> Dict[str, str]:
        """Map of category name -> node id for a query (Songs, Artists, ...)."""
        node = self.search_node_id()
        if node is None:
            return {}
        items = self._app_items(
            "0", str(count), f"item_id:{node}", f"search:{query}"
        )
        return {it["name"]: it["id"] for it in items if it.get("name") and it.get("id")}

    # Canonical category -> accepted names as the plugin may localize them
    # (per-service table). We match by name (case-insensitive) trying each
    # alias, so search keeps working if the LMS UI language is switched.
    def _resolve_category(self, cats: Dict[str, str], canonical: str) -> Optional[str]:
        wanted = self.service.category_aliases.get(canonical, (canonical,))
        norm = {name.strip().lower(): cid for name, cid in cats.items()}
        for alias in wanted:
            cid = norm.get(alias.strip().lower())
            if cid:
                return cid
        return None

    def category_items(
        self, query: str, category: str, count: int = 20
    ) -> List[Dict[str, Any]]:
        cats = self.search_categories(query, count)
        node_id = self._resolve_category(cats, category)
        if not node_id:
            return []
        return self._app_items("0", str(count), f"item_id:{node_id}", "want_url:1")

    def search_tracks(self, query: str, count: int = 20) -> List[Dict[str, Any]]:
        """Return playable tracks ``[{'url', 'title'[, 'artist']}, ...]`` for a query.

        Uses the Songs category in **menu mode** (``menu:1``): each item carries the
        artist as the 2nd line of ``text`` ('Title\\nArtist') and the play URL under
        ``presetParams.favorites_url`` — the plain ``want_url`` mode strips both to a
        bare title. Falls back to ``name``/``url``/``artist`` keys so the simulated
        transport in tests still works."""
        cats = self.search_categories(query, count)
        node = self._resolve_category(cats, "Songs")
        if not node:
            return []
        out: List[Dict[str, Any]] = []
        for item in self._app_items("0", str(count), f"item_id:{node}", "menu:1"):
            if item.get("isaudio") == 0:
                continue
            preset = item.get("presetParams") or {}
            url = item.get("url") or preset.get("favorites_url") or find_uri(item, self.service.uri_re)
            if not url:
                continue
            title, artist = _split_text(item.get("text"))
            title = title or item.get("name")
            artist = artist or item.get("artist")
            if title and self.service.title_noise_re is not None:
                title = self.service.title_noise_re.sub("", title).strip() or title
            if artist and self.service.artist_line_sep:
                # e.g. Qobuz: "Pink Floyd - The Wall (Remastered)" -> "Pink Floyd"
                artist = artist.split(self.service.artist_line_sep, 1)[0].strip() or artist
            track = {"url": url, "title": title}
            if artist:
                track["artist"] = artist
            out.append(track)
        return out

    def playlist_candidates(self, query: str, count: int = 20) -> List[Dict[str, Any]]:
        return [
            {"id": it["id"], "title": it.get("name")}
            for it in self.category_items(query, "Playlists", count)
            if it.get("id")
        ]

    def find_playlist(self, query: str, count: int = 20) -> Optional[Dict[str, Any]]:
        cands = self.playlist_candidates(query, count)
        return cands[0] if cands else None

    def album_candidates(self, query: str, count: int = 20) -> List[Dict[str, Any]]:
        """All album matches for a query, in the service's relevance order. The
        caller scores these against the request (edition words like 'Live In
        Berlin' surface the right edition)."""
        return [
            {"id": it["id"], "title": it.get("name")}
            for it in self.category_items(query, "Albums", count)
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
        for item in self._app_items(
            "0", str(count), f"item_id:{album['id']}", "want_url:1"
        ):
            url = item.get("url") or find_uri(item, self.service.uri_re)
            if item.get("isaudio") and url:
                tracks.append({"url": url, "title": item.get("name")})
        return {"album": album, "tracks": tracks}

    def find_artist(self, query: str, count: int = 20) -> Optional[Dict[str, Any]]:
        for item in self.category_items(query, "Artists", count):
            if item.get("id"):
                return {"id": item["id"], "title": item.get("name")}
        return None

    # Artist "outline" nodes are NOT directly playable (verified live on TIDAL:
    # playing them is a no-op). Their music lives in child nodes; we drill the
    # first available of the service's ``artist_children`` to playable URLs.
    def artist_top_tracks(
        self, query: str, count: int = 20
    ) -> Dict[str, Any]:
        """Return ``{'artist': {...} | None, 'tracks': [{'url','title'}, ...]}``."""
        artist = self.find_artist(query, count)
        if not artist:
            return {"artist": None, "tracks": []}
        children = self._app_items(
            "0", str(count), f"item_id:{artist['id']}", "want_url:1"
        )
        by_name = {c["name"]: c["id"] for c in children if c.get("name") and c.get("id")}
        tracks: List[Dict[str, Any]] = []
        for child_name in self.service.artist_children:
            node_id = by_name.get(child_name)
            if not node_id:
                continue
            for item in self._app_items(
                "0", str(count), f"item_id:{node_id}", "want_url:1"
            ):
                url = item.get("url") or find_uri(item, self.service.uri_re)
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
        """Play a browseable app-feed node (album/playlist) by its OPML id."""
        return self.command(self.service.tag, "playlist", "play", f"item_id:{item_id}")

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
