"""Per-install configuration and data directory, stdlib only.

Two jobs, shared by the license cache and the kid-safe store:

* ``env()`` — one place that knows the app's env-var namespace, so a future
  rename only touches the prefixes below (the old prefix keeps working for a
  release, with a deprecation note).
* ``data_dir()`` + atomic JSON read/write — one persistent directory per
  deploy target: Docker/HA pass ``--data-dir`` (a mounted volume), Windows
  gets ``%APPDATA%``, Linux/macOS the XDG data dir. Writes are atomic
  (tmp + ``os.replace``) so a crash mid-write never corrupts state.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

# Il namespace delle variabili d'ambiente. LEGACY_PREFIX (se impostato) viene
# letto come ripiego per un rilascio, poi sparisce: chi ha ancora i vecchi
# nomi configurati continua a funzionare ma vede l'avviso.
PRIMARY_PREFIX = "SQUEEZESAY"
LEGACY_PREFIX: Optional[str] = None

# Il nome della cartella dati per-utente (Windows %APPDATA%\<qui>, XDG in
# minuscolo su Linux/macOS).
APP_DIR_NAME = "SqueezeSay"

_warned_legacy = set()


def env(name: str, default: Optional[str] = None,
        environ=os.environ) -> Optional[str]:
    """Read ``<PRIMARY_PREFIX>_<name>``, falling back to the legacy prefix.

    The fallback prints a one-time deprecation note per variable, so existing
    setups keep working across the rename but users learn the new name.
    """
    value = environ.get(f"{PRIMARY_PREFIX}_{name}")
    if value is not None:
        return value
    if LEGACY_PREFIX:
        value = environ.get(f"{LEGACY_PREFIX}_{name}")
        if value is not None:
            if name not in _warned_legacy:
                _warned_legacy.add(name)
                print(f"Nota: {LEGACY_PREFIX}_{name} è deprecata, "
                      f"usa {PRIMARY_PREFIX}_{name}.")
            return value
    return default


def data_dir(cli_value: Optional[str] = None, environ=os.environ) -> str:
    """The directory for persistent server-side state, created on first use.

    Resolution order: explicit ``--data-dir`` → ``<PREFIX>_DATA_DIR`` env
    (Docker and the HA add-on already export it, pointing at their volume) →
    ``%APPDATA%`` on Windows → XDG data dir elsewhere.
    """
    path = cli_value or env("DATA_DIR", environ=environ)
    if not path:
        if os.name == "nt":
            base = environ.get("APPDATA") or os.path.expanduser("~")
            path = os.path.join(base, APP_DIR_NAME)
        else:
            base = environ.get("XDG_DATA_HOME") or os.path.expanduser(
                os.path.join("~", ".local", "share"))
            path = os.path.join(base, APP_DIR_NAME.lower())
    os.makedirs(path, exist_ok=True)
    return path


def read_json(path: str, default: Any = None) -> Any:
    """Parsed JSON content of ``path``, or ``default`` on any error.

    Fail-open on purpose: a missing or corrupt state file degrades to the
    defaults instead of taking the server down.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def atomic_write_json(path: str, obj: Any) -> None:
    """Write ``obj`` as JSON, atomically (same-volume tmp + ``os.replace``)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
