"""Speech-to-Text wrapper for NVIDIA Parakeet TDT 0.6B V3.

Adapted from the tested streaming_transcribe.py script.

Key implementation details:
1. NeMo transcribe() accepts audio=[(numpy_array, sample_rate)] tuples
   or file paths — we prefer direct arrays to skip disk I/O
2. MPS (Apple Silicon) IS supported -> model.to(torch.device("mps"))
3. 2s chunks with 0.5s overlap for transcript continuity
4. RMS-based silence detection skips quiet chunks
5. NeMo stderr suppressed during import and inference
"""

import asyncio
import logging
import os
import sys
import tempfile
import threading
import time
import warnings
from typing import Any

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

MOCK_MODE = os.getenv("STT_MOCK_MODE", "false").lower() == "true"

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHUNK_DURATION = 2.0
DEFAULT_OVERLAP_DURATION = 0.5
DEFAULT_SILENCE_THRESHOLD = 0.01
DEFAULT_MODEL = "nvidia/parakeet-tdt-0.6b-v3"


def _rms(audio: npt.NDArray[np.floating[Any]]) -> float:
    if len(audio) == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio**2)))


def _detect_device(preferred: str = "auto") -> str:
    import torch

    if preferred not in ("auto", "best"):
        if preferred == "cuda" and torch.cuda.is_available():
            return "cuda"
        if preferred == "mps" and torch.backends.mps.is_available():
            return "mps"
        logger.warning(
            "Requested device '%s' not available, falling back to auto", preferred
        )

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class _StderrSuppressor:
    """Suppress NeMo's extremely noisy stderr output."""

    def __enter__(self):  # type: ignore[no-untyped-def]
        self._real_stderr = sys.stderr
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        sys.stderr.close()
        sys.stderr = self._real_stderr


# ── Engine ────────────────────────────────────────────────────


