"""Pro license manager — Lemon Squeezy license keys, stdlib only.

Design goals, in order:

1. **Never brick.** ``is_pro()`` is a pure local check (cache file + env);
   the network is touched only on user-initiated activation and on an
   at-most-weekly background revalidation that downgrades **only** when
   Lemon Squeezy definitively answers ``valid: false`` (key disabled or
   refunded). Timeouts, DNS failures and 5xx change nothing: an offline
   household keeps what it paid for, forever.
2. **Honest by design.** The gate is trust-based: this module is AGPL, there
   is no obfuscation, and the docs say so. The key is how users support the
   project, not a lock to pick.

The Lemon Squeezy activate/validate endpoints need no API auth — just the
key itself — so nothing secret ships with the app.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

import appdata

API_BASE = "https://api.lemonsqueezy.com/v1/licenses"
REVALIDATE_AFTER = 7 * 24 * 3600  # seconds; at most one check per week
CACHE_FILE = "license.json"

HttpPost = Callable[[str, Dict[str, str]], Tuple[int, Dict[str, Any]]]


def _http_post(url: str, fields: Dict[str, str],
               timeout: float = 10.0) -> Tuple[int, Dict[str, Any]]:
    """Form-encoded POST returning ``(status, parsed_json)``.

    4xx bodies are parsed too (Lemon Squeezy explains errors there);
    anything unparsable raises like a network failure would.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(url, data=data,
                                 headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            except ValueError:
                pass
        raise


class LicenseManager:
    def __init__(self, data_dir: str, api_base: str = API_BASE,
                 http_post: Optional[HttpPost] = None,
                 now: Callable[[], float] = time.time,
                 environ=os.environ) -> None:
        self.path = os.path.join(data_dir, CACHE_FILE)
        self.api_base = api_base
        self.http_post = http_post or _http_post
        self.now = now
        self.environ = environ

    # -- local state (never touches the network) ----------------------------

    def _cache(self) -> Optional[Dict[str, Any]]:
        data = appdata.read_json(self.path)
        return data if isinstance(data, dict) and data.get("key") else None

    def is_pro(self) -> bool:
        if appdata.env("PRO", environ=self.environ) == "1":
            return True  # dev/test bypass, documented
        cache = self._cache()
        return bool(cache) and not cache.get("revoked")

    def status(self) -> Dict[str, Any]:
        """What the settings UI shows — the key is masked to its last 4."""
        cache = self._cache() or {}
        key = cache.get("key") or ""
        return {
            "pro": self.is_pro(),
            "key": ("****" + key[-4:]) if key else None,
            "instance": cache.get("instance_name"),
            "activated_at": cache.get("activated_at"),
            "revoked": bool(cache.get("revoked")),
        }

    # -- activation (user-initiated, requires the network once) -------------

    def activate(self, key: str) -> Dict[str, Any]:
        """Activate ``key`` against Lemon Squeezy and cache the result.

        Returns ``{"ok": True}`` or ``{"ok": False, "error": "network" |
        "invalid", "detail": ...}`` — never raises, never writes partial
        state on failure.
        """
        key = (key or "").strip()
        if not key:
            return {"ok": False, "error": "invalid", "detail": "empty key"}
        instance = socket.gethostname() or "vivavoce"
        try:
            status, body = self.http_post(
                self.api_base + "/activate",
                {"license_key": key, "instance_name": instance})
        except Exception as exc:
            return {"ok": False, "error": "network", "detail": str(exc)}
        if not body.get("activated"):
            return {"ok": False, "error": "invalid",
                    "detail": body.get("error") or f"HTTP {status}"}
        appdata.atomic_write_json(self.path, {
            "key": key,
            "instance_id": (body.get("instance") or {}).get("id"),
            "instance_name": instance,
            "activated_at": int(self.now()),
            "last_validated": int(self.now()),
            "revoked": False,
        })
        return {"ok": True}

    # -- background revalidation (best-effort, never downgrades on errors) --

    def revalidate_async(self) -> Optional[threading.Thread]:
        """Weekly opportunistic re-check, in a daemon thread at startup."""
        if appdata.env("NO_REVALIDATE", environ=self.environ) == "1":
            return None
        cache = self._cache()
        if not cache or cache.get("revoked"):
            return None
        if self.now() - (cache.get("last_validated") or 0) < REVALIDATE_AFTER:
            return None
        thread = threading.Thread(target=self._revalidate, daemon=True)
        thread.start()
        return thread

    def _revalidate(self) -> None:
        cache = self._cache()
        if not cache:
            return
        try:
            _status, body = self.http_post(
                self.api_base + "/validate",
                {"license_key": cache["key"],
                 "instance_id": cache.get("instance_id") or ""})
        except Exception:
            return  # network trouble: change nothing, retry next week
        if body.get("valid") is False:
            # The ONLY downgrade path: Lemon Squeezy said the key is dead
            # (disabled or refunded). An enabled kid-safe blocklist keeps
            # being enforced regardless — see pro/kidsafe.
            cache["revoked"] = True
            appdata.atomic_write_json(self.path, cache)
        elif body.get("valid") is True:
            cache["last_validated"] = int(self.now())
            appdata.atomic_write_json(self.path, cache)
