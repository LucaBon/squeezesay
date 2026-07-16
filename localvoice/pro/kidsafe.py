# Copyright (c) 2026 Luca Bonura. Proprietary — see licenses/PRO-EULA.md.
# Not covered by the repository's AGPL-3.0 license.
"""Kid-safe mode for the web app: a PIN-protected, voice-editable blocklist.

The blocklist engine (matching, Guard, add/remove actions) lives in the AGPL
core; this module owns the *web* integration: the PIN, the per-client unlock
window, and the fail-safe policy.

Fail-safe by design: enforcement never turns itself off. If the Pro license
is later revoked (refund), an **enabled** blocklist keeps filtering — a
refund must never silently disable child protection — but configuration
changes are locked until a valid key is back.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from typing import Any, Dict, Optional

import actions
import appdata
from blocklist_store import JsonBlocklistStore

STATE_FILE = "kidsafe.json"
UNLOCK_SECONDS = 15 * 60
PBKDF2_ITERATIONS = 200_000
# Un bambino che prova PIN a raffica sulla LAN: dopo MAX_ATTEMPTS sbagliati
# il client aspetta LOCKOUT_SECONDS prima di poter riprovare.
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60


def _hash_pin(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt, PBKDF2_ITERATIONS).hex()


class KidSafe:
    def __init__(self, data_dir: str, license_mgr=None,
                 now=time.time) -> None:
        self.path = os.path.join(data_dir, STATE_FILE)
        self.store = JsonBlocklistStore(self.path)
        self.license = license_mgr
        self.now = now
        self._unlocked: Dict[str, float] = {}   # client_id -> unlocked_until
        self._failures: Dict[str, list] = {}    # client_id -> [count, retry_at]

    # -- state ---------------------------------------------------------------

    def _state(self) -> dict:
        return appdata.read_json(self.path, {}) or {}

    def enabled(self) -> bool:
        return bool(self._state().get("enabled"))

    def has_pin(self) -> bool:
        return bool(self._state().get("pin"))

    def pro_ok(self) -> bool:
        return bool(self.license and self.license.is_pro())

    def terms(self) -> list:
        return self.store.get()

    # -- PIN -------------------------------------------------------------------

    def _save(self, **changes: Any) -> None:
        state = self._state()
        state.update(changes)
        appdata.atomic_write_json(self.path, state)

    def _set_pin(self, pin: str) -> None:
        salt = secrets.token_bytes(16)
        self._save(pin={"salt": salt.hex(), "hash": _hash_pin(pin, salt),
                        "iterations": PBKDF2_ITERATIONS})

    def verify_pin(self, pin: str, client_id: str) -> bool:
        """Constant-ish check with a per-client lockout after repeated misses."""
        count, retry_at = self._failures.get(client_id, [0, 0])
        if count >= MAX_ATTEMPTS and self.now() < retry_at:
            return False
        stored = self._state().get("pin") or {}
        try:
            expected = stored["hash"]
            salt = bytes.fromhex(stored["salt"])
        except (KeyError, ValueError):
            return False
        ok = secrets.compare_digest(_hash_pin(pin or "", salt), expected)
        if ok:
            self._failures.pop(client_id, None)
        else:
            self._failures[client_id] = [count + 1,
                                         self.now() + LOCKOUT_SECONDS]
        return ok

    # -- unlock window ---------------------------------------------------------

    def is_unlocked(self, client_id: str) -> bool:
        return self.now() < self._unlocked.get(client_id, 0)

    def unlock(self, client_id: str, pin: str) -> bool:
        if not self.verify_pin(pin, client_id):
            return False
        self._unlocked[client_id] = self.now() + UNLOCK_SECONDS
        return True

    def lock(self, client_id: str) -> None:
        self._unlocked.pop(client_id, None)

    # -- configuration (Pro-gated; enforcement below is not) -------------------

    def enable(self, pin: str, client_id: str) -> Dict[str, Any]:
        """Turn enforcement on. First run sets the PIN; later runs require it."""
        if not self.pro_ok():
            return {"ok": False, "error": "pro_required"}
        pin = (pin or "").strip()
        if not self.has_pin():
            if len(pin) < 4:
                return {"ok": False, "error": "pin_too_short"}
            self._set_pin(pin)
        elif not self.verify_pin(pin, client_id):
            return {"ok": False, "error": "wrong_pin"}
        self._save(enabled=True)
        self._unlocked[client_id] = self.now() + UNLOCK_SECONDS
        return {"ok": True}

    def disable(self, client_id: str) -> Dict[str, Any]:
        if not self.pro_ok():
            return {"ok": False, "error": "pro_required"}
        if not self.is_unlocked(client_id):
            return {"ok": False, "error": "locked"}
        self._save(enabled=False)
        return {"ok": True}

    def edit_terms(self, op: str, term: str, client_id: str) -> Dict[str, Any]:
        if not self.pro_ok():
            return {"ok": False, "error": "pro_required"}
        if not self.is_unlocked(client_id):
            return {"ok": False, "error": "locked"}
        speech = (actions.add_block if op == "add" else actions.remove_block)(
            self.store, term, is_owner=True)
        return {"ok": True, "speech": str(speech)}

    # -- enforcement (never Pro-gated: see the fail-safe note above) -----------

    def guard_for(self, client_id: str) -> Optional[actions.Guard]:
        """The Guard for this request: restrictive only when kid-safe is
        enabled and the client isn't PIN-unlocked."""
        if not self.enabled() or self.is_unlocked(client_id):
            return None
        return actions.Guard(restricted=True, blocklist=self.terms())
