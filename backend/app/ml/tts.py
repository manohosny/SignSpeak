"""Text-to-Speech wrapper for Kokoro 82M (ONNX Runtime).

Adapted from the tested voice_assistant.py script.

Key implementation details:
1. Uses kokoro_onnx package (NOT the PyTorch 'kokoro' package)
   -> from kokoro_onnx import Kokoro
2. Constructor: Kokoro(model_path, voices_path)
   -> Needs kokoro-v1.0.onnx and voices-v1.0.bin files
3. Async streaming via create_stream() yields (samples, sample_rate)
4. Runs on CPU via ONNX Runtime (no GPU needed, fast for 82M params)

Setup:
    pip install kokoro-onnx
    # Download: kokoro-v1.0.onnx and voices-v1.0.bin
"""

import asyncio
import logging
import os
import time
from collections.abc import AsyncGenerator

import numpy as np

from app.ml.audio_utils import float32_to_wav_bytes

logger = logging.getLogger(__name__)

MOCK_MODE = os.getenv("TTS_MOCK_MODE", "false").lower() == "true"

DEFAULT_MODEL_PATH = os.getenv("KOKORO_MODEL_PATH", "kokoro-v1.0.onnx")
DEFAULT_VOICES_PATH = os.getenv("KOKORO_VOICES_PATH", "voices-v1.0.bin")
DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.05
DEFAULT_LANG = "en-us"


class TTSEngine:
    """Wraps Kokoro ONNX for the WebSocket pipeline.

    Lifecycle:
        engine = TTSEngine()
        engine.load_model()
        wav_bytes = await engine.synthesize("Hello!")
    """

    def __init__(self) -> None:
        self._kokoro = None
        self._loaded = False

    def load_model(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        voices_path: str = DEFAULT_VOICES_PATH,
    ) -> None:
        """Load Kokoro ONNX model. Call once at app startup."""
        if MOCK_MODE:
            logger.info("TTS running in MOCK MODE — no model loaded")
            self._loaded = True
            return

        try:
            from kokoro_onnx import Kokoro

            if not os.path.exists(model_path):
                raise FileNotFoundError(
                    f"Kokoro model not found: {model_path}\n"
                    f"Download from: https://github.com/thewh1teagle/kokoro-onnx"
                )
            if not os.path.exists(voices_path):
                raise FileNotFoundError(
                    f"Kokoro voices not found: {voices_path}\n"
                    f"Download from: https://github.com/thewh1teagle/kokoro-onnx"
                )

            logger.info("Loading Kokoro TTS model...")
            start = time.time()

            self._kokoro = Kokoro(model_path, voices_path)

            self._loaded = True
            elapsed = time.time() - start
            logger.info("Kokoro TTS loaded in %.2fs", elapsed)

        except ImportError:
            logger.error(
                "kokoro-onnx not installed. Install with: pip install kokoro-onnx"
            )
            raise

    async def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        speed: float = DEFAULT_SPEED,
        lang: str = DEFAULT_LANG,
    ) -> bytes:
        """Synthesize text to WAV bytes.

        Collects all stream chunks into a single WAV.
        Runs in thread pool to avoid blocking the event loop.
        """
        if not self._loaded:
            raise RuntimeError("TTS model not loaded. Call load_model() first.")

        if not text or not text.strip():
            raise ValueError("Cannot synthesize empty text")

        if MOCK_MODE:
            return self._silent_wav(duration=0.5)

        return await asyncio.to_thread(
            self._synthesize_sync, text, voice, speed, lang
        )

    def _synthesize_sync(
        self, text: str, voice: str, speed: float, lang: str
    ) -> bytes:
        """Sync synthesis via Kokoro's async stream.

        Uses asyncio.run() because create_stream() is async,
        but we're in a thread so a new event loop is safe.
        """
        try:
            audio_chunks = asyncio.run(
                self._collect_stream_chunks(text, voice, speed, lang)
            )

            if not audio_chunks:
                logger.warning("TTS produced no audio for: %s...", text[:50])
                return self._silent_wav()

            all_samples = np.concatenate(
                [samples for samples, _ in audio_chunks]
            )
            sample_rate = audio_chunks[0][1]

            return float32_to_wav_bytes(all_samples, sample_rate)

        except Exception as e:
            logger.error("TTS inference error: %s", e)
            return self._silent_wav()

    async def _collect_stream_chunks(
        self, text: str, voice: str, speed: float, lang: str
    ) -> list[tuple[np.ndarray, int]]:
        """Collect all chunks from Kokoro's async stream."""
        chunks: list[tuple[np.ndarray, int]] = []
        stream = self._kokoro.create_stream(
            text, voice=voice, speed=speed, lang=lang
        )
        async for samples, sample_rate in stream:
            chunks.append((samples, sample_rate))
        return chunks

    async def synthesize_streaming(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        speed: float = DEFAULT_SPEED,
        lang: str = DEFAULT_LANG,
    ) -> AsyncGenerator[bytes, None]:
        """Async generator yielding WAV chunks as they're synthesized.

        Use for lower latency — send each chunk immediately.

        Usage:
            async for wav_bytes in engine.synthesize_streaming("Hello"):
                await websocket.send_bytes(wav_bytes)
        """
        if not self._loaded:
            raise RuntimeError("TTS model not loaded.")

        if MOCK_MODE:
            yield self._silent_wav(duration=0.5)
            return

        stream = self._kokoro.create_stream(
            text, voice=voice, speed=speed, lang=lang
        )

        chunks_yielded = 0
        async for samples, sample_rate in stream:
            wav_bytes = float32_to_wav_bytes(samples, sample_rate)
            chunks_yielded += 1
            yield wav_bytes

        if chunks_yielded == 0:
            yield self._silent_wav()

    def _silent_wav(
        self, duration: float = 0.1, sample_rate: int = 24000
    ) -> bytes:
        num_samples = int(sample_rate * duration)
        silence = np.zeros(num_samples, dtype=np.float32)
        return float32_to_wav_bytes(silence, sample_rate)

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def unload(self) -> None:
        if self._kokoro is not None:
            del self._kokoro
            self._kokoro = None
            self._loaded = False
            logger.info("TTS model unloaded")


# ── Singleton ─────────────────────────────────────────────────
tts_engine = TTSEngine()
