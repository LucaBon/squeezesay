"""Squeezebox/LMS LAN discovery (UDP 3483 TLV).

Lets the local server and tools find the LMS server automatically, so the user
doesn't have to know or type its IP address. Squeezer does the same — it's the
expected UX for this ecosystem.
"""

from __future__ import annotations

import socket
import time
from typing import Dict, List, Optional


def _parse_tlv(buf: bytes) -> Dict[str, str]:
    out: Dict[str, str] = {}
    i = 0
    while i + 5 <= len(buf):
        tag = buf[i : i + 4].decode("ascii", "replace")
        length = buf[i + 4]
        out[tag] = buf[i + 5 : i + 5 + length].decode("utf-8", "replace")
        i += 5 + length
    return out


def discover(timeout: float = 2.0) -> List[Dict[str, str]]:
    """Broadcast a discovery request and return the LMS servers found on the LAN,
    each as ``{'ip', 'NAME', 'JSON'(port), 'VERS', ...}``. Never raises."""
    fields = [b"NAME", b"IPAD", b"JSON", b"VERS"]
    request = b"e" + b"".join(tag + b"\x00" for tag in fields)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    servers: List[Dict[str, str]] = []
    seen = set()
    try:
        sock.sendto(request, ("255.255.255.255", 3483))
    except OSError:
        sock.close()
        return servers
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(2048)
        except (socket.timeout, OSError):
            break
        if data[:1] != b"E" or addr[0] in seen:
            continue
        seen.add(addr[0])
        servers.append({"ip": addr[0], **_parse_tlv(data[1:])})
    sock.close()
    return servers


def discover_base_url(timeout: float = 2.0) -> Optional[str]:
    """The HTTP base URL (``http://<ip>:<port>``) of the first LMS found, or None."""
    servers = discover(timeout)
    if not servers:
        return None
    srv = servers[0]
    port = srv.get("JSON") or "9000"
    return f"http://{srv['ip']}:{port}"
