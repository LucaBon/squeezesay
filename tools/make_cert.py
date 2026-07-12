#!/usr/bin/env python3
"""Generate a self-signed TLS certificate for the local voice server.

The browser microphone (Web Speech API) needs a secure context (HTTPS) when the
page is opened from another device (e.g. your phone). This creates ``cert.pem``
and ``key.pem`` in the repo root, with the machine's LAN IPs in the certificate's
Subject Alternative Names so the host matches when you connect from the phone.

    uv run python tools/make_cert.py

It's a *self-signed* cert, so the browser shows a one-time "not private" warning:
tap "advanced -> proceed". After that the mic works.
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import os
import socket

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERT = os.path.join(ROOT, "cert.pem")
KEY = os.path.join(ROOT, "key.pem")


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
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    ips = local_ipv4s()
    sans = [x509.DNSName("localhost")]
    for ip in ips:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass

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

    with open(KEY, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    with open(CERT, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print(f"Creati:\n  {CERT}\n  {KEY}")
    print("SAN (host validi):", ", ".join(ips + ["localhost"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
