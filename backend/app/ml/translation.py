"""ASL Translation engine wrapping an mBART-50 fine-tuned model.

Supports bidirectional translation:
    English (en_XX)  ->  ASL Gloss (asl_GL)
    ASL Gloss (asl_GL)  ->  English (en_XX)

Key implementation details:
1. MBart50TokenizerFast requires a custom lang code registration for asl_GL
2. fp16 on CUDA for memory efficiency; no fp16 on MPS (can be unstable)
3. LRU cache (512 entries) avoids repeated inference for identical inputs
4. threading.Lock guards mutable tokenizer state (src_lang) shared across threads
5. CPU auto-downgrades num_beams to 1 (greedy) to keep latency acceptable
"""

import asyncio
import functools
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

MOCK_MODE = os.getenv("TRANSLATION_MOCK_MODE", "false").lower() == "true"

DEFAULT_MODEL = "manohonsy/asl-mbart-50-lora"
EN_LANG_CODE = "en_XX"
ASL_LANG_CODE = "asl_GL"


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


# -- Engine -------------------------------------------------------------------


class TranslationEngine:
    """Wraps mBART-50 LoRA for English <-> ASL Gloss translation.

    Lifecycle:
        engine = TranslationEngine()
        engine.load_model()
        gloss = await engine.english_to_gloss("I want to bake a cake")
        english = await engine.gloss_to_english("IX WANT BAKE CAKE")
    """

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None
        self._device: str = "cpu"
        self._num_beams: int = 4
        self._max_length: int = 128
        self._loaded = False
        self._lock = threading.Lock()

    def load_model(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str = "auto",
        num_beams: int = 4,
        max_length: int = 128,
        dtype: str = "auto",
    ) -> None:
        """Load mBART-50 LoRA model into memory. Call once at app startup."""
        if MOCK_MODE:
            logger.info("Translation running in MOCK MODE -- no model loaded")
            self._loaded = True
            return

        from transformers import MBart50TokenizerFast, MBartForConditionalGeneration
        import torch

        self._device = _detect_device(device)
        logger.info("Loading %s on %s...", model_name, self._device)
        start = time.time()

        # Load tokenizer
        self._tokenizer = MBart50TokenizerFast.from_pretrained(model_name)

        # Register asl_GL language code if not already present
        if "asl_GL" not in self._tokenizer.lang_code_to_id:
            asl_id = self._tokenizer.convert_tokens_to_ids("asl_GL")
            self._tokenizer.lang_code_to_id["asl_GL"] = asl_id
            self._tokenizer.id_to_lang_code[asl_id] = "asl_GL"

        # Load model
        self._model = MBartForConditionalGeneration.from_pretrained(model_name)

        # Device placement
        if self._device == "cuda":
            if dtype != "fp32":
                self._model = self._model.half().to("cuda")
            else:
                self._model = self._model.to("cuda")
        elif self._device == "mps":
            # No fp16 on MPS -- can be unstable
            self._model = self._model.to(torch.device("mps"))
        # cpu: leave as-is

        self._model.eval()

        # Auto-downgrade num_beams on CPU to keep latency acceptable
        self._num_beams = num_beams
        if self._device == "cpu" and num_beams > 1:
            logger.warning(
                "CPU device detected with num_beams=%d; downgrading to greedy "
                "(num_beams=1) for acceptable latency",
                num_beams,
            )
            self._num_beams = 1

        self._max_length = max_length

        elapsed = time.time() - start
        if self._device == "cuda":
            mem = torch.cuda.memory_allocated() / 1e6
            logger.info(
                "Translation model loaded in %.1fs -- VRAM: %.0f MB (%s)",
                elapsed,
                mem,
                self._device,
            )
        else:
            logger.info(
                "Translation model loaded in %.1fs (%s)", elapsed, self._device
            )

        self._loaded = True

    async def english_to_gloss(self, text: str) -> str | None:
        """Translate English text to ASL gloss notation (async).

        Delegates to thread pool to avoid blocking the event loop.
        Returns None if translation fails or produces empty output.
        """
        if not self._loaded:
            raise RuntimeError(
                "Translation model not loaded. Call load_model() first."
            )

        if MOCK_MODE:
            return "MOCK IX WANT BAKE CAKE"

        return await asyncio.to_thread(
            _cached_translate, id(self), text, EN_LANG_CODE, ASL_LANG_CODE
        )

    async def gloss_to_english(self, gloss: str) -> str | None:
        """Translate ASL gloss notation to English text (async).

        Delegates to thread pool to avoid blocking the event loop.
        Returns None if translation fails or produces empty output.
        """
        if not self._loaded:
            raise RuntimeError(
                "Translation model not loaded. Call load_model() first."
            )

        if MOCK_MODE:
            return "Mock: I want to bake a cake"

        return await asyncio.to_thread(
            _cached_translate, id(self), gloss, ASL_LANG_CODE, EN_LANG_CODE
        )

    def _translate_sync(self, text: str, src_lang: str, tgt_lang: str) -> str | None:
        """Synchronous inference -- called via asyncio.to_thread (or cached wrapper).

        Uses a threading.Lock around tokenizer state mutation because
        MBart50TokenizerFast is not thread-safe (src_lang is mutable state).
        torch.no_grad() is used (not inference_mode) -- inference_mode
        interferes with beam search in mBART.
        """
        import torch

        try:
            with self._lock:
                self._tokenizer.src_lang = src_lang
                inputs = self._tokenizer(
                    text,
                    return_tensors="pt",
                    max_length=self._max_length,
                    truncation=True,
                )
                forced_bos = self._tokenizer.convert_tokens_to_ids(tgt_lang)

            # Move inputs to device (outside lock -- tensors are independent copies)
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            with torch.no_grad():
                output = self._model.generate(
                    **inputs,
                    forced_bos_token_id=forced_bos,
                    num_beams=self._num_beams,
                    max_length=self._max_length,
                )

            result = self._tokenizer.decode(output[0], skip_special_tokens=True).strip()
            return result if result else None

        except Exception as e:
            logger.error(
                "Translation inference error (%s -> %s): %s", src_lang, tgt_lang, e
            )
            return None

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
        if self._tokenizer is not None:
            del self._tokenizer
            self._tokenizer = None
        self._loaded = False

        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        _cached_translate.cache_clear()
        logger.info("Translation model unloaded")


# -- LRU Cache ----------------------------------------------------------------


@functools.lru_cache(maxsize=512)
def _cached_translate(
    engine_id: int, text: str, src_lang: str, tgt_lang: str
) -> str | None:
    """Cache translation results keyed by (engine_id, text, src_lang, tgt_lang).

    engine_id = id(translation_engine) ensures the cache is bound to the
    current engine instance and is invalidated via cache_clear() on unload/reload.
    """
    return translation_engine._translate_sync(text, src_lang, tgt_lang)


# -- Singleton ----------------------------------------------------------------
translation_engine = TranslationEngine()
