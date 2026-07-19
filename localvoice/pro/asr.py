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
import threading
from typing import Optional


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
