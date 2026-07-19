# Copyright (c) 2026 Luca Bonura. Proprietary — see licenses/PRO-EULA.md.
# Not covered by the repository's AGPL-3.0 license.
"""Local speech recognition (Pro): server-side Whisper for the web app's mic.

The browser's Web Speech API ships the audio to Google/Apple; this module
closes that last gap in the "everything stays home" promise. The page records
with MediaRecorder and POSTs the clip to ``/transcribe``; here faster-whisper
(CTranslate2, int8 on CPU) turns it into text without any packet leaving the
LAN.

faster-whisper is an *optional* dependency (``uv sync --group asr``) — the
core stays stdlib-only. Without it :meth:`WhisperTranscriber.available`
answers ``False`` and the endpoints degrade politely; nothing else changes.
The model (``--asr-model`` / ``VIVAVOCE_ASR_MODEL``, default ``small``) is
downloaded on first use into the app's data dir, so in Docker it lands in the
persistent volume and survives image updates.
"""

from __future__ import annotations

import importlib.util
import io
import os
import threading
from typing import Optional

# Sotto questa RAM totale il riconoscimento locale resta SPENTO di default.
# Misurato sui fixture italiani: tiny e base trascrivono bene i comandi in
# puro italiano ma storpiano i titoli inglesi ("Comfortably Numb" →
# "fatta blina"), e i titoli sono il cuore del prodotto; small è il primo
# modello utilizzabile ma al picco vuole ~1 GB, che su una macchina da 2 GB
# con sopra OS e LMS non ci sta. Un --asr-model esplicito forza comunque:
# una casa che usa solo comandi di trasporto può scegliere tiny a ragion
# veduta. (Soglia a 3.5 così una "4 GB" reale, che ne riporta ~3.8, passa.)
MIN_RAM_GIB = 3.5


def total_ram_gib() -> float:
    """Total machine RAM in GiB — best-effort, stdlib only (0.0 = unknown)."""
    try:
        if os.name == "nt":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_uint32),
                            ("dwMemoryLoad", ctypes.c_uint32),
                            ("ullTotalPhys", ctypes.c_uint64),
                            ("ullAvailPhys", ctypes.c_uint64),
                            ("ullTotalPageFile", ctypes.c_uint64),
                            ("ullAvailPageFile", ctypes.c_uint64),
                            ("ullTotalVirtual", ctypes.c_uint64),
                            ("ullAvailVirtual", ctypes.c_uint64),
                            ("ullAvailExtendedVirtual", ctypes.c_uint64)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return stat.ullTotalPhys / (1024 ** 3)
        else:
            return (os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
                    / (1024 ** 3))
    except (OSError, ValueError, AttributeError):
        pass
    return 0.0


def default_model(total_gib: Optional[float] = None) -> Optional[str]:
    """The Whisper model to use when none is configured; ``None`` = leave
    local recognition off on this machine (see ``MIN_RAM_GIB``). Unknown RAM
    (probe failed, 0.0) counts as capable: better a slow box that works than
    a capable box crippled by a failed probe."""
    if total_gib is None:
        total_gib = total_ram_gib()
    if total_gib and total_gib < MIN_RAM_GIB:
        return None
    return "small"


class WhisperTranscriber:
    """Turns an audio blob (webm/opus, wav, ...) into text, entirely on-box.

    Construction is always cheap and safe: the heavy import and the model
    load/download happen lazily on the first :meth:`transcribe`, guarded by a
    lock (the HTTP server is threaded). ``available()`` only probes for the
    package, so the server can report ``/asr`` state without paying anything.
    """

    def __init__(self, model: str = "small",
                 cache_dir: Optional[str] = None) -> None:
        self.model_name = model
        self.cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                # int8 su CPU: il compromesso giusto per un mini-PC/NAS di
                # casa — niente GPU richiesta, ~1 GB di RAM col modello small.
                self._model = WhisperModel(
                    self.model_name, device="cpu", compute_type="int8",
                    download_root=self.cache_dir)
            return self._model

    def transcribe(self, audio: bytes, lang: str = "it") -> dict:
        """``{"text": ..., "alternatives": [...]}`` for one recorded command.

        Whisper decodes the container itself (PyAV), so webm/opus from
        MediaRecorder and plain wav both work. It has no n-best output: the
        alternatives list carries the single transcript, and the /command
        mechanism downstream treats it exactly like the browser's list.
        """
        model = self._load()
        segments, _info = model.transcribe(
            io.BytesIO(audio), language=(lang or None), beam_size=5)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return {"text": text, "alternatives": [text] if text else []}
