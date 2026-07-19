"""LMS discovery (``engine/discovery.py``) and the server-side cache.

Broadcast is the fast path; the unicast sweep is what keeps `docker compose up`
zero-config inside a bridge/NAT (the broadcast never leaves the container, but
LMS answers the same TLV request sent unicast). The sweep tests talk to a fake
LMS bound on loopback — no real network involved.
"""

import json
import socket
import threading

import discovery
import server as srv


def _tlv(**fields) -> bytes:
    out = b""
    for tag, value in fields.items():
        raw = value.encode()
        out += tag.encode() + bytes([len(raw)]) + raw
    return out


# -- protocollo TLV -----------------------------------------------------------

def test_request_asks_the_expected_fields():
    req = discovery._request()
    assert req[:1] == b"e"
    assert req[1:] == b"NAME\x00IPAD\x00JSON\x00VERS\x00"


def test_parse_tlv_roundtrip():
    parsed = discovery._parse_tlv(_tlv(NAME="daphile", JSON="9000", VERS="9.0.3"))
    assert parsed == {"NAME": "daphile", "JSON": "9000", "VERS": "9.0.3"}


def test_server_from_accepts_only_e_replies():
    good = discovery._server_from(b"E" + _tlv(NAME="x"), "10.0.0.9")
    assert good == {"ip": "10.0.0.9", "NAME": "x"}
    assert discovery._server_from(b"?" + _tlv(NAME="x"), "10.0.0.9") is None
    assert discovery._server_from(b"", "10.0.0.9") is None


def test_base_url_uses_json_port_with_9000_fallback():
    assert discovery.base_url({"ip": "1.2.3.4", "JSON": "9002"}) == "http://1.2.3.4:9002"
    assert discovery.base_url({"ip": "1.2.3.4"}) == "http://1.2.3.4:9000"
    assert discovery.base_url({"ip": "1.2.3.4", "JSON": ""}) == "http://1.2.3.4:9000"


# -- ordine delle subnet candidate --------------------------------------------

def test_candidate_phases_order_and_dedup(monkeypatch):
    # L'interfaccia locale coincide con una subnet comune: non va ripetuta.
    monkeypatch.setattr(discovery, "_local_prefixes",
                        lambda: ["192.168.1", "172.17.0"])
    phases = dict(discovery._candidate_phases())
    assert list(phases) == ["local", "common", "full"]
    assert phases["local"] == ["192.168.1", "172.17.0"]
    assert "192.168.1" not in phases["common"]          # già in "local"
    assert "10.0.0" in phases["common"]
    assert "192.168.1" not in phases["full"]            # niente doppioni
    assert "192.168.123" in phases["full"]              # il resto del /16 c'è
    all_prefixes = phases["local"] + phases["common"] + phases["full"]
    assert len(all_prefixes) == len(set(all_prefixes))


def test_local_prefixes_skips_loopback_and_link_local(monkeypatch):
    monkeypatch.setattr(discovery.socket, "gethostbyname_ex",
                        lambda _h: ("host", [], ["127.0.1.1", "169.254.3.4",
                                                "192.168.50.7"]))
    probe_fail = lambda *a, **k: (_ for _ in ()).throw(OSError())
    monkeypatch.setattr(discovery.socket.socket, "connect", probe_fail)
    assert discovery._local_prefixes() == ["192.168.50"]


# -- sweep unicast contro un finto LMS su loopback ----------------------------

def _fake_lms_on_loopback(reply=True):
    """A UDP socket bound to 127.0.0.1 that answers one discovery request."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    def run():
        sock.settimeout(5.0)
        try:
            data, addr = sock.recvfrom(2048)
            if reply and data[:1] == b"e":
                sock.sendto(b"E" + _tlv(NAME="testlms", JSON="9002"), addr)
        except OSError:
            pass

    threading.Thread(target=run, daemon=True).start()
    return port, sock


def test_unicast_sweep_finds_lms_and_reports_phases():
    port, sock = _fake_lms_on_loopback()
    seen_phases = []
    try:
        servers = discovery.discover_unicast(
            timeout=5.0, port=port, on_progress=seen_phases.append,
            phases=[("local", ["127.0.0"]), ("full", ["127.0.0"])])
    finally:
        sock.close()
    assert servers == [{"ip": "127.0.0.1", "NAME": "testlms", "JSON": "9002"}]
    # Early-exit: trovato nella prima fase, la seconda non parte nemmeno.
    assert seen_phases == ["local"]
    assert discovery.base_url(servers[0]) == "http://127.0.0.1:9002"


def test_unicast_sweep_gives_up_cleanly_when_nobody_answers():
    # Porta effimera senza nessuno in ascolto: lo sweep torna vuoto, senza
    # eccezioni (su Windows l'ICMP port-unreachable emerge come reset in recv).
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    free_port = probe.getsockname()[1]
    probe.close()
    servers = discovery.discover_unicast(
        timeout=1.0, port=free_port, phases=[("local", ["127.0.0"])])
    assert servers == []


def test_discover_base_url_falls_back_to_sweep(monkeypatch):
    monkeypatch.setattr(discovery, "discover", lambda timeout=2.0: [])
    monkeypatch.setattr(
        discovery, "discover_unicast",
        lambda on_progress=None: [{"ip": "192.168.123.72", "JSON": "9000"}])
    phases = []
    url = discovery.discover_base_url(on_progress=phases.append)
    assert url == "http://192.168.123.72:9000"
    assert phases == ["sweep"]


def test_discover_base_url_broadcast_wins_without_sweep(monkeypatch):
    monkeypatch.setattr(discovery, "discover",
                        lambda timeout=2.0: [{"ip": "10.0.0.5", "JSON": "9000"}])
    def boom(**_kw):
        raise AssertionError("sweep must not run when broadcast succeeds")
    monkeypatch.setattr(discovery, "discover_unicast", boom)
    assert discovery.discover_base_url() == "http://10.0.0.5:9000"


# -- cache lato server (riavvii istantanei) -----------------------------------

def test_lms_cache_roundtrip(tmp_path):
    data_dir = str(tmp_path)
    assert srv._cached_lms(data_dir) == ""            # niente file: nessun URL
    srv._save_cached_lms(data_dir, "http://192.168.123.72:9000")
    assert srv._cached_lms(data_dir) == "http://192.168.123.72:9000"
    raw = json.loads((tmp_path / "discovery_cache.json").read_text())
    assert raw == {"lms": "http://192.168.123.72:9000"}


def test_lms_cache_tolerates_corruption(tmp_path):
    (tmp_path / "discovery_cache.json").write_text("not json {")
    assert srv._cached_lms(str(tmp_path)) == ""


def test_lms_reachable_true_on_listening_port():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        assert srv._lms_reachable(f"http://127.0.0.1:{port}") is True
    finally:
        listener.close()


def test_lms_reachable_false_on_closed_port_or_junk():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    free_port = probe.getsockname()[1]
    probe.close()
    assert srv._lms_reachable(f"http://127.0.0.1:{free_port}", timeout=0.5) is False
    assert srv._lms_reachable("not-a-url") is False
