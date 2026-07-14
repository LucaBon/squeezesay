#!/usr/bin/env python3
"""Generate a self-signed TLS certificate for the local voice server.

The browser microphone (Web Speech API) needs a secure context (HTTPS) when the
page is opened from another device (e.g. your phone). This creates ``cert.pem``
and ``key.pem`` in the repo root, with the machine's LAN IPs in the certificate's
Subject Alternative Names so the host matches when you connect from the phone.

    uv run python tools/make_cert.py
    uv run python tools/make_cert.py --out /data --hosts 192.168.1.20,nas.local

``--out`` writes the pair somewhere else (the Docker entrypoint uses ``/data``);
``--hosts`` adds extra SANs (IPs or DNS names) for when the auto-detected
addresses aren't the ones clients will use — e.g. a container on a bridge
network only sees its internal IP, not the host's LAN IP.

It's a *self-signed* cert, so the browser shows a one-time "not private" warning:
tap "advanced -> proceed". After that the mic works.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import ipaddress
import os
import socket

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def local_ipv4s() -> list:
    ips = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    # also the address used to reach the default route
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ips)


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera cert.pem/key.pem self-signed "
                                             "per il server vocale locale.")
    ap.add_argument("--out", default=ROOT, metavar="DIR",
                    help="directory dove scrivere cert.pem/key.pem "
                         "(default: la radice del repo)")
    ap.add_argument("--hosts", default="", metavar="H1,H2,...",
                    help="SAN aggiuntivi, separati da virgola: IP o nomi DNS "
                         "(es. l'IP LAN dell'host quando si genera in un container)")
    args = ap.parse_args()

    cert_path = os.path.join(args.out, "cert.pem")
    key_path = os.path.join(args.out, "key.pem")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    ips = local_ipv4s()
    hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    sans = [x509.DNSName("localhost")]
    for ip in ips:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass
    for host in hosts:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            sans.append(x509.DNSName(host))  # non è un IP: lo trattiamo come nome DNS

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "impianto-locale")])
    # Fixed dates (no Date.now() needed): valid from 2024 for ~10 years.
    not_before = _dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc)
    not_after = _dt.datetime(2034, 1, 1, tzinfo=_dt.timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .sign(key, hashes.SHA256())
    )

    os.makedirs(args.out, exist_ok=True)
    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print(f"Creati:\n  {cert_path}\n  {key_path}")
    print("SAN (host validi):", ", ".join(ips + hosts + ["localhost"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
