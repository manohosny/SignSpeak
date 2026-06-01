"""ASL Translation engine wrapping an mBART-50 fine-tuned model.

Supports bidirectional translation:
    English (en_XX)  ->  ASL Gloss (asl_GL)
    ASL Gloss (asl_GL)  ->  English (en_XX)

Key implementation details:
1. MBart50TokenizerFast requires a custom lang code registration for asl_GL
2. fp16 on CUDA for memory efficiency; no fp16 on MPS (can be unstable)
3. LRU cache (512 entries) avoids repeated inference for identical inputs
4. Pre-built per-language tokenizers eliminate the need for a thread lock on
   shared tokenizer state (one tokenizer per src_lang, no mutation at inference).
   The shared model itself is NOT thread-safe, so model.generate() is guarded
   by a threading.Lock — inference runs in the asyncio.to_thread pool and
   concurrent translations would otherwise interleave on the same model.
5. CPU auto-downgrades num_beams to 1 (greedy) to keep latency acceptable
"""

import asyncio
import copy
import functools
import logging
import os
import threading
import time
from typing import Any

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
        self._tokenizers: dict[str, Any] = {}
        self._decode_tokenizer: Any = None
        self._device: str = "cpu"
        self._num_beams: int = 4
        self._max_length: int = 128
        self._loaded = False
        # Serializes model.generate() across asyncio.to_thread worker threads —
        # the underlying PyTorch model is shared and not thread-safe.
        self._inference_lock = threading.Lock()

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

        # Load tokenizer — extra_special_tokens={} overrides the list stored in
        # tokenizer_config.json (saved with older transformers) which newer
        # transformers incorrectly expects to be a dict and calls .keys() on it.
        base_tokenizer = MBart50TokenizerFast.from_pretrained(
            model_name, extra_special_tokens={}
        )

        # Register asl_GL language code if not already present.
        # id_to_lang_code only exists on MBart50Tokenizer (slow), not the fast variant.
        if "asl_GL" not in base_tokenizer.lang_code_to_id:
            asl_id = base_tokenizer.convert_tokens_to_ids("asl_GL")
            base_tokenizer.lang_code_to_id["asl_GL"] = asl_id

        # Pre-build one tokenizer per source language so inference is stateless
        # and no lock is needed around the mutable tokenizer.src_lang setter.
        en_tokenizer = copy.deepcopy(base_tokenizer)
        en_tokenizer.src_lang = EN_LANG_CODE
        asl_tokenizer = copy.deepcopy(base_tokenizer)
        asl_tokenizer.src_lang = ASL_LANG_CODE
        self._tokenizers = {
            EN_LANG_CODE: en_tokenizer,
            ASL_LANG_CODE: asl_tokenizer,
        }
        # decode() with skip_special_tokens is language-agnostic; pin one for clarity.
        self._decode_tokenizer = en_tokenizer

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

        # Auto-downgrade num_beams to greedy on CPU and MPS — beam search is
        # too slow on both for real-time use (CPU: obvious; MPS: limited op support).
        self._num_beams = num_beams
        if self._device in ("cpu", "mps") and num_beams > 1:
            logger.warning(
                "%s device detected with num_beams=%d; downgrading to greedy "
                "(num_beams=1) for acceptable latency",
                self._device,
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

        Tokenization is stateless: each src_lang has its own pre-configured
        tokenizer instance, so no lock is required.
        torch.no_grad() is used (not inference_mode) -- inference_mode
        interferes with beam search in mBART.
        """
        import torch

        try:
            tokenizer = self._tokenizers[src_lang]
            inputs = tokenizer(
                text,
                return_tensors="pt",
                max_length=self._max_length,
                truncation=True,
            )
            forced_bos = tokenizer.convert_tokens_to_ids(tgt_lang)

            # Move inputs to device.
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            # The model is shared across worker threads and is not
            # thread-safe — serialize the actual generate() call. Tokenize
            # (above) and decode (below) are stateless / read-only and stay
            # outside the lock.
            with self._inference_lock, torch.no_grad():
                output = self._model.generate(
                    **inputs,
                    forced_bos_token_id=forced_bos,
                    num_beams=self._num_beams,
                    max_length=self._max_length,
                )

            result = self._decode_tokenizer.decode(
                output[0], skip_special_tokens=True
            ).strip()
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
        self._tokenizers.clear()
        self._decode_tokenizer = None
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
