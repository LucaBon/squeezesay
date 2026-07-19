"""Squeezebox/LMS LAN discovery (UDP 3483 TLV).

Lets the local server and tools find the LMS server automatically, so the user
doesn't have to know or type its IP address. Squeezer does the same — it's the
expected UX for this ecosystem.

Two strategies, tried in order:

1. ``discover()`` — one broadcast request. Instant on a real LAN interface.
2. ``discover_unicast()`` — LMS answers the same TLV request sent *unicast*
   (verified against LMS 9), so when broadcast gets no reply — inside a Docker
   bridge/NAT the broadcast never leaves the container — we sweep candidate
   private subnets host by host and stop at the first answer. Outbound unicast
   UDP crosses Docker's NAT fine, which keeps `docker compose up` zero-config
   on Docker Desktop too.
"""

from __future__ import annotations

import select
import socket
import time
from typing import Callable, Dict, List, Optional, Tuple

DISCOVERY_PORT = 3483

# Densely-used home /24s, tried before the exhaustive 192.168/16 pass:
# factory defaults of common routers (.0/.1/.2, FRITZ!Box .178/.188,
# some ISP boxes .100) plus the usual 10.x and 172.16 picks.
_COMMON_PREFIXES = [
    "192.168.0", "192.168.1", "192.168.2", "192.168.100",
    "192.168.178", "192.168.188", "10.0.0", "10.0.1", "10.1.1", "172.16.0",
]


def _request() -> bytes:
    fields = [b"NAME", b"IPAD", b"JSON", b"VERS"]
    return b"e" + b"".join(tag + b"\x00" for tag in fields)


def _parse_tlv(buf: bytes) -> Dict[str, str]:
    out: Dict[str, str] = {}
    i = 0
    while i + 5 <= len(buf):
        tag = buf[i : i + 4].decode("ascii", "replace")
        length = buf[i + 4]
        out[tag] = buf[i + 5 : i + 5 + length].decode("utf-8", "replace")
        i += 5 + length
    return out


def _server_from(data: bytes, ip: str) -> Optional[Dict[str, str]]:
    """A ``{'ip', 'NAME', 'JSON', ...}`` record if ``data`` is an LMS reply."""
    if data[:1] != b"E":
        return None
    return {"ip": ip, **_parse_tlv(data[1:])}


def base_url(server: Dict[str, str]) -> str:
    """The HTTP base URL of a discovered server record."""
    port = server.get("JSON") or "9000"
    return f"http://{server['ip']}:{port}"


def discover(timeout: float = 2.0, port: int = DISCOVERY_PORT) -> List[Dict[str, str]]:
    """Broadcast a discovery request and return the LMS servers found on the LAN,
    each as ``{'ip', 'NAME', 'JSON'(port), 'VERS', ...}``. Never raises."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    servers: List[Dict[str, str]] = []
    seen = set()
    try:
        sock.sendto(_request(), ("255.255.255.255", port))
    except OSError:
        sock.close()
        return servers
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(2048)
        except (socket.timeout, OSError):
            break
        if addr[0] in seen:
            continue
        srv = _server_from(data, addr[0])
        if srv:
            seen.add(addr[0])
            servers.append(srv)
    sock.close()
    return servers


def _local_prefixes() -> List[str]:
    """/24 prefixes ("192.168.123") of this host's IPv4 interfaces."""
    ips = set()
    # Primary outbound interface: a UDP connect() picks the routing table's
    # answer without sending anything (TEST-NET-1 destination, never reached).
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("192.0.2.1", 9))
        ips.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except OSError:
        pass
    prefixes = []
    for ip in sorted(ips):
        if ip.startswith(("127.", "169.254.")):
            continue
        prefix = ip.rsplit(".", 1)[0]
        if prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def _candidate_phases() -> List[Tuple[str, List[str]]]:
    """Ordered sweep phases as ``(name, [/24 prefixes])``, no duplicates:
    local interfaces first, then common home subnets, then all of 192.168/16."""
    seen: set = set()
    phases: List[Tuple[str, List[str]]] = []
    for name, prefixes in [
        ("local", _local_prefixes()),
        ("common", _COMMON_PREFIXES),
        ("full", [f"192.168.{i}" for i in range(256)]),
    ]:
        fresh = [p for p in prefixes if p not in seen]
        seen.update(fresh)
        if fresh:
            phases.append((name, fresh))
    return phases


def discover_unicast(
    timeout: float = 30.0,
    port: int = DISCOVERY_PORT,
    on_progress: Optional[Callable[[str], None]] = None,
    phases: Optional[List[Tuple[str, List[str]]]] = None,
) -> List[Dict[str, str]]:
    """Sweep candidate subnets with unicast discovery requests and return the
    first LMS that answers (as a one-element list; empty if none). Never raises.

    ``on_progress`` (if given) is called with the phase name ("local",
    "common", "full") as each begins. Replies are polled every few dozen
    packets — early exit on the first valid answer, so on a typical network
    this returns in well under a second once the right subnet is reached.

    When the socket's send buffer fills (a full 192.168/16 pass is ~65k
    packets — through Docker/WSL NAT the kernel drains slower than we send),
    we wait for writability and retry instead of dropping: a silent drop here
    once cost the one packet that mattered. This self-paces the sweep to
    whatever the network layer actually sustains.
    """
    request = _request()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
        try:
            sock.setsockopt(socket.SOL_SOCKET, opt, 1 << 20)
        except OSError:
            pass
    deadline = time.time() + timeout
    found: List[Dict[str, str]] = []

    def _poll(wait: float) -> None:
        end = time.time() + wait
        while not found and time.time() < end:
            ready, _, _ = select.select([sock], [], [], max(0.0, end - time.time()))
            if not ready:
                return
            while True:
                try:
                    data, addr = sock.recvfrom(2048)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:
                    # Windows surfaces ICMP port-unreachable from swept hosts
                    # as ConnectionResetError on recv: ignore and keep reading.
                    continue
                srv = _server_from(data, addr[0])
                if srv:
                    found.append(srv)
                    return

    def _send(dest: Tuple[str, int]) -> None:
        while time.time() < deadline and not found:
            try:
                sock.sendto(request, dest)
                return
            except BlockingIOError:
                # Send buffer full: drain any replies, then wait until the
                # kernel is ready to take more packets. Never drop.
                _poll(0.002)
                select.select([], [sock], [], 0.05)
            except OSError:
                return  # unroutable address: skip it

    try:
        sent = 0
        for name, prefixes in phases or _candidate_phases():
            if on_progress:
                on_progress(name)
            for prefix in prefixes:
                for host in range(1, 255):
                    _send((f"{prefix}.{host}", port))
                    sent += 1
                    if sent % 64 == 0:
                        _poll(0.002)
                if found or time.time() > deadline:
                    return found
        # Stragglers: the last bursts' replies may still be in flight.
        _poll(min(1.5, max(0.0, deadline - time.time())))
        return found
    finally:
        sock.close()


def discover_base_url(
    timeout: float = 2.0,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """The HTTP base URL (``http://<ip>:<port>``) of the first LMS found, or
    None. Tries broadcast first, then the unicast sweep (``on_progress`` gets
    "sweep" before it starts, then the sweep's phase names)."""
    servers = discover(timeout)
    if not servers:
        if on_progress:
            on_progress("sweep")
        servers = discover_unicast(on_progress=on_progress)
    if not servers:
        return None
    return base_url(servers[0])