class STTEngine:
    """Wraps Parakeet for use in the WebSocket pipeline.

    Lifecycle:
        engine = STTEngine()
        engine.load_model()
        transcript = await engine.transcribe(audio_float32)
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._device: str = "cpu"
        self._loaded = False

    def load_model(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str = "auto",
    ) -> None:
        """Load Parakeet into memory. Call once at app startup."""
        if MOCK_MODE:
            logger.info("STT running in MOCK MODE — no model loaded")
            self._loaded = True
            return

        os.environ["NEMO_VERBOSE"] = "0"
        warnings.filterwarnings("ignore")
        logging.getLogger("nemo_logger").setLevel(logging.ERROR)
        logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)
        logging.getLogger("lhotse").setLevel(logging.ERROR)

        import torch

        with _StderrSuppressor():
            import nemo.collections.asr as nemo_asr  # noqa: F811

        self._device = _detect_device(device)
        logger.info("Loading %s on %s...", model_name, self._device)
        start = time.time()

        with _StderrSuppressor():
            self._model = nemo_asr.models.ASRModel.from_pretrained(
                model_name=model_name
            )

        self._model.eval()

        if self._device == "mps":
            self._model = self._model.to(torch.device("mps"))
        elif self._device == "cpu":
            self._model = self._model.cpu()

        elapsed = time.time() - start
        if self._device == "cuda":
            mem = torch.cuda.memory_allocated() / 1e6
            logger.info(
                "Parakeet loaded in %.1fs — VRAM: %.0f MB (%s)",
                elapsed,
                mem,
                self._device,
            )
        else:
            logger.info("Parakeet loaded in %.1fs (%s)", elapsed, self._device)

        self._loaded = True

    async def transcribe(self, audio: npt.NDArray[np.floating[Any]]) -> str | None:
        """Transcribe float32 audio (16kHz mono) via thread pool.

        Returns text or None if too short / empty.
        """
        if not self._loaded:
            raise RuntimeError("STT model not loaded. Call load_model() first.")

        if len(audio) < DEFAULT_SAMPLE_RATE * 0.1:
            return None

        if MOCK_MODE:
            duration = len(audio) / DEFAULT_SAMPLE_RATE
            return f"[Mock transcript — {duration:.1f}s of audio]"

        from app.core.config import settings

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._transcribe_sync, audio),
                timeout=settings.STT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            from app.core.metrics import ML_INFERENCE_TIMEOUTS

            ML_INFERENCE_TIMEOUTS.labels(engine="stt").inc()
            logger.error(
                "STT inference timed out after %.1fs — dropping utterance",
                settings.STT_TIMEOUT_SECONDS,
            )
            return None

    def _transcribe_sync(self, audio: npt.NDArray[np.floating[Any]]) -> str | None:
        """Sync transcription — passes NumPy arrays directly to NeMo.

        Falls back to temp-file path if direct array input fails.
        """
        import torch

        try:
            with _StderrSuppressor():
                with torch.inference_mode():
                    outputs = self._model.transcribe(
                        audio=[audio],
                        batch_size=1,
                        verbose=False,
                    )

            if not outputs:
                return None

            text = outputs[0]
            if hasattr(text, "text"):
                text = text.text

            text = text.strip()
            return text if text else None

        except (TypeError, ValueError):
            # NeMo version doesn't support audio=[array] — fall back
            logger.warning(
                "NeMo transcribe() does not accept array input; "
                "falling back to temp file"
            )
            return self._transcribe_sync_file(audio)
        except Exception as e:
            logger.error("STT inference error: %s", e)
            return None
        finally:
            # Zero audio data to prevent leaking speech in crash dumps
            audio.fill(0)

    def _transcribe_sync_file(self, audio: npt.NDArray[np.floating[Any]]) -> str | None:
        """Fallback: transcription via temp file for older NeMo versions."""
        import soundfile as sf

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                sf.write(f.name, audio, DEFAULT_SAMPLE_RATE)
                tmp_path = f.name

            import torch

            with _StderrSuppressor():
                with torch.inference_mode():
                    outputs = self._model.transcribe(
                        [tmp_path], batch_size=1, verbose=False
                    )

            if not outputs:
                return None

            text = outputs[0]
            if hasattr(text, "text"):
                text = text.text

            text = text.strip()
            return text if text else None

        except Exception as e:
            logger.error("STT inference error (file fallback): %s", e)
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def device(self) -> str:
        return self._device

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
            self._loaded = False

            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            logger.info("STT model unloaded")


# ── Streaming Buffer ──────────────────────────────────────────


class StreamingSTTBuffer:
    """Per-meeting audio buffer supporting fixed-window and utterance modes.

    Modes:
        "fixed"     — Original 2-second chunk windows with overlap and RMS
                      silence detection. Backend-driven boundaries.
        "utterance" — Accumulates audio until the frontend signals an
                      utterance boundary via ``flush_utterance()``, or the
                      ``max_utterance_duration`` safety cap is hit.

    Usage (utterance mode):
        buffer = StreamingSTTBuffer(mode="utterance")
        buffer.feed(pcm_float32)

        # Periodic check — has_partial for interim transcripts
        if buffer.has_partial:
            audio, uid = buffer.peek_utterance()
            partial = await stt_engine.transcribe(audio)

        # Safety cap — continuous speech > max_utterance_duration
        if buffer.ready:
            audio, uid = buffer.get_chunk()
            final = await stt_engine.transcribe(audio)

        # Frontend sends utterance_end control message
        result = buffer.flush_utterance()
        if result is not None:
            audio, uid = result
            final = await stt_engine.transcribe(audio)

    Usage (fixed mode — unchanged):
        buffer = StreamingSTTBuffer(mode="fixed")
        buffer.feed(pcm_float32)
        if buffer.ready:
            audio = buffer.get_chunk()
            if audio is not None:
                transcript = await stt_engine.transcribe(audio)
    """

    # Minimum buffer length to consider for transcription (100ms at 16kHz)
    MIN_UTTERANCE_SAMPLES = 1600

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        mode: str = "utterance",
        # Fixed-mode parameters (original defaults)
        chunk_duration: float = DEFAULT_CHUNK_DURATION,
        overlap_duration: float = DEFAULT_OVERLAP_DURATION,
        silence_threshold: float = DEFAULT_SILENCE_THRESHOLD,
        # Utterance-mode parameters
        max_utterance_duration: float = 10.0,
        partial_threshold: float = 2.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.mode = mode

        # Fixed-mode settings
        self.chunk_samples = int(chunk_duration * sample_rate)
        self.overlap_samples = int(overlap_duration * sample_rate)
        self.silence_threshold = silence_threshold

        # Utterance-mode settings
        self.max_utterance_samples = int(max_utterance_duration * sample_rate)
        self.partial_threshold_samples = int(partial_threshold * sample_rate)

        # Shared state
        self._buffer = np.array([], dtype=np.float32)
        self._prev_overlap = np.array([], dtype=np.float32)
        self._lock = threading.Lock()

        # Utterance tracking
        self._current_utterance_id: str | None = None

    def _ensure_utterance_id(self) -> None:
        """Generate a new utterance_id if we don't have one."""
        if self._current_utterance_id is None:
            import uuid

            self._current_utterance_id = str(uuid.uuid4())

    def _rotate_utterance_id(self) -> None:
        """Force a new utterance_id (used after safety-cap flush)."""
        self._current_utterance_id = None

    @property
    def utterance_id(self) -> str | None:
        """Current utterance ID, or None if buffer is empty."""
        return self._current_utterance_id

    def feed(self, audio: npt.NDArray[np.floating[Any]]) -> None:
        """Append audio samples. Thread-safe."""
        with self._lock:
            self._buffer = np.concatenate(
                [self._buffer, audio.astype(np.float32)]
            )
            if self.mode == "utterance" and len(self._buffer) > 0:
                self._ensure_utterance_id()

    @property
    def ready(self) -> bool:
        """True when buffer should be flushed.

        Fixed mode: buffer >= chunk_duration.
        Utterance mode: only when max_utterance_duration safety cap is hit.
        """
        if self.mode == "fixed":
            return len(self._buffer) >= self.chunk_samples
        # Utterance mode — safety cap
        return len(self._buffer) >= self.max_utterance_samples

    @property
    def has_partial(self) -> bool:
        """True when utterance-mode buffer has enough audio for a partial.

        Only meaningful in utterance mode. Returns False in fixed mode.
        """
        if self.mode != "utterance":
            return False
        return len(self._buffer) >= self.partial_threshold_samples

    @property
    def duration(self) -> float:
        return len(self._buffer) / self.sample_rate

    def get_chunk(
        self,
    ) -> (
        npt.NDArray[np.floating[Any]]
        | tuple[npt.NDArray[np.floating[Any]], str]
        | None
    ):
        """Extract one chunk.

        Fixed mode: returns np.ndarray or None (silent).
        Utterance mode (safety-cap): returns (np.ndarray, utterance_id) or None.
        Auto-rotates utterance_id after safety-cap flush.
        """
        if self.mode == "fixed":
            return self._get_chunk_fixed()
        return self._get_chunk_utterance_cap()

    def _get_chunk_fixed(self) -> npt.NDArray[np.floating[Any]] | None:
        """Original fixed-window chunk extraction."""
        with self._lock:
            if len(self._buffer) < self.chunk_samples:
                return None

            chunk = self._buffer[: self.chunk_samples]
            self._buffer = self._buffer[self.chunk_samples :]

            if len(self._prev_overlap) > 0:
                full_audio = np.concatenate([self._prev_overlap, chunk])
            else:
                full_audio = chunk

            if self.overlap_samples > 0:
                self._prev_overlap = chunk[-self.overlap_samples :]
            else:
                self._prev_overlap = np.array([], dtype=np.float32)

        if _rms(chunk) < self.silence_threshold:
            return None

        return full_audio

    def _get_chunk_utterance_cap(
        self,
    ) -> tuple[npt.NDArray[np.floating[Any]], str] | None:
        """Safety-cap flush for utterance mode (continuous speech > max).

        No RMS silence check here — in utterance mode, the frontend VAD
        already strips silence. Discarding 10s of accumulated audio on
        a false RMS reading would be a destructive failure mode.
        """
        with self._lock:
            if len(self._buffer) < self.max_utterance_samples:
                return None

            audio = self._buffer.copy()
            self._buffer.fill(0)  # Zero before replacing
            self._buffer = np.array([], dtype=np.float32)
            uid = self._current_utterance_id or ""
            # Rotate ID so subsequent audio gets a new one (Edge Case #1)
            self._rotate_utterance_id()

        return (audio, uid)

    def flush_utterance(self) -> tuple[npt.NDArray[np.floating[Any]], str] | None:
        """Flush buffer on frontend utterance_end signal.

        Returns (audio, utterance_id) or None if buffer too short (< 100ms).
        Idempotent: consecutive calls on an empty buffer return None (Edge Case #2).
        """
        with self._lock:
            if len(self._buffer) < self.MIN_UTTERANCE_SAMPLES:
                return None

            audio = self._buffer.copy()
            self._buffer.fill(0)  # Zero before replacing
            self._buffer = np.array([], dtype=np.float32)
            uid = self._current_utterance_id or ""
            self._rotate_utterance_id()

        return (audio, uid)

    def peek_utterance(self) -> tuple[npt.NDArray[np.floating[Any]], str] | None:
        """Get a copy of accumulated audio without consuming it.

        Used for partial (interim) transcripts.
        """
        with self._lock:
            if len(self._buffer) < self.MIN_UTTERANCE_SAMPLES:
                return None
            audio = self._buffer.copy()
            uid = self._current_utterance_id or ""
        return (audio, uid)

    def flush(
        self,
    ) -> (
        npt.NDArray[np.floating[Any]]
        | tuple[npt.NDArray[np.floating[Any]], str]
        | None
    ):
        """Get remaining audio. Call when speaker stops or meeting ends.

        Fixed mode: returns np.ndarray or None.
        Utterance mode: returns (np.ndarray, utterance_id) or None.
        """
        with self._lock:
            if len(self._buffer) < self.sample_rate * 0.2:
                return None

            audio = self._buffer.copy()
            self._buffer.fill(0)  # Zero before replacing
            self._buffer = np.array([], dtype=np.float32)

            if self.mode == "fixed" and len(self._prev_overlap) > 0:
                audio = np.concatenate([self._prev_overlap, audio])
            if len(self._prev_overlap) > 0:
                self._prev_overlap.fill(0)
            self._prev_overlap = np.array([], dtype=np.float32)

            uid = self._current_utterance_id
            self._rotate_utterance_id()

        if _rms(audio) < self.silence_threshold:
            return None

        if self.mode == "utterance":
            return (audio, uid or "")
        return audio

    def clear(self) -> None:
        with self._lock:
            if len(self._buffer) > 0:
                self._buffer.fill(0)
            self._buffer = np.array([], dtype=np.float32)
            if len(self._prev_overlap) > 0:
                self._prev_overlap.fill(0)
            self._prev_overlap = np.array([], dtype=np.float32)
            self._rotate_utterance_id()


# ── Singleton ─────────────────────────────────────────────────
stt_engine = STTEngine()
