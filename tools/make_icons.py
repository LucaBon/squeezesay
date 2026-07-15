#!/usr/bin/env python3
"""Generate the PWA icons (localvoice/icon-192.png, icon-512.png), stdlib only.

A PNG writer over zlib/struct — no Pillow — drawing the app icon: an amber
eighth note on the app's hi-fi dark plate, ringed in brand green, full-bleed
(so the same file works both as a normal icon and as a maskable one; note and
ring sit inside the central safe zone). Icons are deterministic: re-running
produces byte-identical files, so they are committed and this script only
needs to run when the design changes.

    uv run python tools/make_icons.py
"""

from __future__ import annotations

import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "localvoice")

BG = (14, 19, 17)       # #0e1311 — the app's hi-fi dark background
FG = (232, 161, 60)     # #e8a13c — the amber VU accent (the note)
RING = (45, 125, 70)    # #2d7d46 — brand green ring
SS = 3                  # supersampling factor (cheap antialiasing)


def _note_hit(x: float, y: float) -> bool:
    """Is the (0..1, 0..1) point inside the eighth-note glyph? Drawn inside the
    central ~60% so launcher masks (circle/squircle) never cut it."""
    # note head: ellipse, slightly squashed and tilted feel via wider x radius
    hx, hy, rx, ry = 0.435, 0.660, 0.130, 0.100
    if ((x - hx) / rx) ** 2 + ((y - hy) / ry) ** 2 <= 1.0:
        return True
    # stem: vertical bar from the head's right edge up
    if 0.535 <= x <= 0.585 and 0.300 <= y <= 0.665:
        return True
    # flag: parallelogram sweeping right-down from the stem top
    if 0.300 <= y <= 0.470:
        t = (y - 0.300) / 0.170          # 0 at top -> 1 at bottom of the flag
        x0 = 0.535 + 0.16 * t            # left edge slides right going down
        if x0 <= x <= x0 + 0.085:
            return True
    return False


def _ring_hit(x: float, y: float) -> bool:
    """Thin circular ring inside the maskable safe zone (radius <= 0.40)."""
    r = ((x - 0.5) ** 2 + (y - 0.5) ** 2) ** 0.5
    return 0.365 <= r <= 0.395


def _render(size: int) -> list:
    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            note = ring = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = (px + (sx + 0.5) / SS) / size
                    y = (py + (sy + 0.5) / SS) / size
                    if _note_hit(x, y):
                        note += 1
                    elif _ring_hit(x, y):
                        ring += 1
            an = note / (SS * SS)
            ar = ring / (SS * SS)
            ab = 1 - an - ar
            r = round(BG[0] * ab + FG[0] * an + RING[0] * ar)
            g = round(BG[1] * ab + FG[1] * an + RING[1] * ar)
            b = round(BG[2] * ab + FG[2] * an + RING[2] * ar)
            row.append((r, g, b, 255))
        rows.append(row)
    return rows


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: str, rows: list) -> None:
    h = len(rows)
    w = len(rows[0])
    raw = b"".join(
        b"\x00" + bytes(v for px in row for v in px) for row in rows
    )
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
    png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
           + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main() -> int:
    for size in (192, 512):
        path = os.path.join(OUT_DIR, f"icon-{size}.png")
        write_png(path, _render(size))
        print(f"Creato: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
