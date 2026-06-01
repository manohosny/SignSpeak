"""Tests for app.ml.translation — runs entirely in MOCK_MODE (no model download).

TRANSLATION_MOCK_MODE must be set before the module is imported so the
module-level MOCK_MODE constant is True.
"""

import asyncio
import os

# Set env var first (works when module hasn't been imported yet).
os.environ["TRANSLATION_MOCK_MODE"] = "true"

import pytest  # noqa: E402

import app.ml.translation as _translation_mod  # noqa: E402

# Patch module-level MOCK_MODE in case the module was already imported by
# another part of the test suite (e.g. ws tests importing handlers.py).
_translation_mod.MOCK_MODE = True

from app.ml.translation import (  # noqa: E402
    TranslationEngine,
    translation_engine,
    EN_LANG_CODE,
    ASL_LANG_CODE,
    DEFAULT_MODEL,
    _cached_translate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_loaded() -> None:
    """Load the mock engine if not already loaded."""
    if not translation_engine.is_loaded:
        translation_engine.load_model()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMockMode:
    def setup_method(self) -> None:
        _ensure_loaded()

    def test_mock_english_to_gloss(self) -> None:
        result = asyncio.run(translation_engine.english_to_gloss("I want to bake a cake"))
        assert result is not None
        assert result.isupper() or "MOCK" in result

    def test_mock_gloss_to_english(self) -> None:
        result = asyncio.run(translation_engine.gloss_to_english("IX WANT BAKE CAKE"))
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

    def test_mock_english_to_gloss_fixed_output(self) -> None:
        result = asyncio.run(translation_engine.english_to_gloss("anything"))
        assert result == "MOCK IX WANT BAKE CAKE"

    def test_mock_gloss_to_english_fixed_output(self) -> None:
        result = asyncio.run(translation_engine.gloss_to_english("IX BAKE"))
        assert result == "Mock: I want to bake a cake"


class TestLoadAndUnload:
    def test_load_sets_is_loaded(self) -> None:
        engine = TranslationEngine()
        assert not engine.is_loaded
        engine.load_model()
        assert engine.is_loaded

    def test_unload_clears_state(self) -> None:
        engine = TranslationEngine()
        engine.load_model()
        assert engine.is_loaded
        engine.unload()
        assert not engine.is_loaded

    def test_unload_singleton_clears_state(self) -> None:
        # Ensure singleton is loaded first
        _ensure_loaded()
        translation_engine.unload()
        assert not translation_engine.is_loaded
        # Re-load so other tests are not broken
        translation_engine.load_model()

    def test_load_model_is_idempotent_in_mock(self) -> None:
        engine = TranslationEngine()
        engine.load_model()
        engine.load_model()  # second call should not raise
        assert engine.is_loaded


class TestNotLoadedGuard:
    def test_english_to_gloss_raises_when_not_loaded(self) -> None:
        engine = TranslationEngine()
        with pytest.raises(RuntimeError, match="not loaded"):
            asyncio.run(engine.english_to_gloss("hello"))

    def test_gloss_to_english_raises_when_not_loaded(self) -> None:
        engine = TranslationEngine()
        with pytest.raises(RuntimeError, match="not loaded"):
            asyncio.run(engine.gloss_to_english("IX HELLO"))


class TestConstants:
    def test_default_model_name(self) -> None:
        assert DEFAULT_MODEL == "manohonsy/asl-mbart-50-lora"

    def test_lang_codes(self) -> None:
        assert EN_LANG_CODE == "en_XX"
        assert ASL_LANG_CODE == "asl_GL"

    def test_device_property(self) -> None:
        engine = TranslationEngine()
        assert engine.device == "cpu"


class TestCacheHelper:
    def test_cached_translate_exists(self) -> None:
        assert callable(_cached_translate)
        assert hasattr(_cached_translate, "cache_clear")
        assert hasattr(_cached_translate, "cache_info")

    def test_cache_clear_does_not_raise(self) -> None:
        _cached_translate.cache_clear()


class TestNoSharedTokenizerLock:
    """Verify the singleton no longer relies on a threading.Lock for tokenizer state."""

    def test_engine_has_no_lock_attribute(self) -> None:
        engine = TranslationEngine()
        assert not hasattr(engine, "_lock"), (
            "TranslationEngine should not carry a threading.Lock anymore -- "
            "tokenization is stateless via per-language tokenizer instances."
        )

    def test_engine_carries_per_language_tokenizers_field(self) -> None:
        engine = TranslationEngine()
        assert hasattr(engine, "_tokenizers")
        assert isinstance(engine._tokenizers, dict)

    def test_engine_carries_decode_tokenizer_field(self) -> None:
        engine = TranslationEngine()
        assert hasattr(engine, "_decode_tokenizer")

    def test_unload_clears_tokenizers(self) -> None:
        engine = TranslationEngine()
        engine.load_model()
        # In mock mode the tokenizers dict stays empty, but unload must still
        # leave it as an empty dict and reset _decode_tokenizer to None.
        engine.unload()
        assert engine._tokenizers == {}
        assert engine._decode_tokenizer is None


@pytest.mark.skipif(
    os.getenv("RUN_ML_INTEGRATION", "false").lower() != "true",
    reason="Set RUN_ML_INTEGRATION=true to exercise the real mBART-50 LoRA model",
)
class TestConcurrencyIntegration:
    """Interleaved en->asl and asl->en calls must not corrupt each other.

    Without per-language tokenizers, a race on tokenizer.src_lang would let one
    direction's input be tokenized with the other direction's special token.
    Result: silently wrong output. This test reproduces the race window.
    """

    def test_interleaved_directions_do_not_cross_contaminate(self) -> None:
        # Disable mock mode for this test.
        os.environ["TRANSLATION_MOCK_MODE"] = "false"
        _translation_mod.MOCK_MODE = False

        engine = TranslationEngine()
        engine.load_model()

        async def run() -> list[str | None]:
            tasks = []
            for _ in range(8):
                tasks.append(engine.english_to_gloss("I want to bake a cake"))
                tasks.append(engine.gloss_to_english("IX WANT BAKE CAKE"))
            return await asyncio.gather(*tasks)

        results = asyncio.run(run())
        en_to_asl = results[0::2]
        asl_to_en = results[1::2]

        # ASL gloss outputs should be mostly uppercase tokens; English outputs
        # should contain lowercase letters typical of an English sentence.
        for r in en_to_asl:
            assert r and r.replace(" ", "").isupper(), (
                f"Expected gloss-like (uppercase) output, got: {r!r}"
            )
        for r in asl_to_en:
            assert r and any(c.islower() for c in r), (
                f"Expected English-like (lowercase letters present) output, got: {r!r}"
            )

        engine.unload()
