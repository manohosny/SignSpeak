"""Speech-to-Text wrapper for NVIDIA Parakeet TDT 0.6B V3.

Adapted from the tested streaming_transcribe.py script.

Key implementation details:
1. NeMo transcribe() expects FILE PATHS -> write temp .wav before inference
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

import numpy as np

logger = logging.getLogger(__name__)

MOCK_MODE = os.getenv("STT_MOCK_MODE", "false").lower() == "true"

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHUNK_DURATION = 2.0
DEFAULT_OVERLAP_DURATION = 0.5
DEFAULT_SILENCE_THRESHOLD = 0.01
DEFAULT_MODEL = "nvidia/parakeet-tdt-0.6b-v3"


def _rms(audio: np.ndarray) -> float:
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
        self._model = None
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

    async def transcribe(self, audio: np.ndarray) -> str | None:
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

        return await asyncio.to_thread(self._transcribe_sync, audio)

    def _transcribe_sync(self, audio: np.ndarray) -> str | None:
        """Sync transcription via temp file (NeMo expects file paths)."""
        import soundfile as sf

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                sf.write(f.name, audio, DEFAULT_SAMPLE_RATE)
                tmp_path = f.name

            import torch

            with _StderrSuppressor():
                with torch.no_grad():
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
            logger.error("STT inference error: %s", e)
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
    """Per-meeting audio buffer with overlap and silence detection.

    Adapted from StreamingTranscriber in the working script.

    Usage:
        buffer = StreamingSTTBuffer()
        buffer.feed(pcm_float32)
        if buffer.ready:
            audio = buffer.get_chunk()   # None if silent
            if audio is not None:
                transcript = await stt_engine.transcribe(audio)
    """

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        chunk_duration: float = DEFAULT_CHUNK_DURATION,
        overlap_duration: float = DEFAULT_OVERLAP_DURATION,
        silence_threshold: float = DEFAULT_SILENCE_THRESHOLD,
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_samples = int(chunk_duration * sample_rate)
        self.overlap_samples = int(overlap_duration * sample_rate)
        self.silence_threshold = silence_threshold

        self._buffer = np.array([], dtype=np.float32)
        self._prev_overlap = np.array([], dtype=np.float32)
        self._lock = threading.Lock()

    def feed(self, audio: np.ndarray) -> None:
        """Append audio samples. Thread-safe."""
        with self._lock:
            self._buffer = np.concatenate(
                [self._buffer, audio.astype(np.float32)]
            )

    @property
    def ready(self) -> bool:
        """True when buffer has >= chunk_duration of audio."""
        return len(self._buffer) >= self.chunk_samples

    @property
    def duration(self) -> float:
        return len(self._buffer) / self.sample_rate

    def get_chunk(self) -> np.ndarray | None:
        """Extract one chunk with overlap for continuity.

        Returns None if chunk is silent (below RMS threshold).
        """
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

    def flush(self) -> np.ndarray | None:
        """Get remaining audio. Call when speaker stops or meeting ends."""
        with self._lock:
            if len(self._buffer) < self.sample_rate * 0.2:
                return None

            audio = self._buffer.copy()
            self._buffer = np.array([], dtype=np.float32)

            if len(self._prev_overlap) > 0:
                audio = np.concatenate([self._prev_overlap, audio])
            self._prev_overlap = np.array([], dtype=np.float32)

        if _rms(audio) < self.silence_threshold:
            return None

        return audio

    def clear(self) -> None:
        with self._lock:
            self._buffer = np.array([], dtype=np.float32)
            self._prev_overlap = np.array([], dtype=np.float32)


# ── Singleton ─────────────────────────────────────────────────
stt_engine = STTEngine()
